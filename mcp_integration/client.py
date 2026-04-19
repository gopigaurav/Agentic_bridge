import requests
import json

def call_mcp_server(endpoint, method="GET", data=None):
    """
    Client code for MCP (Model Context Protocol) integration
    """
    url = f"http://localhost:8080{endpoint}"
    
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    if method == "POST" and data:
        response = requests.post(url, headers=headers, json=data)
    else:
        response = requests.get(url, headers=headers)
    
    try:
        result = response.json()
        print(f"Response: {result}")
        return result
    except:
        print(f"Raw response: {response.text}")
        return response.text

def list_available_tools():
    """List available MCP tools"""
    return call_mcp_server("/tools", method="GET")

def execute_tool(tool_name, args):
    """Execute a specific MCP tool"""
    return call_mcp_server(f"/tools/{tool_name}", method="POST", data={"args": args})

if __name__ == "__main__":
    print("MCP Integration Client")
    print("Available tools:", list_available_tools())
