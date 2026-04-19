#!/usr/bin/env python3
"""
gRPC Server for MCP Integration

Provides MCP protocol over gRPC for efficient RPC communication.
"""

import grpc
from concurrent import futures
import os
import json
import logging
from typing import Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Try to import grpc modules
try:
    import grpc
    GRPC_AVAILABLE = True
except ImportError:
    GRPC_AVAILABLE = False
    logger.warning("grpcio not installed. Install with: pip install grpcio")


# =============================================================================
# gRPC Service Implementation (placeholder - requires .proto compilation)
# =============================================================================

class MCPServicer:
    """
    gRPC servicer for MCP protocol.

    Note: This requires compiled protobuf classes from mcp.proto
    For now, provides a simple implementation that can be extended.
    """

    def __init__(self):
        self.tools = {
            "read_file": self._read_file,
            "write_file": self._write_file,
            "list_directory": self._list_directory,
            "run_command": self._run_command,
        }
        self.resources: Dict[str, str] = {}

    def _read_file(self, filepath: str) -> Dict[str, Any]:
        """Read file contents."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return {"success": True, "content": f.read()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _write_file(self, filepath: str, content: str) -> Dict[str, Any]:
        """Write content to file."""
        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            return {"success": True, "message": f"Written to {filepath}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _list_directory(self, path: str) -> Dict[str, Any]:
        """List directory contents."""
        try:
            items = os.listdir(path)
            return {"success": True, "items": items}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _run_command(self, command: str) -> Dict[str, Any]:
        """Run shell command."""
        try:
            import subprocess
            result = subprocess.run(command, shell=True, capture_output=True, text=True)
            return {
                "success": True,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def call_tool(self, tool_name: str, arguments: Dict) -> Dict[str, Any]:
        """Call a tool by name."""
        if tool_name not in self.tools:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}
        return self.tools[tool_name](**arguments)


class GRPCMCPServer:
    """
    gRPC MCP Server.

    Start with:
        server = GRPCMCPServer(port=50051)
        server.start()
    """

    def __init__(self, port: int = 50051, max_workers: int = 10):
        self.port = port
        self.max_workers = max_workers
        self.server = None
        self.servicer = MCPServicer()

    def start(self):
        """Start the gRPC server."""
        if not GRPC_AVAILABLE:
            logger.error("grpcio not installed. Cannot start server.")
            return False

        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=self.max_workers))

        # Note: In production, you would add your servicer to the server:
        # add_MCPServicer_to_server(self.servicer, self.server)

        self.server.add_insecure_port(f'[::]:{self.port}')
        self.server.start()
        logger.info(f"gRPC MCP Server started on port {self.port}")
        return True

    def stop(self, grace: int = 0):
        """Stop the gRPC server."""
        if self.server:
            self.server.stop(grace)
            logger.info("gRPC MCP Server stopped")

    def wait_for_termination(self):
        """Block until server terminates."""
        if self.server:
            self.server.wait_for_termination()


# =============================================================================
# Simple JSON-RPC over HTTP (alternative to gRPC)
# =============================================================================

from http.server import HTTPServer, BaseHTTPRequestHandler


class MCPRequestHandler(BaseHTTPRequestHandler):
    """HTTP handler for JSON-RPC style MCP requests."""

    def __init__(self, *args, servicer=None, **kwargs):
        self.servicer = servicer or MCPServicer()
        super().__init__(*args, **kwargs)

    def do_POST(self):
        """Handle JSON-RPC POST requests."""
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')

        try:
            request = json.loads(body)
            method = request.get('method')
            params = request.get('params', {})

            if method == 'tools/call':
                tool_name = params.get('name')
                arguments = params.get('arguments', {})
                result = self.servicer.call_tool(tool_name, arguments)
            elif method == 'tools/list':
                result = {"tools": list(self.servicer.tools.keys())}
            elif method == 'ping':
                result = {"status": "pong"}
            else:
                result = {"error": f"Unknown method: {method}"}

            response = {
                "jsonrpc": "2.0",
                "id": request.get('id', 1),
                "result": result
            }

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())

        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error": "Invalid JSON"}')

    def log_message(self, format, *args):
        logger.info(f"{self.address_string()} - {format % args}")


def run_http_server(port: int = 50052):
    """Run HTTP server for MCP (simpler alternative to gRPC)."""
    servicer = MCPServicer()
    server = HTTPServer(('localhost', port), lambda *args, **kwargs: MCPRequestHandler(*args, servicer=servicer, **kwargs))
    logger.info(f"HTTP MCP Server starting on port {port}")
    server.serve_forever()


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--http":
        # Run HTTP server (simpler, no grpcio needed)
        run_http_server()
    else:
        # Run gRPC server
        server = GRPCMCPServer(port=50051)
        if server.start():
            print("gRPC MCP Server running on port 50051")
            print("Press Ctrl+C to stop")
            try:
                server.wait_for_termination()
            except KeyboardInterrupt:
                server.stop()
                print("\nServer stopped")
