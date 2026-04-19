from flask import Flask, request, jsonify
import os

app = Flask(__name__)

@app.route('/health')
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "ok"})

@app.route('/tools', methods=['GET'])
def list_tools():
    """List available tools"""
    tools = [
        {
            "name": "read_file",
            "description": "Read file contents"
        },
        {
            "name": "write_file",
            "description": "Write file contents"
        },
        {
            "name": "run_command",
            "description": "Execute shell commands"
        }
    ]
    return jsonify(tools)

@app.route('/tools/<tool_name>', methods=['POST'])
def execute_tool(tool_name):
    """Execute a specific tool"""
    if tool_name == "read_file":
        return execute_read_file()
    elif tool_name == "write_file":
        return execute_write_file()
    elif tool_name == "run_command":
        return execute_run_command()
    else:
        return jsonify({"error": "Unknown tool"}), 404

def execute_read_file():
    """Read file contents"""
    data = request.get_json()
    filepath = data.get('filepath')
    if filepath:
        with open(filepath, 'r') as f:
            return jsonify({"content": f.read()})
    return jsonify({"error": "No filepath provided"}), 400

def execute_write_file():
    """Write file contents"""
    data = request.get_json()
    filepath = data.get('filepath')
    content = data.get('content')
    if filepath and content:
        with open(filepath, 'w') as f:
            f.write(content)
        return jsonify({"status": "success"})
    return jsonify({"error": "Missing filepath or content"}), 400

def execute_run_command():
    """Execute shell commands"""
    data = request.get_json()
    command = data.get('command')
    if command:
        import subprocess
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        return jsonify({
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        })
    return jsonify({"error": "No command provided"}), 400

if __name__ == "__main__":
    app.run(host='localhost', port=8080)
