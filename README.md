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

### Advanced Features (New!)
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
# Start server on default port 8080
python agentic_bridge.py --http

# Start server on custom port
python agentic_bridge.py --http --port 3000
```

### Single Prompt Execution

```bash
# Basic usage
python agentic_bridge.py --prompt "create a file hello.py with a hello world program"

# Use API mode (better streaming)
python agentic_bridge.py --prompt "explain agentic_bridge.py" --api

# Skip confirmation for destructive actions
python agentic_bridge.py --prompt "delete file temp.txt" --no-confirm
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
| `/verbose` | Enable verbose output mode (default) |
| `/minimal` | Enable minimal output mode (results only) |
| `/sandbox` | Toggle code sandbox on/off |
| `/run-python` | Execute Python code from last response in sandbox |
| `/run-js` | Execute JavaScript code from last response in sandbox |

## Available Tools

| Tool | Description | Example |
|------|-------------|---------|
| `read_file` | Read contents of a file | "read the file config.py" |
| `write_file` | Create or overwrite a file | "create a file main.py with a flask app" |
| `edit_file` | Edit files (search-replace or full content) | "edit main.py to add logging" |
| `delete_file` | Delete a file | "delete file temp.txt" |
| `run_command` | Execute a shell command | "run ls -la" |
| `search_code` | Search for patterns in code | "search for 'def main' in .py files" |
| `git` | Execute safe git operations | "git status", "git diff" |
| `list_directory` | List folder contents | "list files in src/" |

## Example Interactions

### File Creation
```
>>> create a file calculator.py with functions for add, subtract, multiply, and divide
```

### File Understanding (Multi-File Context)
```
>>> explain how authentication works
# Automatically reads auth.py, middleware.py, routes.py if related
```

### Dry-Run Mode
```
>>> /dry-run create a flask app
[DRY-RUN] Would execute: Create/overwrite file: app.py
[DRY-RUN] Would execute: Create/overwrite file: requirements.txt
```

### Undo Last Change
```
>>> /undo
[Undo] Restored: main.py
```

### Code Sandbox
```
>>> /run-python
print("Hello from sandbox!")
# Output: Hello from sandbox!
```

### Git Integration
```
>>> /quit
Session Summary:
  Files created: 3
  Files modified: 1
  Commands run: 2
Files modified. Create a git commit? (yes/no): yes
[Git] Commit created: [Agentic] Changes at 2026-04-08
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AGENTIC_STREAM` | Enable streaming output | `0` |
| `VSCODE_CURRENT_FILE` | Current file in VS Code | - |
| `OLLAMA_MODEL` | Model to use | `qwen2.5-coder:7b` |

### Model Configuration

Edit in `agentic_bridge.py`:
```python
OLLAMA_MODEL = "qwen2.5-coder:7b"  # Change to any Ollama model
OLLAMA_API_URL = "http://localhost:11434/api/generate"
CHAT_API_URL = "http://localhost:11434/api/chat"
```

## Safety Features

### Destructive Command Detection
Commands requiring confirmation:
- File deletion: `rm`, `del`, `remove-item`
- Disk operations: `format`, `fdisk`, `mkfs`
- Permission changes: `chmod 777`, `chown`
- Dangerous git: `git reset --hard`, `git clean -fd`, `git push --force`

### Bypassing Confirmation
```bash
python agentic_bridge.py --repl --no-confirm
```

## HTTP API

**Endpoints:**
- `POST /` - Send a prompt: `{"prompt": "...", "use_api": true}`
- `GET /` - Health check

**Example:**
```bash
curl -X POST http://localhost:8080 \
  -H "Content-Type: application/json" \
  -d '{"prompt": "create a file test.py with print hello", "use_api": true}'
```

## Architecture

```
User Interface (REPL/HTTP/CLI)
        │
        ▼
Intent Detection
        │
        ▼
Conversation Memory + Multi-File Context
        │
        ▼
LLM (Ollama)
        │
        ▼
Response Parser ([TOOL], [RUN], [PLAN])
        │
        ▼
Safety Layer → Dry-Run Check
        │
        ▼
Tool Executor (with Auto-Retry)
        │
        ▼
Git Tracking + Session Stats
```

## Troubleshooting

### Responses Cut Off Mid-Sentence
- Ensure `requests` library is installed: `pip install requests`
- Use API mode: `--api` flag

### "File does not exist" Errors
- The agent auto-corrects typos automatically
- Check suggested files in the error message

### Git Integration Not Working
- Ensure you're in a git repository
- Verify git is installed and in PATH

### Code Sandbox Errors
- For Python: Dangerous imports are blocked (`os`, `sys`, `subprocess`, etc.)
- For JS: Node.js must be installed (`node` in PATH)

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
        return ToolResult(success=True, output="Done!")

# Register
TOOL_REGISTRY["my_tool"] = MyCustomTool()
```

## License

MIT License - Feel free to use and modify as needed.
