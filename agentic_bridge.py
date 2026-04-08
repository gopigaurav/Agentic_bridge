"""
Agentic Bridge - Local AI Agent for qwen2.5-coder
==================================================
A complete agentic AI system that allows local LLM models to perform actions
similar to Claude/GitHub Copilot.

Features:
- Multi-step planning and execution
- Tool-based architecture (file ops, commands, git, search)
- Safety layer with confirmation for destructive actions
- Conversation memory and context tracking
- HTTP server and REPL interfaces
"""

import subprocess
import sys
import os
import json
import re
import hashlib
import tempfile
import atexit
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple, Literal
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import copy
import shutil
from difflib import unified_diff
from pathlib import Path

# Try to import requests, fall back to urllib if not available
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    import urllib.request
    import urllib.error
    HAS_REQUESTS = False

# --- CONFIG ---
OLLAMA_MODEL = "qwen3.5"
OLLAMA_API_URL = "http://localhost:11434/api/generate"
CHAT_API_URL = "http://localhost:11434/api/chat"

# Safety configuration
DESTRUCTIVE_COMMANDS = [
    "rm ", "del ", "rmdir ", "remove-item ",
    "format ", "fdisk ", "mkfs ",
    "chmod 777 ", "chown ",
    "> ", ">> ",  # redirections that can overwrite
    "dd ", "shutdown ", "reboot ",
    "git reset --hard", "git clean -fd", "git push --force"
]

SAFE_COMMAND_PREFIXES = [
    "ls ", "dir ", "cat ", "type ", "head ", "tail ",
    "grep ", "find ", "where ", "which ",
    "git status ", "git diff ", "git log ", "git show ",
    "pwd ", "whoami ", "date ", "echo ",
    "python ", "python3 ", "node ", "npm ", "pip ",
    "cargo ", "go ", "rustc ", "javac ", "java "
]

ALLOWED_FILE_EXTENSIONS = [
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs", ".c", ".cpp", ".h",
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".html", ".css", ".scss", ".less", ".vue", ".svelte",
    ".sh", ".bat", ".ps1", ".zsh", ".fish",
    ".sql", ".graphql", ".proto",
    ".env", ".gitignore", ".dockerignore"
]


# =============================================================================
# CONVERSATION MEMORY
# =============================================================================

class ConversationMemory:
    """Maintains conversation history and context."""

    def __init__(self, max_turns: int = 20):
        self.max_turns = max_turns
        self.turns: List[Dict[str, Any]] = []
        self.context_variables: Dict[str, Any] = {}

    def add_turn(self, role: str, content: str, actions: List[Dict] = None):
        """Add a turn to conversation history."""
        turn = {
            "role": role,
            "content": content,
            "actions": actions or [],
            "timestamp": datetime.now().isoformat()
        }
        self.turns.append(turn)
        # Trim if exceeds max turns
        while len(self.turns) > self.max_turns:
            self.turns.pop(0)

    def get_recent_context(self, n: int = 5) -> str:
        """Get recent conversation turns as context string."""
        recent = self.turns[-n:]
        context_parts = []
        for turn in recent:
            role_label = "User" if turn["role"] == "user" else "Assistant"
            context_parts.append(f"{role_label}: {turn['content']}")
            if turn["actions"]:
                for action in turn["actions"]:
                    context_parts.append(f"  -> Executed: {action.get('type', 'unknown')}")
        return "\n".join(context_parts)

    def set_variable(self, key: str, value: Any):
        """Store a context variable."""
        self.context_variables[key] = value

    def get_variable(self, key: str, default: Any = None) -> Any:
        """Retrieve a context variable."""
        return self.context_variables.get(key, default)

    def clear(self):
        """Clear conversation history."""
        self.turns.clear()
        self.context_variables.clear()


# Global conversation memory
conversation_memory = ConversationMemory()


# =============================================================================
# SESSION STATISTICS TRACKER
# =============================================================================

class SessionStats:
    """Tracks session statistics for summaries."""

    def __init__(self):
        self.files_created = 0
        self.files_modified = 0
        self.files_deleted = 0
        self.commands_run = 0
        self.tools_used = {}
        self.start_time = datetime.now()

    def record_action(self, action_type: str, tool_name: str = None):
        if action_type == "tool":
            if tool_name == "write_file":
                self.files_created += 1
            elif tool_name == "edit_file":
                self.files_modified += 1
            elif tool_name == "delete_file":
                self.files_deleted += 1
            else:
                self.tools_used[tool_name] = self.tools_used.get(tool_name, 0) + 1
        elif action_type == "command":
            self.commands_run += 1

    def get_summary(self) -> str:
        elapsed = datetime.now() - self.start_time
        lines = [
            f"\n{'='*50}",
            "SESSION SUMMARY",
            f"{'='*50}",
            f"Duration: {elapsed.seconds // 60}m {elapsed.seconds % 60}s",
            f"Files created: {self.files_created}",
            f"Files modified: {self.files_modified}",
            f"Files deleted: {self.files_deleted}",
            f"Commands run: {self.commands_run}",
        ]
        if self.tools_used:
            lines.append(f"Tools used: {', '.join(f'{k}({v})' for k, v in self.tools_used.items())}")
        lines.append(f"{'='*50}")
        return "\n".join(lines)


# Global session statistics
session_stats = SessionStats()


# =============================================================================
# UNDO HISTORY MANAGER
# =============================================================================

class UndoManager:
    """Manages undo history for file modifications."""

    def __init__(self, max_history: int = 50):
        self.max_history = max_history
        self.history: List[Dict] = []
        self._temp_dir = os.path.join(tempfile.gettempdir(), "agentic_undo")
        os.makedirs(self._temp_dir, exist_ok=True)

    def save_file_state(self, filepath: str) -> str:
        """Save file state and return backup path."""
        if not os.path.exists(filepath):
            return None

        backup_id = hashlib.md5(f"{filepath}{datetime.now().isoformat()}".encode()).hexdigest()[:12]
        backup_path = os.path.join(self._temp_dir, f"{backup_id}.bak")

        # Store original content and metadata
        with open(filepath, "rb") as f:
            content = f.read()

        with open(backup_path, "wb") as f:
            f.write(content)

        # Record in history
        self.history.append({
            "type": "file_modification",
            "filepath": os.path.abspath(filepath),
            "backup_path": backup_path,
            "timestamp": datetime.now().isoformat()
        })

        # Trim history if needed
        while len(self.history) > self.max_history:
            old_entry = self.history.pop(0)
            if os.path.exists(old_entry.get("backup_path", "")):
                os.remove(old_entry["backup_path"])

        return backup_path

    def undo_last(self) -> Tuple[bool, str]:
        """Undo the last file modification."""
        if not self.history:
            return False, "No actions to undo"

        last_entry = self.history.pop()
        if last_entry["type"] == "file_modification":
            filepath = last_entry["filepath"]
            backup_path = last_entry["backup_path"]

            if os.path.exists(backup_path):
                with open(backup_path, "rb") as f:
                    original_content = f.read()
                with open(filepath, "wb") as f:
                    f.write(original_content)
                os.remove(backup_path)
                return True, f"Restored: {filepath}"
            else:
                return False, "Backup file not found"

        return False, "Unknown action type"

    def clear(self):
        """Clear undo history and cleanup temp files."""
        for entry in self.history:
            backup_path = entry.get("backup_path")
            if backup_path and os.path.exists(backup_path):
                os.remove(backup_path)
        self.history.clear()


# Global undo manager
undo_manager = UndoManager()

# Cleanup temp files on exit
def cleanup_undo_files():
    if os.path.exists(undo_manager._temp_dir):
        shutil.rmtree(undo_manager._temp_dir, ignore_errors=True)

atexit.register(cleanup_undo_files)


# =============================================================================
# DRY-RUN MODE MANAGER
# =============================================================================

class DryRunManager:
    """Manages dry-run mode for previewing actions without executing."""

    def __init__(self):
        self.enabled = False
        self.planned_actions: List[Dict] = []

    def enable(self):
        self.enabled = True
        self.planned_actions = []
        print("\n[DRY-RUN MODE ENABLED] Actions will be previewed but not executed.")

    def disable(self):
        self.enabled = False
        print("\n[DRY-RUN MODE DISABLED] Actions will now be executed normally.")

    def record_action(self, action: Dict) -> str:
        """Record an action for dry-run preview and return description."""
        self.planned_actions.append(action)
        return format_action_description(action)

    def show_planned_actions(self):
        """Display all planned actions."""
        if not self.planned_actions:
            print("[No actions planned]")
            return

        print(f"\n[PLANNED ACTIONS - {len(self.planned_actions)} total]")
        for i, action in enumerate(self.planned_actions, 1):
            desc = format_action_description(action)
            print(f"  {i}. {desc}")

    def clear(self):
        self.planned_actions = []


# Global dry-run manager
dry_run_manager = DryRunManager()


# =============================================================================
# MULTI-FILE CONTEXT READER
# =============================================================================

class MultiFileContextReader:
    """Automatically reads related files for better context understanding."""

    # Keywords that trigger multi-file reading
    DOMAIN_PATTERNS = {
        'auth': ['auth', 'login', 'session', 'token', 'jwt', 'oauth', 'credential', 'password'],
        'database': ['db', 'database', 'model', 'schema', 'migration', 'query', 'sql'],
        'api': ['api', 'endpoint', 'route', 'handler', 'controller', 'view'],
        'config': ['config', 'setting', 'env', 'environment', 'constant'],
        'utils': ['util', 'helper', 'common', 'shared', 'lib'],
        'middleware': ['middleware', 'interceptor', 'filter', 'decorator'],
        'test': ['test', 'spec', 'fixture', 'mock'],
    }

    def __init__(self):
        self.max_files = 5
        self.max_content_per_file = 5000

    def find_related_files(self, prompt: str, base_filepath: str = None) -> List[str]:
        """Find files related to the prompt topic."""
        prompt_lower = prompt.lower()
        related_files = []

        # Determine the domain/topic from the prompt
        matched_domains = []
        for domain, keywords in self.DOMAIN_PATTERNS.items():
            if any(kw in prompt_lower for kw in keywords):
                matched_domains.append(domain)

        if not matched_domains and not base_filepath:
            return []

        # Get base directory
        base_dir = os.path.dirname(os.path.abspath(base_filepath)) if base_filepath else os.getcwd()

        # Walk the directory to find related files
        for root, dirs, files in os.walk(base_dir):
            # Skip hidden and common non-essential directories
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', 'venv', '__pycache__', 'dist', 'build']]

            for filename in files:
                if not any(filename.endswith(ext) for ext in ALLOWED_FILE_EXTENSIONS):
                    continue

                filepath = os.path.join(root, filename)
                score = 0

                # Score by domain match
                for domain in matched_domains:
                    if domain in filename.lower():
                        score += 10

                # Score by keyword match in filename
                for kw in prompt_lower.split():
                    if len(kw) > 3 and kw in filename.lower():
                        score += 5

                # Score by proximity to base file
                if base_filepath:
                    base_name = os.path.basename(base_filepath)
                    if filename != base_name:
                        # Same directory bonus
                        if os.path.dirname(filepath) == os.path.dirname(os.path.abspath(base_filepath)):
                            score += 3
                        # Import relationship check (read file to check imports)
                        try:
                            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                                content = f.read(2000)
                                base_name_no_ext = os.path.splitext(base_name)[0]
                                if base_name_no_ext in content:
                                    score += 15
                        except:
                            pass

                if score > 0:
                    related_files.append((filepath, score))

        # Sort by score and return top files
        related_files.sort(key=lambda x: x[1], reverse=True)
        return [f[0] for f in related_files[:self.max_files]]

    def read_context(self, prompt: str, base_filepath: str = None) -> str:
        """Read related files and return context string."""
        related = self.find_related_files(prompt, base_filepath)

        if not related:
            return ""

        context_parts = ["\n\n[RELATED FILES CONTEXT]"]

        for filepath in related:
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read(self.max_content_per_file)
                context_parts.append(f"\n--- File: {filepath} ---\n{content[:self.max_content_per_file]}")
            except Exception as e:
                context_parts.append(f"\n--- File: {filepath} ---\n[Could not read: {e}]")

        context_parts.append("[END RELATED FILES CONTEXT]\n")
        return "\n".join(context_parts)


# Global multi-file context reader
multi_file_reader = MultiFileContextReader()


# =============================================================================
# GIT INTEGRATION
# =============================================================================

class GitIntegration:
    """Git integration for auto-committing changes."""

    def __init__(self):
        self.modified_files: List[str] = []
        self.git_root = None
        self._detect_git_root()

    def _detect_git_root(self) -> Optional[str]:
        """Detect if we're in a git repository and return the root path."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                cwd=os.getcwd()
            )
            if result.returncode == 0:
                self.git_root = result.stdout.strip()
                return self.git_root
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        return None

    def is_git_repo(self) -> bool:
        """Check if current directory is in a git repository."""
        return self.git_root is not None

    def track_file_modification(self, filepath: str):
        """Track a file modification for potential commit."""
        if not self.is_git_repo():
            return

        abs_filepath = os.path.abspath(filepath)
        if abs_filepath not in self.modified_files:
            self.modified_files.append(abs_filepath)

    def get_status(self) -> Dict[str, List[str]]:
        """Get git status showing modified files."""
        if not self.is_git_repo():
            return {"staged": [], "unstaged": [], "untracked": []}

        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                cwd=self.git_root
            )
            if result.returncode == 0:
                staged = []
                unstaged = []
                untracked = []

                for line in result.stdout.splitlines():
                    if len(line) >= 3:
                        status = line[:2]
                        filepath = line[3:].strip()

                        if status.startswith("A") or status.startswith("M") and status[1] != ' ':
                            staged.append(filepath)
                        elif status.startswith("M") or status.startswith("D"):
                            unstaged.append(filepath)
                        elif status.startswith("?"):
                            untracked.append(filepath)

                return {"staged": staged, "unstaged": unstaged, "untracked": untracked}
        except:
            pass

        return {"staged": [], "unstaged": [], "untracked": []}

    def offer_commit(self) -> bool:
        """Offer to commit modified files. Returns True if user wants to commit."""
        if not self.is_git_repo() or not self.modified_files:
            return False

        print(f"\n[Git Integration] {len(self.modified_files)} file(s) modified in this session:")
        for f in self.modified_files[-10:]:  # Show last 10
            print(f"  - {os.path.relpath(f, self.git_root)}")

        print("\nCreate a git commit? (yes/no): ", end="")
        try:
            response = input().strip().lower()
            if response in ["yes", "y"]:
                return self._create_commit()
        except (EOFError, KeyboardInterrupt):
            pass

        return False

    def _create_commit(self) -> bool:
        """Create a git commit with modified files."""
        if not self.modified_files:
            print("[Git] No files to commit")
            return False

        try:
            # Stage modified files
            for filepath in self.modified_files:
                subprocess.run(
                    ["git", "add", filepath],
                    capture_output=True,
                    cwd=self.git_root
                )

            # Create commit message
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            commit_msg = f"[Agentic] Changes at {timestamp}\n\nModified files:\n" + \
                         "\n".join(f"- {os.path.relpath(f, self.git_root)}" for f in self.modified_files[-20:])

            result = subprocess.run(
                ["git", "commit", "-m", commit_msg],
                capture_output=True,
                text=True,
                cwd=self.git_root
            )

            if result.returncode == 0:
                print(f"[Git] Commit created: {commit_msg.split(chr(10))[0]}")
                self.modified_files = []
                return True
            else:
                print(f"[Git] Commit failed: {result.stderr}")
                return False

        except Exception as e:
            print(f"[Git] Error creating commit: {e}")
            return False

    def clear(self):
        """Clear tracked modifications."""
        self.modified_files = []


# Global git integration
git_integration = GitIntegration()


# =============================================================================
# OUTPUT MODE MANAGER (Feature 9: Voice/Text Output Toggle)
# =============================================================================

class OutputModeManager:
    """Manages output verbosity - minimal vs verbose mode."""

    def __init__(self):
        self.verbose = True  # Default to verbose mode

    def set_minimal(self):
        self.verbose = False
        print("\n[Output Mode] MINIMAL - Only showing results")

    def set_verbose(self):
        self.verbose = True
        print("\n[Output Mode] VERBOSE - Explaining each step")

    def toggle(self):
        self.verbose = not self.verbose
        mode = "VERBOSE" if self.verbose else "MINIMAL"
        print(f"\n[Output Mode] Switched to {mode}")
        return self.verbose

    def should_explain(self) -> bool:
        return self.verbose

    def format_output(self, verbose_text: str, minimal_text: str = None) -> str:
        """Return appropriate output based on mode."""
        if self.verbose or minimal_text is None:
            return verbose_text
        return minimal_text


# Global output mode manager
output_mode_manager = OutputModeManager()


# =============================================================================
# PROGRESS INDICATOR (Feature 7)
# =============================================================================

class ProgressIndicator:
    """Shows progress indicators for long operations."""

    SPINNERS = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']

    def __init__(self):
        self.current_operation = None
        self.step = 0
        self.total = 0

    def start_operation(self, description: str):
        """Mark the start of an operation."""
        self.current_operation = description
        if output_mode_manager.verbose:
            print(f"\n[Starting] {description}")

    def update(self, current: int, total: int, description: str):
        """Update progress: [Step X/Y] Description."""
        self.step = current
        self.total = total
        if output_mode_manager.verbose:
            print(f"\n[Step {current}/{total}] {description}")

    def complete(self, success: bool = True):
        """Mark operation as complete."""
        if output_mode_manager.verbose:
            status = "✓" if success else "✗"
            print(f"\n[{status}] {self.current_operation or 'Operation'} completed")
        self.current_operation = None

    def context(self, step_num: int, total_steps: int, description: str):
        """Context manager style progress."""
        if output_mode_manager.verbose:
            print(f"\n[Step {step_num}/{total_steps}] {description}")
        return self


# Global progress indicator
progress = ProgressIndicator()


# =============================================================================
# CODE EXECUTION SANDBOX (Feature 6)
# =============================================================================

class CodeSandbox:
    """Sandbox for safely executing Python/JS code."""

    def __init__(self):
        self.enabled = True
        self.timeout = 5  # seconds
        self.max_output_lines = 100

    def execute_python(self, code: str, allowed_imports: List[str] = None) -> Tuple[bool, str]:
        """Execute Python code in a restricted environment."""
        if allowed_imports is None:
            allowed_imports = ['math', 'json', 're', 'datetime', 'collections', 'itertools']

        # Security checks
        dangerous_patterns = [
            '__import__', 'eval(', 'exec(', 'compile(', 'open(',
            'os.', 'sys.', 'subprocess', 'importlib', 'builtins',
            'globals()', 'locals()', 'setattr', 'getattr', 'delattr'
        ]

        for pattern in dangerous_patterns:
            if pattern in code:
                return False, f"Security violation: '{pattern}' not allowed in sandbox"

        # Create restricted globals
        restricted_globals = {"__builtins__": {}}

        # Add allowed imports
        for mod_name in allowed_imports:
            try:
                mod = __import__(mod_name)
                restricted_globals[mod_name] = mod
            except ImportError:
                pass

        # Capture output
        import io
        from contextlib import redirect_stdout

        output_buffer = io.StringIO()

        try:
            with redirect_stdout(output_buffer):
                exec(code, restricted_globals, {})
            output = output_buffer.getvalue()
            return True, f"Output:\n{output[:1000]}"  # Limit output
        except Exception as e:
            return False, f"Error: {str(e)}"

    def execute_javascript(self, code: str) -> Tuple[bool, str]:
        """Execute JavaScript code using Node.js in sandbox mode."""
        # Check if node is available
        if not shutil.which('node'):
            return False, "Node.js not found. Cannot execute JavaScript."

        # Security checks
        dangerous_patterns = [
            'require(', 'process.', 'child_process', 'fs.', 'exec(',
            'eval(', 'Function(', 'vm.', 'net.', 'http.', 'https.'
        ]

        for pattern in dangerous_patterns:
            if pattern in code:
                return False, f"Security violation: '{pattern}' not allowed"

        # Create temp file
        temp_file = os.path.join(tempfile.gettempdir(), f"sandbox_{os.getpid()}.js")

        try:
            with open(temp_file, 'w') as f:
                f.write(code)

            # Run with timeout
            proc = subprocess.Popen(
                ['node', temp_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.timeout
            )
            out, err = proc.communicate()

            if proc.returncode == 0:
                return True, f"Output:\n{out[:1000]}"
            else:
                return False, f"Error:\n{err[:500]}"

        except subprocess.TimeoutExpired:
            proc.kill()
            return False, f"Timeout: Code execution exceeded {self.timeout}s"
        except Exception as e:
            return False, f"Error: {str(e)}"
        finally:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass

    def offer_run(self, code: str, language: str = "python") -> bool:
        """Offer to run code in sandbox. Returns True if user wants to run."""
        if not self.enabled:
            return False

        lang_name = "JavaScript" if language == "js" else "Python"
        print(f"\n[Sandbox] {lang_name} code detected.")
        print("Run in sandbox? (yes/no): ", end="")

        try:
            response = input().strip().lower()
            if response in ["yes", "y"]:
                if language == "js":
                    return self.execute_javascript(code)
                else:
                    return self.execute_python(code)
        except (EOFError, KeyboardInterrupt):
            pass

        return False


# Global code sandbox
code_sandbox = CodeSandbox()


# =============================================================================
# TOOL DEFINITIONS
# =============================================================================

class ToolResult:
    """Represents the result of a tool execution."""

    def __init__(self, success: bool, output: str = "", error: str = "", data: Any = None):
        self.success = success
        self.output = output
        self.error = error
        self.data = data

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "data": self.data
        }


class Tool:
    """Base class for all tools."""

    name: str = "base_tool"
    description: str = "Base tool"

    def __init__(self):
        pass

    def validate(self, **kwargs) -> Tuple[bool, str]:
        """Validate tool arguments. Returns (is_valid, error_message)."""
        return True, ""

    def execute(self, **kwargs) -> ToolResult:
        """Execute the tool. Override in subclasses."""
        raise NotImplementedError


def find_similar_file(filepath: str, max_distance: int = 3) -> str:
    """Find a file with a similar name if the exact path doesn't exist."""
    if os.path.exists(filepath):
        return filepath

    dirname = os.path.dirname(filepath) or "."
    basename = os.path.basename(filepath)

    if not os.path.isdir(dirname):
        return filepath

    def levenshtein_distance(s1, s2):
        if len(s1) < len(s2):
            return levenshtein_distance(s2, s1)
        if len(s2) == 0:
            return len(s1)

        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row

        return previous_row[-1]

    # Find files with similar names
    for filename in os.listdir(dirname):
        distance = levenshtein_distance(basename, filename)
        if distance <= max_distance:
            return os.path.join(dirname, filename)

    return filepath


class ReadFileTool(Tool):
    """Read contents of a file."""

    name = "read_file"
    description = "Read the contents of a file. Use this to understand file contents."

    def validate(self, filepath: str, **kwargs) -> Tuple[bool, str]:
        if not filepath:
            return False, "No filepath provided"

        # Try to find similar file if exact path doesn't exist
        corrected = find_similar_file(filepath)
        if corrected != filepath:
            return True, ""  # Will use corrected path

        if not os.path.exists(filepath):
            return False, f"File does not exist: {filepath}"
        return True, ""

    def execute(self, filepath: str, **kwargs) -> ToolResult:
        try:
            # Try to correct typos in filename
            actual_path = find_similar_file(filepath)
            if actual_path != filepath:
                print(f"[Note: Corrected '{filepath}' -> '{actual_path}']")

            with open(actual_path, "r", encoding="utf-8") as f:
                content = f.read()
            return ToolResult(
                success=True,
                output=f"File contents ({actual_path}):\n{content}",
                data={"filepath": actual_path, "content": content, "size": len(content)}
            )
        except FileNotFoundError:
            # Feature 4: Better error messages with suggestions
            dirname = os.path.dirname(filepath) or "."
            if os.path.isdir(dirname):
                try:
                    files_in_dir = os.listdir(dirname)
                    similar = find_similar_file(filepath)
                    suggestion = f" Did you mean '{similar}'?" if similar != filepath else ""
                    return ToolResult(
                        success=False,
                        error=f"File '{filepath}' not found.{suggestion}\nFiles in directory: {', '.join(sorted(files_in_dir)[:10])}"
                    )
                except:
                    pass
            return ToolResult(success=False, error=f"File '{filepath}' not found.")
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class WriteFileTool(Tool):
    """Create or overwrite a file."""

    name = "write_file"
    description = "Create a new file or overwrite an existing file with content."

    def validate(self, filepath: str, content: str, **kwargs) -> Tuple[bool, str]:
        if not filepath:
            return False, "No filepath provided"
        if not content:
            return False, "No content provided"
        if len(filepath) < 3:
            return False, "Filename too short"
        # Check for dangerous patterns
        if ".." in filepath or filepath.startswith("/"):
            return False, "Invalid filepath"
        return True, ""

    def execute(self, filepath: str, content: str, **kwargs) -> ToolResult:
        try:
            # Create parent directories if needed
            parent_dir = os.path.dirname(filepath)
            if parent_dir and not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)

            # Feature 2: Save undo state if file exists (modification)
            if os.path.exists(filepath):
                undo_manager.save_file_state(filepath)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)

            # Feature 8: Record session stats
            session_stats.record_action("tool", "write_file")

            # Git integration: track modification
            git_integration.track_file_modification(filepath)

            return ToolResult(
                success=True,
                output=f"File created: {filepath}",
                data={"filepath": filepath, "bytes_written": len(content)}
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class EditFileTool(Tool):
    """Edit specific lines in a file."""

    name = "edit_file"
    description = "Edit specific lines or make search-replace changes in a file."

    def validate(self, filepath: str, **kwargs) -> Tuple[bool, str]:
        if not filepath:
            return False, "No filepath provided"
        if not os.path.exists(filepath):
            return False, f"File does not exist: {filepath}"
        return True, ""

    def execute(self, filepath: str,
                search_text: str = None,
                replace_text: str = None,
                line_number: int = None,
                new_content: str = None,
                content: str = None,  # Alternative parameter name
                **kwargs) -> ToolResult:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                original_content = f.read()
                lines = original_content.splitlines()

            new_lines = lines.copy()

            # Handle content parameter (alternative name)
            if content is not None and new_content is None:
                new_content = content

            # Search-replace mode
            if search_text and replace_text is not None:
                new_content = original_content.replace(search_text, replace_text)
                if new_content == original_content:
                    return ToolResult(
                        success=False,
                        error="Search text not found in file"
                    )
            # Line replacement mode
            elif line_number is not None and new_content is not None:
                if line_number < 1 or line_number > len(lines):
                    return ToolResult(
                        success=False,
                        error=f"Line number {line_number} out of range (1-{len(lines)})"
                    )
                new_lines[line_number - 1] = new_content
                new_content = "\n".join(new_lines)
            # Full file overwrite mode (if only new_content provided)
            elif new_content is not None:
                pass  # Use new_content as-is
            else:
                return ToolResult(
                    success=False,
                    error="Must provide either (search_text, replace_text), (line_number, new_content), or just (new_content)"
                )

            # Feature 2: Save undo state before modification
            undo_manager.save_file_state(filepath)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_content)

            # Feature 8: Record session stats
            session_stats.record_action("tool", "edit_file")

            # Git integration: track modification
            git_integration.track_file_modification(filepath)

            return ToolResult(
                success=True,
                output=f"File edited: {filepath}",
                data={"filepath": filepath, "changes_made": True}
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class DeleteFileTool(Tool):
    """Delete a file."""

    name = "delete_file"
    description = "Delete a file. This is a destructive action."

    def validate(self, filepath: str, **kwargs) -> Tuple[bool, str]:
        if not filepath:
            return False, "No filepath provided"
        if not os.path.exists(filepath):
            return False, f"File does not exist: {filepath}"
        if os.path.isdir(filepath):
            return False, "Cannot delete directories with this tool"
        return True, ""

    def execute(self, filepath: str, **kwargs) -> ToolResult:
        try:
            os.remove(filepath)
            return ToolResult(
                success=True,
                output=f"File deleted: {filepath}"
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class RunCommandTool(Tool):
    """Execute a shell command."""

    name = "run_command"
    description = "Execute a shell command and return its output."

    def validate(self, command: str, **kwargs) -> Tuple[bool, str]:
        if not command:
            return False, "No command provided"
        # Check for destructive commands
        for destructive in DESTRUCTIVE_COMMANDS:
            if destructive in command.lower():
                return False, f"Potentially destructive command detected: {command}"
        return True, ""

    def execute(self, command: str, timeout: int = 30, **kwargs) -> ToolResult:
        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=os.getcwd()
            )
            out, err = proc.communicate(timeout=timeout)
            output = out + ("\n" + err if err else "")
            return ToolResult(
                success=proc.returncode == 0,
                output=output if output else "(no output)",
                data={"returncode": proc.returncode}
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            return ToolResult(success=False, error=f"Command timed out after {timeout}s")
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class SearchCodeTool(Tool):
    """Search for patterns in code files."""

    name = "search_code"
    description = "Search for text patterns in code files using grep-like functionality."

    def validate(self, pattern: str, **kwargs) -> Tuple[bool, str]:
        if not pattern:
            return False, "No search pattern provided"
        return True, ""

    def execute(self, pattern: str, file_pattern: str = None,
                path: str = None, **kwargs) -> ToolResult:
        try:
            search_path = path or os.getcwd()
            results = []

            for root, dirs, files in os.walk(search_path):
                # Skip hidden and common non-essential directories
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', 'venv', '__pycache__', 'dist', 'build']]

                for filename in files:
                    if file_pattern and not re.search(file_pattern, filename):
                        continue

                    filepath = os.path.join(root, filename)
                    try:
                        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                            if pattern in content:
                                # Find line numbers
                                for i, line in enumerate(content.splitlines(), 1):
                                    if pattern in line:
                                        results.append({
                                            "file": filepath,
                                            "line": i,
                                            "content": line.strip()[:200]
                                        })
                    except (PermissionError, IOError):
                        continue

            if not results:
                return ToolResult(
                    success=True,
                    output="No matches found"
                )

            output = f"Found {len(results)} matches:\n"
            for r in results[:50]:  # Limit output
                output += f"  {r['file']}:{r['line']} - {r['content']}\n"

            return ToolResult(
                success=True,
                output=output,
                data={"matches": results}
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class GitTool(Tool):
    """Execute git commands safely."""

    name = "git"
    description = "Execute git commands. Safe operations only (status, diff, log, show, add, commit)."

    SAFE_GIT_COMMANDS = ["status", "diff", "log", "show", "add", "commit", "branch", "checkout", "restore"]
    DANGEROUS_GIT_COMMANDS = ["reset --hard", "clean -fd", "push --force", "rebase -i"]

    def validate(self, command: str, **kwargs) -> Tuple[bool, str]:
        if not command:
            return False, "No git command provided"

        # Check for dangerous git commands
        for dangerous in self.DANGEROUS_GIT_COMMANDS:
            if dangerous in command:
                return False, f"Dangerous git command detected: {dangerous}"

        return True, ""

    def execute(self, command: str, **kwargs) -> ToolResult:
        try:
            full_command = f"git {command}"
            proc = subprocess.Popen(
                full_command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=os.getcwd()
            )
            out, err = proc.communicate()
            output = out + ("\n" + err if err else "")
            return ToolResult(
                success=proc.returncode == 0,
                output=output if output else "(no output)",
                data={"returncode": proc.returncode}
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class ListDirectoryTool(Tool):
    """List contents of a directory."""

    name = "list_directory"
    description = "List files and directories in a given path."

    def validate(self, path: str = None, **kwargs) -> Tuple[bool, str]:
        check_path = path or os.getcwd()
        if not os.path.exists(check_path):
            return False, f"Path does not exist: {check_path}"
        if not os.path.isdir(check_path):
            return False, f"Path is not a directory: {check_path}"
        return True, ""

    def execute(self, path: str = None, **kwargs) -> ToolResult:
        try:
            check_path = path or os.getcwd()
            entries = os.listdir(check_path)

            result = []
            for entry in sorted(entries):
                full_path = os.path.join(check_path, entry)
                is_dir = os.path.isdir(full_path)
                result.append({
                    "name": entry,
                    "type": "directory" if is_dir else "file",
                    "path": full_path
                })

            output = f"Contents of {check_path}:\n"
            for r in result:
                marker = "[DIR]" if r["type"] == "directory" else "[FILE]"
                output += f"  {marker} {r['name']}\n"

            return ToolResult(
                success=True,
                output=output,
                data={"entries": result}
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


# Registry of all available tools
TOOL_REGISTRY: Dict[str, Tool] = {
    "read_file": ReadFileTool(),
    "write_file": WriteFileTool(),
    "edit_file": EditFileTool(),
    "delete_file": DeleteFileTool(),
    "run_command": RunCommandTool(),
    "search_code": SearchCodeTool(),
    "git": GitTool(),
    "list_directory": ListDirectoryTool()
}


def get_tool_schema(tool_name: str) -> Dict:
    """Get the schema for a tool (for LLM prompting)."""
    tool = TOOL_REGISTRY.get(tool_name)
    if not tool:
        return {}

    # Get the execute method signature
    import inspect
    sig = inspect.signature(tool.execute)
    params = []
    for name, param in sig.parameters.items():
        if name in ["self", "kwargs"]:
            continue
        params.append({
            "name": name,
            "type": param.annotation.__name__ if param.annotation != inspect.Parameter.empty else "any",
            "required": param.default == inspect.Parameter.empty,
            "default": param.default if param.default != inspect.Parameter.empty else None
        })

    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": params
    }


def get_all_tool_schemas() -> List[Dict]:
    """Get schemas for all tools."""
    return [get_tool_schema(name) for name in TOOL_REGISTRY.keys()]


# =============================================================================
# PLANNING SYSTEM
# =============================================================================

class Plan:
    """Represents a multi-step plan."""

    def __init__(self, goal: str, steps: List[Dict[str, Any]] = None):
        self.goal = goal
        self.steps = steps or []
        self.current_step = 0
        self.results: List[Dict] = []
        self.status = "pending"  # pending, in_progress, completed, failed

    def add_step(self, tool_name: str, **kwargs):
        """Add a step to the plan."""
        self.steps.append({
            "tool": tool_name,
            "parameters": kwargs,
            "status": "pending",
            "result": None
        })

    def get_current_step(self) -> Dict:
        """Get the current step."""
        if self.current_step < len(self.steps):
            return self.steps[self.current_step]
        return None

    def mark_step_complete(self, result: Dict):
        """Mark current step as complete."""
        if self.current_step < len(self.steps):
            self.steps[self.current_step]["status"] = "completed"
            self.steps[self.current_step]["result"] = result
            self.results.append(result)
            self.current_step += 1

    def mark_step_failed(self, error: str):
        """Mark current step as failed."""
        if self.current_step < len(self.steps):
            self.steps[self.current_step]["status"] = "failed"
            self.steps[self.current_step]["error"] = error

    def is_complete(self) -> bool:
        """Check if all steps are complete."""
        return self.current_step >= len(self.steps)

    def to_dict(self) -> Dict:
        return {
            "goal": self.goal,
            "steps": self.steps,
            "current_step": self.current_step,
            "status": self.status,
            "results": self.results
        }


def parse_plan_from_response(llm_response: str) -> Optional[Plan]:
    """Parse a plan from LLM response."""
    # Look for [PLAN]...[/PLAN] tags
    plan_match = re.search(r"\[PLAN\](.*?)\[/PLAN\]", llm_response, re.DOTALL)
    if not plan_match:
        return None

    plan_text = plan_match.group(1).strip()

    # Try to parse as JSON
    try:
        plan_data = json.loads(plan_text)
        plan = Plan(goal=plan_data.get("goal", "Unknown goal"))
        for step in plan_data.get("steps", []):
            plan.add_step(step["tool"], **step.get("parameters", {}))
        return plan
    except json.JSONDecodeError:
        pass

    # Fallback: parse structured text format
    lines = plan_text.strip().split("\n")
    plan = Plan(goal="Multi-step task")

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Parse "1. tool_name: param=value" format
        match = re.match(r"(\d+)?\.?\s*(\w+):\s*(.*)", line)
        if match:
            tool_name = match.group(2)
            params_str = match.group(3)

            # Parse parameters
            params = {}
            for param_match in re.finditer(r"(\w+)=([^,]+)", params_str):
                key = param_match.group(1)
                value = param_match.group(2).strip().strip('"\'')
                params[key] = value

            if tool_name in TOOL_REGISTRY:
                plan.add_step(tool_name, **params)

    return plan if plan.steps else None


def parse_action_from_response(response: str) -> Optional[Dict[str, Any]]:
    """Parse a single action from LLM response."""

    # Check for [RUN]...[/RUN] tags
    match = re.search(r"\[RUN\](.*?)\[/RUN\]", response, re.DOTALL)
    if match:
        return {"type": "command", "value": match.group(1).strip()}

    # Check for [TOOL name]...[/TOOL] tags
    tool_match = re.search(r"\[TOOL\s+(\w+)\](.*?)\[/TOOL\]", response, re.DOTALL)
    if tool_match:
        tool_name = tool_match.group(1)
        params_text = tool_match.group(2).strip()

        # Try to parse parameters as JSON
        try:
            params = json.loads(params_text)
            return {"type": "tool", "tool": tool_name, "parameters": params}
        except json.JSONDecodeError:
            # Fallback: parse key=value pairs
            params = {}
            for line in params_text.split("\n"):
                if "=" in line:
                    key, value = line.split("=", 1)
                    params[key.strip()] = value.strip()
            return {"type": "tool", "tool": tool_name, "parameters": params}

    # Check for [FILE filename]...[/FILE] tags
    file_tag_match = re.search(r"\[FILE ([^\]]+)\](.*?)\[/FILE\]", response, re.DOTALL)
    if file_tag_match:
        filename = file_tag_match.group(1).strip()
        content = file_tag_match.group(2).lstrip('\n')
        return {"type": "tool", "tool": "write_file", "parameters": {"filepath": filename, "content": content}}

    # Check for file creation pattern: "create file xyz" and code block
    file_match = re.search(r"(?:create|write|make)[^\n]*file[^\n]*([\w\-.]+)[^\n]*\n+```(\w+)?\n(.*?)\n```", response, re.DOTALL | re.IGNORECASE)
    if file_match:
        filename = file_match.group(1).strip()
        content = file_match.group(3)
        return {"type": "tool", "tool": "write_file", "parameters": {"filepath": filename, "content": content}}

    # Check for code block with filename mention
    lines = response.splitlines()
    for i, line in enumerate(lines):
        if 'file' in line.lower() and i+1 < len(lines) and lines[i+1].startswith('```'):
            filename_match = re.findall(r'([\w\-.]+\.\w+)', line)
            if filename_match:
                code_lines = []
                for j in range(i+2, len(lines)):
                    if lines[j].startswith('```'):
                        break
                    code_lines.append(lines[j])
                return {
                    "type": "tool",
                    "tool": "write_file",
                    "parameters": {
                        "filepath": filename_match[-1],
                        "content": '\n'.join(code_lines)
                    }
                }

    return None


# =============================================================================
# SAFETY LAYER
# =============================================================================

def is_destructive_action(action: Dict) -> bool:
    """Check if an action is potentially destructive."""
    if action.get("type") == "command":
        cmd = action.get("value", "").lower()
        return any(d in cmd for d in DESTRUCTIVE_COMMANDS)

    if action.get("type") == "tool":
        if action.get("tool") == "delete_file":
            return True
        if action.get("tool") == "run_command":
            cmd = action.get("parameters", {}).get("command", "").lower()
            return any(d in cmd for d in DESTRUCTIVE_COMMANDS)

    return False


def require_confirmation(action: Dict) -> bool:
    """Check if an action requires user confirmation."""
    return is_destructive_action(action)


def confirm_action(action: Dict) -> bool:
    """Ask user for confirmation on destructive actions."""
    if not require_confirmation(action):
        return True

    action_desc = format_action_description(action)
    print(f"\n⚠️  DESTRUCTIVE ACTION DETECTED:")
    print(f"   {action_desc}")
    print(f"\n   Do you want to proceed? (yes/no): ", end="")

    try:
        response = input().strip().lower()
        return response in ["yes", "y"]
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return False


def format_action_description(action: Dict) -> str:
    """Format an action as a human-readable description."""
    if action.get("type") == "command":
        return f"Run command: {action.get('value')}"
    if action.get("type") == "tool":
        tool = action.get("tool")
        params = action.get("parameters", {})
        if tool == "write_file":
            return f"Create/overwrite file: {params.get('filepath')}"
        if tool == "delete_file":
            return f"Delete file: {params.get('filepath')}"
        if tool == "edit_file":
            return f"Edit file: {params.get('filepath')}"
        if tool == "run_command":
            return f"Run command: {params.get('command')}"
        return f"Execute tool: {tool}({params})"
    return str(action)


# =============================================================================
# LLM INTERACTION
# =============================================================================

def build_system_prompt() -> str:
    """Build the system prompt with tool descriptions."""
    tool_schemas = get_all_tool_schemas()

    tools_text = "\n".join([
        f"- {t['name']}: {t['description']}\n  Parameters: {t['parameters']}"
        for t in tool_schemas
    ])

    return f"""You are an AI coding assistant with the ability to execute actions on the user's system.
You have access to the following tools:

{tools_text}

CRITICAL RULES:
1. You are an ACTION-TAKING agent. Do NOT ask questions or seek clarification.
2. Before EDITING any file, FIRST read it using [TOOL read_file] to understand current content
3. For FILE EDITING, use [TOOL edit_file] with the COMPLETE new content (not just the addition)
4. For FILE CREATION, use [TOOL write_file] with full content
5. Only use [RUN] for actual shell commands (ls, git, pip, etc.) - NEVER for file editing

WORKFLOW FOR EDITING FILES:
Step 1: Read the file first: [TOOL read_file]{{"filepath": "example.js"}}[/TOOL]
Step 2: Then edit with complete content: [TOOL edit_file]{{"filepath": "example.js", "new_content": "FULL new content here"}}[/TOOL]

Output format for tool calls:
[TOOL tool_name]
{{"param1": "value1", "param2": "value2"}}
[/TOOL]

For file editing (provide complete new content):
[TOOL edit_file]
{{"filepath": "example.js", "new_content": "full new file content here"}}
[/TOOL]

For file creation:
[TOOL write_file]
{{"filepath": "example.js", "content": "full file content here"}}
[/TOOL]

For simple commands:
[RUN]ls -la[/RUN]

For multi-step tasks:
[PLAN]
{{
  "goal": "description of the goal",
  "steps": [
    {{"tool": "tool_name", "parameters": {{"param": "value"}}}},
    {{"tool": "another_tool", "parameters": {{"param": "value"}}}}
  ]
}}
[/PLAN]

IMPORTANT RULES:
1. NEVER ask questions - just TAKE ACTION
2. ALWAYS copy filenames EXACTLY as given - never change, abbreviate, or typo them
3. If the user says "this file" or "the file", use the filename from context
4. When editing, ALWAYS read the file first, then provide COMPLETE new content (not just additions)
5. Be concise in explanations - focus on executing actions

Example interaction:
User: "edit response.js to add array writing code"
Assistant: First, let me read the current content of response.js.
[TOOL read_file]
{{"filepath": "response.js"}}
[/TOOL]
Now I'll update it with the complete new content.
[TOOL edit_file]
{{"filepath": "response.js", "new_content": "const fs = require('fs');\\nconst arr = [1,2,3];\\nfs.writeFileSync('out.json', JSON.stringify(arr));"}}
[/TOOL]

Always execute tools immediately without asking for confirmation or clarification."""


def run_ollama_chat(messages: List[Dict], stream: bool = False) -> str:
    """Run Ollama chat API and return output."""
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": stream,
        "options": {
            "num_predict": 4096,  # Increase max tokens
            "temperature": 0.7,
        }
    }

    if HAS_REQUESTS:
        resp = requests.post(CHAT_API_URL, json=payload, stream=stream)
        resp.raise_for_status()
        output = ""
        if stream:
            for line in resp.iter_lines():
                if line:
                    data = json.loads(line)
                    chunk = data.get("message", {}).get("content", "")
                    print(chunk, end="", flush=True)
                    output += chunk
        else:
            for line in resp.iter_lines():
                if line:
                    data = json.loads(line)
                    output += data.get("message", {}).get("content", "")
        return output
    else:
        # Fallback to urllib - use streaming for complete response
        payload["stream"] = True
        req = urllib.request.Request(
            CHAT_API_URL,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}
        )
        output = ""
        with urllib.request.urlopen(req) as resp:
            for line in resp:
                if line:
                    data = json.loads(line.decode())
                    chunk = data.get("message", {}).get("content", "")
                    if stream:
                        print(chunk, end="", flush=True)
                    output += chunk
        return output


def run_ollama_generate(prompt: str, stream: bool = True) -> str:
    """Run Ollama generate API and return output. Streaming enabled by default."""
    full_prompt = build_system_prompt() + "\n\nUser: " + prompt + "\nAssistant:"
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": full_prompt,
        "stream": True,  # Always stream for complete responses
        "options": {
            "num_predict": 8192,  # Max tokens for long responses
            "temperature": 0.7,
        }
    }

    output = ""
    if HAS_REQUESTS:
        resp = requests.post(OLLAMA_API_URL, json=payload, stream=True)
        resp.raise_for_status()
        for line in resp.iter_lines():
            if line:
                data = json.loads(line)
                chunk = data.get("response", "")
                if stream:
                    print(chunk, end="", flush=True)
                output += chunk
    else:
        req = urllib.request.Request(
            OLLAMA_API_URL,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            for line in resp:
                if line:
                    data = json.loads(line.decode())
                    chunk = data.get("response", "")
                    if stream:
                        print(chunk, end="", flush=True)
                    output += chunk
    return output


def run_ollama_cli(prompt: str, stream: bool = False) -> str:
    """Run Ollama model via CLI - falls back to API for better reliability."""
    # CLI mode has issues with streaming and token limits
    # Fall back to API which handles responses more reliably
    try:
        return run_ollama_generate(prompt, stream=stream)
    except Exception as e:
        # True fallback to subprocess if API fails
        full_prompt = build_system_prompt() + "\n\nUser: " + prompt + "\nAssistant:"
        proc = subprocess.Popen(
            ["ollama", "run", OLLAMA_MODEL],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        out, err = proc.communicate(full_prompt)
        if proc.returncode != 0:
            raise RuntimeError(f"Ollama CLI error: {err}")
        return out


# =============================================================================
# INTENT DETECTION
# =============================================================================

def detect_intent_and_prepare_prompt(user_prompt: str, vscode_current_file: str = None) -> Tuple[str, str]:
    """
    Detects if the user wants to understand/explain a file and prepares the LLM prompt and filename.
    Returns (llm_prompt, filename or None).
    """
    # Patterns for intent detection
    understand_patterns = [
        r"understand (this|the|current)? ?file",
        r"explain (this|the|current)? ?file",
        r"summarize (this|the|current)? ?file",
        r"what does (this|the|current)? ?file do",
        r"explain ([\w\-.]+)",
        r"understand ([\w\-.]+)",
        r"summarize ([\w\-.]+)",
        r"what does ([\w\-.]+) do"
    ]

    for pat in understand_patterns:
        m = re.search(pat, user_prompt, re.IGNORECASE)
        if m:
            # If a filename is captured, use it
            if m.lastindex and m.group(m.lastindex) and m.group(m.lastindex) not in ["this", "the", "current"]:
                filename = m.group(m.lastindex)
            else:
                filename = vscode_current_file

            if not filename:
                filename = input("Which file do you want to understand? ")

            try:
                with open(filename, "r", encoding="utf-8") as f:
                    file_content = f.read()
            except Exception as e:
                return (f"Could not read file '{filename}': {e}", None)

            llm_prompt = f"Explain the following code file ({filename}):\n\n{file_content}"
            return (llm_prompt, filename)

    # Default: no special intent detected
    return (None, None)


# =============================================================================
# CORE BRIDGE LOGIC
# =============================================================================

def auto_correct_parameters(tool_name: str, params: Dict, error: str) -> Tuple[bool, Dict]:
    """
    Attempt to auto-correct parameters when a tool fails.
    Returns (success, corrected_params).
    """
    corrected = params.copy()

    # File not found errors - try to find similar file
    if "not found" in error.lower() or "does not exist" in error.lower():
        filepath = params.get("filepath")
        if filepath:
            # Try finding similar file
            similar = find_similar_file(filepath)
            if similar and similar != filepath and os.path.exists(similar):
                print(f"[Auto-correct] File '{filepath}' -> '{similar}'")
                corrected["filepath"] = similar
                return True, corrected

            # Suggest files in directory
            dirname = os.path.dirname(filepath) or "."
            if os.path.isdir(dirname):
                try:
                    files = [f for f in os.listdir(dirname) if os.path.isfile(os.path.join(dirname, f))]
                    if files:
                        print(f"[Hint] Files in {dirname}: {', '.join(files[:10])}")
                except:
                    pass

    return False, corrected


def execute_action(action: Dict, auto_retry: bool = True, max_retries: int = 2) -> ToolResult:
    """Execute a parsed action and return the result. Includes auto-retry with corrected parameters."""
    action_type = action.get("type")
    retries = 0

    while retries <= max_retries:
        if action_type == "command":
            tool = TOOL_REGISTRY["run_command"]
            result = tool.execute(command=action.get("value", ""))

        elif action_type == "tool":
            tool_name = action.get("tool")
            params = action.get("parameters", {})

            if tool_name not in TOOL_REGISTRY:
                return ToolResult(success=False, error=f"Unknown tool: {tool_name}")

            tool = TOOL_REGISTRY[tool_name]

            # Validate before executing
            is_valid, error_msg = tool.validate(**params)
            if not is_valid:
                # Try auto-correction for validation errors
                if auto_retry and retries < max_retries:
                    corrected_success, corrected_params = auto_correct_parameters(tool_name, params, error_msg)
                    if corrected_success:
                        params = corrected_params
                        retries += 1
                        continue
                return ToolResult(success=False, error=error_msg)

            result = tool.execute(**params)

            # Auto-retry on failure
            if not result.success and auto_retry and retries < max_retries:
                corrected_success, corrected_params = auto_correct_parameters(tool_name, params, result.error)
                if corrected_success:
                    print(f"[Retry {retries + 1}/{max_retries}] Retrying with corrected parameters...")
                    action["parameters"] = corrected_params
                    params = corrected_params
                    retries += 1
                    continue

            return result

        else:
            return ToolResult(success=False, error=f"Unknown action type: {action_type}")

        # If we got here with a command, return the result
        if action_type == "command":
            return result

    return ToolResult(success=False, error="Max retries exceeded")


def execute_plan(plan: Plan) -> List[Dict]:
    """Execute a multi-step plan."""
    results = []

    while not plan.is_complete():
        step = plan.get_current_step()
        if not step:
            break

        # Feature 7: Progress indicators with verbose mode check
        if output_mode_manager.verbose:
            print(f"\n[Step {plan.current_step + 1}/{len(plan.steps)}] Executing: {step['tool']}")

        action = {
            "type": "tool",
            "tool": step["tool"],
            "parameters": step["parameters"]
        }

        # Check for confirmation
        if require_confirmation(action) and not confirm_action(action):
            plan.mark_step_failed("User cancelled")
            results.append({"step": step, "status": "cancelled", "error": "User cancelled"})
            break

        result = execute_action(action)
        plan.mark_step_complete(result.to_dict())
        results.append({
            "step": step,
            "status": "completed" if result.success else "failed",
            "result": result.to_dict()
        })

        if not result.success:
            if output_mode_manager.verbose:
                print(f"Step failed: {result.error}")
            # Ask user if they want to continue
            print("Continue with remaining steps? (yes/no): ", end="")
            try:
                response = input().strip().lower()
                if response not in ["yes", "y"]:
                    break
            except (EOFError, KeyboardInterrupt):
                break

    return results


def auto_read_file_before_edit(prompt: str) -> Optional[str]:
    """Detect if prompt involves editing a file, and auto-read it first."""
    edit_keywords = ['edit', 'update', 'modify', 'change', 'add to', 'append to',
                     'insert in', 'replace in', 'fix', 'improve', 'refactor']
    file_keywords = ['file', 'code', 'script', '.py', '.js', '.ts', '.json', '.md']

    prompt_lower = prompt.lower()

    # Check if this is an edit request
    is_edit = any(kw in prompt_lower for kw in edit_keywords)
    has_file_ref = any(kw in prompt_lower for kw in file_keywords) or \
                   re.search(r'\.[\w]+', prompt_lower) or \
                   re.search(r'[a-zA-Z_][\w\-\.]*\.[a-z]{2,4}', prompt)

    if is_edit and has_file_ref:
        # Try to extract filename
        filename_match = re.search(r'([a-zA-Z_][\w\-\.]*\.[a-z]{2,4})', prompt)
        if filename_match:
            filepath = filename_match.group(1)
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                    return f"\n\n[CONTEXT: Current content of {filepath}]\n{content}\n[/CONTEXT]"
                except:
                    pass
    return None


def prompt_and_act(prompt: str, use_api: bool = False) -> dict:
    """Main entry point: process a user prompt and execute actions."""
    global conversation_memory

    stream = os.environ.get("AGENTIC_STREAM", "0") == "1"
    vscode_current_file = os.environ.get("VSCODE_CURRENT_FILE")

    # Check for dry-run mode toggle
    if prompt.startswith("/dry-run"):
        dry_run_manager.enable()
        prompt = prompt[len("/dry-run"):].strip()
        if not prompt:
            return {"response": "Dry-run mode enabled. Send your next command to see what would happen.", "action": None, "action_type": None, "result": None}
    elif prompt == "/dry-run-off":
        dry_run_manager.disable()
        return {"response": "Dry-run mode disabled.", "action": None, "action_type": None, "result": None}
    elif prompt == "/dry-run-show":
        dry_run_manager.show_planned_actions()
        return {"response": "Shown planned actions.", "action": None, "action_type": None, "result": None}

    # Check for undo command
    if prompt == "/undo":
        success, msg = undo_manager.undo_last()
        print(f"\n[Undo] {msg}")
        return {"response": msg, "action": None, "action_type": "undo", "result": {"success": success}}

    # Check for git commit command
    if prompt == "/git-commit":
        git_integration.offer_commit()
        return {"response": "Git commit handled.", "action": None, "action_type": "git", "result": None}

    # Check for code execution request
    if prompt.startswith("/run-python") or prompt.startswith("/run-js"):
        language = "python" if "python" in prompt else "js"
        code = prompt.split("\n", 1)[1] if "\n" in prompt else ""
        if not code:
            # Look for code block in last assistant response
            last_turn = conversation_memory.turns[-1] if conversation_memory.turns else None
            if last_turn:
                code_match = re.search(r"```(?:python|js|javascript)?\n(.*?)\n```", last_turn.get("content", ""), re.DOTALL)
                if code_match:
                    code = code_match.group(1)

        if code:
            if language == "python":
                success, output = code_sandbox.execute_python(code)
            else:
                success, output = code_sandbox.execute_javascript(code)
            return {"response": output, "action": None, "action_type": f"run_{language}", "result": {"success": success}}
        else:
            return {"response": "No code found to execute. Provide code after the command or ensure the last response contains a code block.", "action": None, "action_type": None, "result": None}

    # Add conversation context to prompt
    recent_context = conversation_memory.get_recent_context(3)

    # Auto-read file if this is an edit request
    file_context = auto_read_file_before_edit(prompt)

    # Feature 5: Multi-file context for explain/understand requests
    multi_file_context = ""
    explain_intent = any(kw in prompt.lower() for kw in ['explain', 'understand', 'how does', 'how it', 'authentication', 'api', 'flow'])
    if explain_intent and vscode_current_file:
        multi_file_context = multi_file_reader.read_context(prompt, vscode_current_file)

    # Build full prompt with all context
    context_parts = []
    if recent_context:
        context_parts.append(f"Recent conversation:\n{recent_context}")
    if file_context:
        context_parts.append(file_context)
    if multi_file_context:
        context_parts.append(multi_file_context)

    if context_parts:
        full_prompt = "\n\n".join(context_parts) + f"\n\nUser: {prompt}"
    else:
        full_prompt = prompt

    # Check for file understanding intent
    llm_prompt, detected_filename = detect_intent_and_prepare_prompt(prompt, vscode_current_file)

    if llm_prompt:
        # File understanding - just get explanation
        if use_api:
            response = run_ollama_chat([{"role": "user", "content": llm_prompt}], stream=stream)
        else:
            response = run_ollama_cli(llm_prompt, stream=stream)
        action = None
        action_type = None
        result = response
    else:
        # General agentic mode - include file context in the prompt
        if use_api:
            response = run_ollama_chat([{"role": "user", "content": full_prompt}], stream=stream)
        else:
            response = run_ollama_cli(full_prompt, stream=stream)

        # Parse response for actions
        action = parse_action_from_response(response)
        plan = parse_plan_from_response(response)

        action_type = None
        result = None

        if plan and plan.steps:
            # Execute multi-step plan
            print(f"\n[Executing plan: {plan.goal}]")
            plan_results = execute_plan(plan)
            result = {
                "plan_executed": True,
                "goal": plan.goal,
                "steps": plan_results,
                "summary": f"Completed {len([r for r in plan_results if r['status'] == 'completed'])} of {len(plan_results)} steps"
            }
            action_type = "plan"
            action = plan.to_dict()
        elif action:
            # Feature 3: Dry-run mode - preview actions without executing
            if dry_run_manager.enabled:
                action_desc = dry_run_manager.record_action(action)
                print(f"\n[DRY-RUN] Would execute: {action_desc}")
                result = {"dry_run": True, "action_preview": action_desc}
                action_type = "dry_run"
            elif require_confirmation(action) and not confirm_action(action):
                result = "Action cancelled by user"
                action_type = None
            else:
                tool_result = execute_action(action)
                result = tool_result.to_dict()
                action_type = action.get("type")

                # AUTO-CONTINUE: If user asked to edit but LLM only read the file,
                # automatically generate the edit based on the user's request
                if action.get("type") == "tool" and action.get("tool") == "read_file":
                    edit_intent = any(kw in prompt.lower() for kw in
                                      ['edit', 'update', 'modify', 'change', 'add', 'insert',
                                       'replace', 'fix', 'improve', 'refactor', 'include'])
                    if edit_intent:
                        # Extract filename from the read action
                        filepath = action.get("parameters", {}).get("filepath", "")
                        if filepath and os.path.exists(filepath):
                            # Read the file content
                            with open(filepath, 'r', encoding='utf-8') as f:
                                current_content = f.read()

                            # Ask LLM to generate the edit based on user's request
                            print(f"\n[Auto-completing edit for {filepath}...]")
                            edit_prompt = f"""Based on the user's request: "{prompt}"
Current file content:
{current_content}

Provide the COMPLETE new content for {filepath} that incorporates the user's request.
Output ONLY the new content, no explanations.
Format your response as:
[TOOL edit_file]
{{"filepath": "{filepath}", "new_content": "YOUR COMPLETE NEW CONTENT HERE"}}
[/TOOL]"""
                            if use_api:
                                edit_response = run_ollama_chat([{"role": "user", "content": edit_prompt}], stream=False)
                            else:
                                edit_response = run_ollama_cli(edit_prompt, stream=False)

                            # Parse and execute the edit
                            edit_action = parse_action_from_response(edit_response)
                            if edit_action and edit_action.get("type") == "tool":
                                print(f"[Executing edit on {filepath}]")
                                edit_result = execute_action(edit_action)
                                result = {
                                    "read_then_edit": True,
                                    "read_result": tool_result.to_dict(),
                                    "edit_result": edit_result.to_dict()
                                }
                                action = edit_action
                                action_type = "edit_file"

                # Handle file creation from prompt/code block fallback
                if not action:
                    file_prompt_match = re.search(r"(?:create|write|make)[^\n]*file[^\n]*([\w\-.]+)", prompt, re.IGNORECASE)
                    code_block_match = re.search(r"```(\w+)?\n(.*?)\n```", response, re.DOTALL)
                    if file_prompt_match and code_block_match:
                        filename = file_prompt_match.group(1).strip()
                        content = code_block_match.group(2)
                        if filename and len(filename) > 2:
                            try:
                                with open(filename, "w", encoding="utf-8") as f:
                                    f.write(content)
                                result = {"success": True, "output": f"File '{filename}' created"}
                                action_type = "file"
                                action = {"type": "tool", "tool": "write_file", "parameters": {"filepath": filename, "content": content}}
                            except Exception as e:
                                result = {"success": False, "error": str(e)}

    # Store in conversation memory
    conversation_memory.add_turn("user", prompt)
    conversation_memory.add_turn("assistant", response, [action] if action else [])

    return {
        "response": response,
        "action": action,
        "action_type": action_type,
        "result": result
    }


def clean_llm_output(text: str) -> str:
    """Remove ANSI escape sequences and fix line breaks for human-friendly display."""
    text = re.sub(r'\u001b\[[0-9;]*[A-Za-z]', '', text)
    text = text.replace('\\n', '\n')
    return text


# =============================================================================
# HTTP SERVER INTERFACE
# =============================================================================

class AgenticHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        data = json.loads(post_data)
        prompt = data.get("prompt", "")
        use_api = data.get("use_api", False)
        result = prompt_and_act(prompt, use_api)

        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())

    def do_GET(self):
        """Health check endpoint."""
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok", "model": OLLAMA_MODEL}).encode())


def start_http_server(port=8080):
    server = HTTPServer(('localhost', port), AgenticHandler)
    print(f"Agentic bridge HTTP server running on http://localhost:{port}")
    print("Endpoints:")
    print("  POST / - Send a prompt to execute")
    print("  GET /  - Health check")
    server.serve_forever()


# =============================================================================
# MAIN ENTRY
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Agentic Ollama Bridge - Local AI Agent")
    parser.add_argument('--prompt', type=str, help='Prompt to send to Ollama')
    parser.add_argument('--api', action='store_true', help='Use Ollama API instead of CLI')
    parser.add_argument('--http', action='store_true', help='Run as HTTP server')
    parser.add_argument('--port', type=int, default=8080, help='HTTP server port')
    parser.add_argument('--repl', action='store_true', help='Run in interactive REPL mode')
    parser.add_argument('--debug', action='store_true', help='Run with pdb debugger')
    parser.add_argument('--no-confirm', action='store_true', help='Skip confirmation for destructive actions')
    args = parser.parse_args()

    # Override confirmation behavior if requested
    if args.no_confirm:
        confirm_action = lambda action: True

    if args.debug:
        import pdb; pdb.set_trace()

    if args.http:
        start_http_server(args.port)

    elif args.repl:
        print("=" * 60)
        print("Agentic Bridge Interactive Mode")
        print("=" * 60)
        print(f"Model: {OLLAMA_MODEL}")
        print("Commands:")
        print("  /clear        - Clear conversation memory")
        print("  /tools        - List available tools")
        print("  /undo         - Undo last file modification")
        print("  /dry-run      - Enable dry-run mode (preview actions)")
        print("  /dry-run-off  - Disable dry-run mode")
        print("  /dry-run-show - Show planned actions")
        print("  /git-commit   - Create git commit for changes")
        print("  /verbose      - Enable verbose output (default)")
        print("  /minimal      - Enable minimal output mode")
        print("  /sandbox      - Toggle code sandbox for Python/JS execution")
        print("  /run-python   - Run Python code from last response in sandbox")
        print("  /run-js       - Run JavaScript code from last response in sandbox")
        print("  /quit         - Exit (shows session summary)")
        print("=" * 60)

        # Check git repo status
        if git_integration.is_git_repo():
            print(f"[Git] Repository detected: {git_integration.git_root}")
        else:
            print("[Git] No git repository detected")

        # Show current output mode
        mode = "VERBOSE" if output_mode_manager.verbose else "MINIMAL"
        print(f"[Output Mode] {mode}")

        os.environ["AGENTIC_STREAM"] = "1"

        # Force API mode in REPL for better streaming support
        use_api_for_repl = True
        if not HAS_REQUESTS:
            print("[Note] 'requests' library not found, falling back to CLI mode")
            use_api_for_repl = False

        try:
            while True:
                prompt = input("\n>>> ").strip()
                if not prompt:
                    continue

                if prompt == "/quit":
                    # Feature 8: Session summary
                    print(session_stats.get_summary())

                    # Feature 10: Git integration - offer commit
                    if git_integration.is_git_repo() and git_integration.modified_files:
                        git_integration.offer_commit()

                    print("Goodbye!")
                    break
                elif prompt == "/clear":
                    conversation_memory.clear()
                    print("Conversation memory cleared.")
                    continue
                elif prompt == "/tools":
                    print("\nAvailable tools:")
                    for name, tool in TOOL_REGISTRY.items():
                        print(f"  - {name}: {tool.description}")
                    continue
                elif prompt == "/undo":
                    success, msg = undo_manager.undo_last()
                    print(f"[Undo] {msg}")
                    continue
                elif prompt == "/verbose":
                    output_mode_manager.set_verbose()
                    continue
                elif prompt == "/minimal":
                    output_mode_manager.set_minimal()
                    continue
                elif prompt == "/sandbox":
                    code_sandbox.enabled = not code_sandbox.enabled
                    status = "enabled" if code_sandbox.enabled else "disabled"
                    print(f"\n[Code Sandbox] {status}")
                    continue
                elif prompt.startswith("/run-python") or prompt.startswith("/run-js"):
                    # Handled in prompt_and_act
                    pass
                elif prompt.startswith("/dry-run"):
                    # Handled in prompt_and_act
                    pass

                print("--- Executing ---")
                stream = os.environ.get("AGENTIC_STREAM", "0") == "1"
                result = prompt_and_act(prompt, use_api=use_api_for_repl)

                # Only print response if not streaming (streaming prints as it goes)
                if not stream:
                    cleaned = clean_llm_output(result["response"])
                    print("\n" + "=" * 50)
                    print(cleaned)
                    print("=" * 50)

                # Print action result in human-readable format
                if result.get("action_type"):
                    print("\n[Action Performed]")
                    if result["action_type"] == "tool":
                        action = result.get("action", {})
                        tool_name = action.get("tool", "unknown")
                        params = action.get("parameters", {})
                        if tool_name == "write_file":
                            print(f"  Created file: {params.get('filepath', 'unknown')}")
                        elif tool_name == "delete_file":
                            print(f"  Deleted file: {params.get('filepath', 'unknown')}")
                        elif tool_name == "run_command":
                            cmd_result = result.get("result", {})
                            if cmd_result.get("success"):
                                print(f"  Command executed successfully")
                                output = cmd_result.get("output", "")
                                if output and output != "(no output)":
                                    print(f"  Output:\n    {output[:500]}")  # Limit output length
                            else:
                                print(f"  Command failed: {cmd_result.get('error', 'unknown error')}")
                        elif tool_name == "read_file":
                            file_result = result.get("result", {})
                            data = file_result.get("data", {})
                            print(f"  Read file: {data.get('filepath', 'unknown')} ({data.get('size', 0)} bytes)")
                        else:
                            print(f"  Executed: {tool_name}")
                    elif result["action_type"] == "command":
                        print(f"  Command executed")
                    elif result["action_type"] == "plan":
                        plan_result = result.get("result", {})
                        print(f"  Plan: {plan_result.get('goal', 'Multi-step task')}")
                        print(f"  Completed: {plan_result.get('summary', 'unknown')}")

        except KeyboardInterrupt:
            print("\nExiting interactive mode.")

    elif args.prompt:
        result = prompt_and_act(args.prompt, args.api)
        cleaned = clean_llm_output(result["response"])
        print(cleaned)
        print("\n--- Action Details ---")
        print(json.dumps({k: v for k, v in result.items() if k != "response"}, indent=2, ensure_ascii=False))

    else:
        print("Agentic Bridge - Local AI Agent")
        print(f"Model: {OLLAMA_MODEL}")
        print("\nUsage:")
        print("  --prompt 'your prompt'  - Execute a single prompt")
        print("  --repl                  - Interactive mode")
        print("  --http                  - Run as HTTP server")
        print("  --api                   - Use Ollama API (default: CLI)")
        print("\nExample:")
        print("  python agentic_bridge.py --repl")
        print("  python agentic_bridge.py --prompt 'create a file hello.py with a hello world program'")
