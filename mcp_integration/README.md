# MCP Integration

Model Context Protocol integration for AI assistants.

## Installation

```bash
pip install -r requirements.txt
```

## Usage

1. Start the server:
```bash
python server.py
```

2. Use the client:
```python
from client import execute_tool
result = execute_tool("read_file", {"filepath": "example.txt"})
```

## Available Tools

- `read_file` - Read file contents
- `write_file` - Write file contents  
- `run_command` - Execute shell commands
