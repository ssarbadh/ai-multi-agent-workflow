"""CLI wrapper for running MCP servers via stdio transport."""

import argparse
import asyncio
import json
import sys
from typing import Optional

from app.servers.base import BaseMCPServer
from app.servers.infra_server import InfrastructureMCPServer
from app.servers.rag_server import RAGMCPServer
from app.servers.context_server import ContextMCPServer
from app.core.logging import get_logger

logger = get_logger(__name__)

# Available servers
SERVERS = {
    "infra": InfrastructureMCPServer,
    "rag": RAGMCPServer,
    "context": ContextMCPServer,
}


class StdioTransport:
    """Handle MCP communication over stdio."""
    
    def __init__(self, server: BaseMCPServer):
        self.server = server
        self.running = False
    
    async def read_message(self) -> Optional[dict]:
        """Read a JSON-RPC message from stdin."""
        try:
            line = await asyncio.get_event_loop().run_in_executor(
                None, sys.stdin.readline
            )
            if not line:
                return None
            return json.loads(line.strip())
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON", error=str(e))
            return None
    
    def write_message(self, message: dict):
        """Write a JSON-RPC message to stdout."""
        sys.stdout.write(json.dumps(message) + "\n")
        sys.stdout.flush()
    
    async def handle_message(self, message: dict) -> dict:
        """Process an MCP message and return response."""
        method = message.get("method", "")
        params = message.get("params", {})
        msg_id = message.get("id")
        
        try:
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {"listChanged": True},
                        "resources": {"subscribe": True, "listChanged": True},
                        "prompts": {"listChanged": True},
                    },
                    "serverInfo": self.server.get_server_info().model_dump(),
                }
            elif method == "tools/list":
                tools = self.server.list_tools()
                result = {"tools": [t.model_dump() for t in tools]}
            elif method == "tools/call":
                tool_result = await self.server.call_tool(
                    params.get("name", ""),
                    params.get("arguments", {})
                )
                result = tool_result.model_dump()
            elif method == "resources/list":
                resources = self.server.list_resources()
                result = {"resources": [r.model_dump() for r in resources]}
            elif method == "resources/read":
                resource_result = await self.server.read_resource(params.get("uri", ""))
                result = resource_result.model_dump()
            elif method == "prompts/list":
                prompts = self.server.list_prompts()
                result = {"prompts": [p.model_dump() for p in prompts]}
            elif method == "prompts/get":
                prompt_result = await self.server.get_prompt(
                    params.get("name", ""),
                    params.get("arguments", {})
                )
                result = prompt_result.model_dump()
            elif method == "ping":
                result = {}
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"}
                }
            
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}
            
        except Exception as e:
            logger.error("Error handling message", method=method, error=str(e))
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32603, "message": str(e)}
            }
    
    async def run(self):
        """Main loop for stdio transport."""
        self.running = True
        logger.info("Starting stdio transport", server=self.server.name)
        
        while self.running:
            message = await self.read_message()
            if message is None:
                break
            
            response = await self.handle_message(message)
            if response.get("id") is not None:
                self.write_message(response)
        
        logger.info("Stdio transport stopped")


def main():
    parser = argparse.ArgumentParser(description="Run MCP server via stdio")
    parser.add_argument(
        "server",
        choices=list(SERVERS.keys()),
        help="Server to run: infra, rag, or context"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    args = parser.parse_args()
    
    # Create server instance
    server_class = SERVERS[args.server]
    server = server_class()
    
    # Run stdio transport
    transport = StdioTransport(server)
    asyncio.run(transport.run())


if __name__ == "__main__":
    main()
