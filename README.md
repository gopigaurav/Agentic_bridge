# Agentic Bridge - Local AI Agent

A complete agentic AI system that enables local LLM models (via Ollama) to perform real actions on your system - similar to Claude or GitHub Copilot, but running 100% locally.

## Features

### Core Features
- **Tool-Based Architecture**: 8 built-in tools for file operations, commands, git, and search
- **Multi-Step Planning**: Break complex tasks into sequential actions
- **Conversation Memory**: Maintains context across multiple turns
- **Safety Layer**: Confirmation prompts for destructive actions
- **Multiple Interfaces**: REPL, HTTP server, and CLI modes
- **Smart Filename Correction**: Auto-corrects typos in filenames using Levenshtein distance

### Advanced Features
1. **Auto-Retry with Corrected Parameters**: When a tool fails (e.g., file not found), automatically retries with corrections
2. **Undo/Rollback Capability**: Track file changes and revert the last action with `/undo`
3. **Dry-Run Mode**: Preview actions before executing with `/dry-run`
4. **Better Error Messages**: Shows suggestions and lists files in directory when errors occur
5. **Multi-File Context Understanding**: Automatically reads related files when explaining code
6. **Code Execution Sandbox**: Safely run Python/JS code with `/run-python` or `/run-js`
7. **Progress Indicators**: Shows `[Step X/Y]` progress for long operations
8. **Session Summaries**: Displays accomplishments on exit
9. **Output Mode Toggle**: Switch between verbose and minimal output
10. **Git Integration**: Auto-detects repo and offers to commit changes
11. **Multi-Action Execution**: Executes ALL tool calls in a single response (creates multiple files at once)
12. **Real-Time Streaming**: Watch the LLM's reasoning as it generates responses
13. **Continuation Loop**: Automatically continues executing until task is complete (like Claude)
14. **Claude-like Permission Prompts**: 3 options (Allow/Deny/Allow Always) for file operations
15. **Goal/Step Tracking**: Visual progress tracking with strikethrough for completed steps

## Prerequisites

1. **Python 3.8+** installed
2. **Ollama** installed and running locally
3. **Model** pulled (e.g., `qwen2.5-coder`, `llama3`, `mistral`):
   ```bash
   ollama pull qwen2.5-coder:7b
   ```

## Installation

```bash
# Install Python dependencies
pip install requests

# Verify Ollama is running
ollama list

# Test the model
ollama run qwen2.5-coder:7b "Hello!"
```

## Usage

### Interactive REPL Mode (Recommended)

```bash
python agentic_bridge.py --repl
```

### HTTP Server Mode

```bash
python agentic_bridge.py --http --port 8080
```

### Single Prompt Execution

```bash
python agentic_bridge.py --prompt "create a Flask API with user authentication" --api
```

## Interactive REPL Commands

| Command | Description |
| :--- | :--- |
| `/quit` | Exit with session summary and git commit offer |
| `/clear` | Clear conversation memory |
| `/tools` | List all available tools |
| `/undo` | Undo the last file modification |
| `/dry-run` | Enable dry-run mode (preview actions without executing) |
| `/dry-run-off` | Disable dry-run mode |
| `/dry-run-show` | Show all planned actions |
| `/git-commit` | Create git commit for modified files |
| `/goals` | Display current goals and progress (Claude-like strikethrough) |
| `/verbose` | Enable verbose output mode (default) |
| `/minimal` | Enable minimal output mode (results only) |
| `/sandbox` | Toggle code sandbox on/off |
| `/run-python` | Execute Python code from last response in sandbox |
| `/run-js` | Execute JavaScript code from last response in sandbox |
| `/agentic` | **TRUE AGENTIC MODE**: Autonomous loop until goal achieved |
| `/reset-permissions` | Reset all granted permissions |

## Modes of Operation

### Normal Mode - Tool-Calling Assistant
One prompt triggers multiple actions with continuation loop.
```
>>> add router code to the React app

[Task Execution Started]
Will continue executing until task appears complete (max 10 iterations)

[LLM Thinking...]
[Action 1/3] Create src/router.js
[Success] File created: src/router.js

[Action 2/3] Edit src/App.js
[Success] File edited: src/App.js

[Action 3/3] Edit src/index.js
[Success] File edited: src/index.js

[Task Complete]
```

### Agentic Mode - Autonomous AI Agent
The agent loops autonomously until the goal is achieved with goal tracking.
```
>>> /agentic create a Flask API with user authentication

============================================================
GOAL: create a Flask API with user authentication
Progress: 0/5 steps
============================================================
  [○] 1. Create app.py
  [○] 2. Create auth.py
  [○] 3. Create models.py
  [○] 4. Create requirements.txt
  [○] 5. Test the server
============================================================

[Iteration 1/20] Creating app.py...
[Success]

[Iteration 2/20] Creating auth.py...
[Success]

...

[Goal Achieved!]
Flask API with JWT authentication is ready.
```

## Claude-Like Features (New!)

### 1. Permission Prompts

When creating/editing files, you get 3 options like Claude:

```
============================================================
[Permission Request]
============================================================
Tool: write_file
File: src/components/TodoList.js

Options:
  [A] Allow - Allow this operation once
  [D] Deny  - Skip this operation
  [AA] Allow Always - Allow this and similar files for rest of session

Your choice (A/D/AA): 
```

### 2. Goal/Step Tracking with Visual Progress

Goals are tracked with strikethrough for completed steps:

```
============================================================
GOAL: create a Flask API with user authentication
Progress: 3/5 steps
============================================================
  [✓] 1. C̶r̶e̶a̶t̶e̶ ̶a̶p̶p̶.̶p̶y̶
  [✓] 2. C̶r̶e̶a̶t̶e̶ ̶a̕u̶t̶h̶.̶p̶y̶
  [✓] 3. C̶r̶e̶a̶t̶e̶ ̶m̶o̶d̶e̶l̶s̶.̶p̶y̶
  [○] 4. Create requirements.txt
  [○] 5. Test the server
============================================================
```

### 3. Continuation Loop

The agent automatically continues executing until the task is complete:

```
>>> add a todo list UI to the React app

[Task Execution Started]
Will continue executing until task appears complete (max 10 iterations)

[Iteration 1] Creating TodoList.js...
[Iteration 2] Creating TodoItem.js...
[Iteration 3] Updating App.js...
[Iteration 4] Updating index.css...
[Task Complete]
```

## Code Structure (agentic_bridge.py)

### File Statistics
- **Total Lines**: ~3100+
- **Classes**: 25+
- **Functions**: 60+
- **Tools**: 8 built-in

### Core Classes

#### 1. ConversationMemory (Line ~141)
Maintains conversation history and context variables.
```python
class ConversationMemory:
    def __init__(self, max_turns: int = 20)
    def add_turn(self, role: str, content: str, actions: List = None)
    def get_recent_context(self, n: int = 5) -> str
    def set_variable(self, key: str, value: Any)
    def get_variable(self, key: str, default: Any = None) -> Any
    def clear(self)
```

#### 2. SessionStats (Line ~226)
Tracks session statistics for summaries.
```python
class SessionStats:
    files_created: int
    files_modified: int
    files_deleted: int
    commands_run: int
    tools_used: Dict[str, int]
```

#### 3. UndoManager (Line ~297)
Manages undo history for file modifications.
```python
class UndoManager:
    def save_file_state(self, filepath: str) -> str
    def undo_last(self) -> Tuple[bool, str]
    def clear(self)
```

#### 4. DryRunManager (Line ~389)
Manages dry-run mode for previewing actions.
```python
class DryRunManager:
    enabled: bool
    planned_actions: List[Dict]
    def enable(self)
    def disable(self)
    def record_action(self, action: Dict) -> str
    def show_planned_actions(self)
```

#### 5. MultiFileContextReader (Line ~433)
Automatically reads related files for context.
```python
class MultiFileContextReader:
    DOMAIN_PATTERNS: Dict[str, List[str]]  # auth, database, api, config, etc.
    def find_related_files(self, prompt: str, base_filepath: str) -> List[str]
    def read_context(self, prompt: str, base_filepath: str) -> str
```

#### 6. OutputModeManager (Line ~686)
Manages output verbosity (verbose vs minimal).
```python
class OutputModeManager:
    verbose: bool
    def set_minimal(self)
    def set_verbose(self)
    def toggle(self)
    def should_explain(self) -> bool
```

#### 7. ProgressIndicator (Line ~724)
Shows progress indicators for long operations.
```python
class ProgressIndicator:
    SPINNERS: List[str]
    def start_operation(self, description: str)
    def update(self, current: int, total: int, description: str)
    def complete(self, success: bool = True)
```

#### 8. CodeSandbox (Line ~769)
Sandbox for safely executing Python/JS code.
```python
class CodeSandbox:
    enabled: bool
    timeout: int
    def execute_python(self, code: str, allowed_imports: List[str]) -> Tuple[bool, str]
    def execute_javascript(self, code: str) -> Tuple[bool, str]
```

#### 9. GitIntegration (Line ~543)
Git integration for auto-committing changes.
```python
class GitIntegration:
    modified_files: List[str]
    git_root: Optional[str]
    def track_file_modification(self, filepath: str)
    def offer_commit(self) -> bool
    def get_status(self) -> Dict[str, List[str]]
```

#### 10. AgenticLoop (Line ~898) - TRUE AGENTIC AI
The core agentic loop that works autonomously toward goals.
```python
class AgenticLoop:
    goal: str
    max_iterations: int
    iteration: int
    completed_steps: List[str]
    failed_steps: List[str]
    
    def _build_loop_prompt(self) -> str
    def _check_goal_complete(self, llm_response: str) -> Tuple[bool, str]
    def _parse_next_action(self, response: str) -> Optional[Dict]
    def run(self, use_api: bool = False) -> Dict
```

#### 11. GoalStepTracker (Line ~2350) - CLAUDE-LIKE
Visual goal/step tracking with strikethrough.
```python
class GoalStepTracker:
    goals: List[Dict]
    current_goal_idx: int
    
    def create_goal(self, goal: str, steps: List[str] = None) -> int
    def add_step(self, step_desc: str, goal_idx: int = None)
    def mark_step_done(self, step_idx: int, goal_idx: int = None)
    def mark_goal_complete(self, goal_idx: int = None)
    def display(self, verbose: bool = True)
    def get_current_goal(self)
```

#### 12. PermissionManager (Line ~2400) - CLAUDE-LIKE
Claude-style permission prompts with 3 options.
```python
class PermissionManager:
    allowed_always: Set[str]
    denied_always: Set[str]
    
    def check_permission(self, action: Dict) -> Tuple[bool, str]
    def grant_permission(self, filepath: str, scope: str = "once")
    def ask_permission(self, action: Dict) -> bool
```

### Tool Classes (Line ~1106+)

All tools inherit from the base `Tool` class:

```python
class Tool:
    name: str
    description: str
    def validate(self, **kwargs) -> Tuple[bool, str]
    def execute(self, **kwargs) -> ToolResult
```

#### ToolResult
```python
class ToolResult:
    success: bool
    output: str
    error: str
    data: Any
```

#### Available Tools

| Tool | Class | Description |
|------|-------|-------------|
| `read_file` | ReadFileTool | Read file contents with auto-correction |
| `write_file` | WriteFileTool | Create/overwrite files with undo tracking |
| `edit_file` | EditFileTool | Search-replace or line-based editing |
| `delete_file` | DeleteFileTool | Delete files (requires confirmation) |
| `run_command` | RunCommandTool | Execute shell commands |
| `search_code` | SearchCodeTool | Grep-like code search |
| `git` | GitTool | Safe git operations only |
| `list_directory` | ListDirectoryTool | List directory contents |

### Key Functions

#### Main Entry Points

```python
# Main function - processes prompt and executes actions (with continuation loop)
prompt_and_act(prompt: str, use_api: bool = False, max_continuations: int = 10) -> dict

# True agentic mode - loops until goal achieved
run_agentic_mode(goal: str, max_iterations: int = 20, use_api: bool = False) -> Dict
```

#### Response Parsing

```python
# Parse ALL tool calls from response (multi-action support)
parse_all_actions_from_response(response: str) -> List[Dict[str, Any]]

# Parse single action (legacy, returns first)
parse_action_from_response(response: str) -> Optional[Dict[str, Any]]

# Parse multi-step plans
parse_plan_from_response(response: str) -> Optional[Plan]
```

#### Execution

```python
# Execute a single action (with auto-retry)
execute_action(action: Dict, auto_retry: bool = True, max_retries: int = 2) -> ToolResult

# Execute a multi-step plan
execute_plan(plan: Plan) -> List[Dict]
```

#### LLM Interaction

```python
# Build system prompt with tool schemas
build_system_prompt() -> str

# Ollama chat API (recommended for streaming)
run_ollama_chat(messages: List[Dict], stream: bool = False) -> str

# Ollama generate API
run_ollama_generate(prompt: str, stream: bool = True) -> str

# Ollama CLI fallback
run_ollama_cli(prompt: str, stream: bool = False) -> str
```

#### Utility Functions

```python
# Find similar filename (typo correction)
find_similar_file(filepath: str, max_distance: int = 3) -> str

# Auto-correct parameters on failure
auto_correct_parameters(tool_name: str, params: Dict, error: str) -> Tuple[bool, Dict]

# Check if action is destructive
is_destructive_action(action: Dict) -> bool

# Require user confirmation
require_confirmation(action: Dict) -> bool
confirm_action(action: Dict) -> bool

# Format action for display
format_action_description(action: Dict) -> str

# Clean LLM output (remove ANSI codes)
clean_llm_output(text: str) -> str
```

### Safety Layer

#### Destructive Commands Detection
```python
DESTRUCTIVE_COMMANDS = [
    "rm ", "del ", "rmdir ", "remove-item ",
    "format ", "fdisk ", "mkfs ",
    "chmod 777 ", "chown ",
    "> ", ">> ",  # redirections
    "dd ", "shutdown ", "reboot ",
    "git reset --hard", "git clean -fd", "git push --force"
]
```

#### Allowed File Extensions
```python
ALLOWED_FILE_EXTENSIONS = [
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs", ".c", ".cpp", ".h",
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".html", ".css", ".scss", ".less", ".vue", ".svelte",
    ".sh", ".bat", ".ps1", ".zsh", ".fish",
    ".sql", ".graphql", ".proto",
    ".env", ".gitignore", ".dockerignore"
]
```

### Agentic Loop Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  1. RECEIVE GOAL                                            │
│     User: "/agentic create a Flask API"                     │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  2. CREATE GOAL TRACKER ENTRY                               │
│     - Goal: "create a Flask API"                            │
│     - Steps: [app.py, auth.py, models.py, ...]              │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  3. BUILD CONTEXT PROMPT                                    │
│     - Current goal                                           │
│     - Completed steps so far                                 │
│     - Failed steps and errors                                │
│     - Current file system state                              │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  4. LLM DECIDES NEXT SINGLE STEP (with streaming)          │
│     "I should create app.py first"                          │
│     OR "Goal is complete!"                                  │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  5. ASK PERMISSION (Claude-like)                           │
│     [A] Allow  [D] Deny  [AA] Allow Always                 │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  6. PARSE ALL ACTIONS FROM RESPONSE                         │
│     May contain multiple tool calls                         │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  7. EXECUTE ALL ACTIONS (with auto-retry)                  │
│     [Creates app.py, auth.py, etc.]                         │
│     Mark steps as done with strikethrough                   │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  8. OBSERVE RESULTS                                         │
│     Success → Add to completed_steps, mark step done        │
│     Failure → Add to failed_steps, auto-retry               │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  9. CONTINUATION CHECK                                      │
│     Task complete? → Exit                                    │
│     More actions needed? → Continue (max 10 iterations)      │
│     Max iterations? → Exit with partial                      │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  10. FINAL GOAL CHECK                                       │
│     LLM says "yes" → Exit with summary                       │
│     LLM says "no"  → Go to step 3 (replan)                  │
└─────────────────────────────────────────────────────────────┘
```

### HTTP Server (Line ~2880+)

```python
class AgenticHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        # Handle POST: {"prompt": "...", "use_api": true}
        
    def do_GET(self):
        # Health check: {"status": "ok", "model": "qwen2.5-coder"}

def start_http_server(port=8080)
```

**Endpoints:**
- `POST /` - Execute a prompt
- `GET /` - Health check

### Configuration

#### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AGENTIC_STREAM` | Enable streaming output | `0` |
| `VSCODE_CURRENT_FILE` | Current file in VS Code | - |
| `OLLAMA_MODEL` | Model to use | `qwen3.5` |

#### Constants in Code

```python
OLLAMA_MODEL = "qwen3.5"
OLLAMA_API_URL = "http://localhost:11434/api/generate"
CHAT_API_URL = "http://localhost:11434/api/chat"
```

## Example Interactions

### Claude-like Permission Prompt
```
>>> create a React component for todo list

============================================================
[Permission Request]
============================================================
Tool: write_file
File: src/TodoList.js

Options:
  [A] Allow - Allow this operation once
  [D] Deny  - Skip this operation
  [AA] Allow Always - Allow this and similar .js files

Your choice (A/D/AA): AA

[Success] File created: src/TodoList.js
[Permission granted for *.js files this session]
```

### Goal Tracking Display
```
>>> /goals

============================================================
GOAL: create a Flask API with user authentication
Progress: 3/5 steps
============================================================
  [✓] 1. C̶r̶e̶a̶t̶e̶ ̶a̶p̶p̶.̶p̶y̶
  [✓] 2. C̶r̶e̶a̶t̶e̶ ̶a̶u̶t̶h̶.̶p̶y̶
  [✓] 3. C̶r̶e̶a̶t̶e̶ ̶m̶o̶d̶e̶l̶s̶.̶p̶y̶
  [○] 4. Create requirements.txt
  [○] 5. Test the server
============================================================
```

### Multi-Action Execution with Continuation
```
>>> add router to React app

[Task Execution Started]
Will continue executing until task appears complete (max 10 iterations)

[LLM Thinking...]

[Action 1/4] Create src/router.js
[Success] File created: src/router.js

[Action 2/4] Edit src/App.js
[Success] File edited: src/App.js

[Continuation] Checking if more actions needed...

[Action 3/4] Edit src/index.js
[Success] File edited: src/index.js

[Continuation] Checking if more actions needed...

[Task Complete] Router has been added to the React application.
```

## Troubleshooting

### Silent Waiting (5+ seconds)
- **Fixed**: Streaming now shows LLM reasoning in real-time
- Ensure `requests` is installed: `pip install requests`
- Use `--api` flag for better streaming

### Only First File Created
- **Fixed**: `parse_all_actions_from_response()` now executes ALL tool calls
- **Fixed**: Continuation loop keeps executing until task is complete

### Permission Prompts Not Showing
- Check if `--no-confirm` flag is used (disables prompts)
- Reset permissions with `/reset-permissions`

### "File does not exist" Errors
- Auto-correction is enabled
- Check suggested files in error message

### Git Integration Not Working
- Ensure you're in a git repository
- Verify git is installed

### Code Sandbox Errors
- Python: Dangerous imports blocked (`os`, `sys`, `subprocess`)
- JS: Node.js must be installed

## Extending the Agent

### Adding New Tools

```python
class MyCustomTool(Tool):
    name = "my_tool"
    description = "Does something useful"

    def validate(self, param1: str, **kwargs) -> Tuple[bool, str]:
        if not param1:
            return False, "param1 is required"
        return True, ""

    def execute(self, param1: str, **kwargs) -> ToolResult:
        # Your implementation
        return ToolResult(success=True, output="Done!")

# Register
TOOL_REGISTRY["my_tool"] = MyCustomTool()
```

### Adding Custom Permission Rules

```python
# Allow all Python files in current project
permission_manager.allowed_always.add("*.py")

# Deny specific sensitive files
permission_manager.denied_always.add(".env")
permission_manager.denied_always.add("*.key")
```

## License

MIT License - Feel free to use and modify as needed.
