"""MCP Gateway - routes requests to appropriate servers."""

import hashlib
import time
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.core.logging import logger
from app.core.security import MCPUser, check_permission, check_tool_permission
from app.models.schemas import (
    GatewayConfig,
    GatewayRoute,
    ToolCallRequest,
    ToolCallResponse,
)
from app.services.server_registry import server_registry
from app.services.session_manager import session_manager


class MCPGateway:
    """Gateway for routing MCP requests."""

    def __init__(self):
        self._config = GatewayConfig()
        self._http_client: Optional[httpx.AsyncClient] = None

    async def initialize(self) -> None:
        """Initialize the gateway."""
        self._http_client = httpx.AsyncClient(timeout=self._config.default_timeout)
        logger.info("MCP Gateway initialized")

    async def shutdown(self) -> None:
        """Shutdown the gateway."""
        if self._http_client:
            await self._http_client.aclose()

    def configure(self, config: GatewayConfig) -> None:
        """Update gateway configuration."""
        self._config = config
        logger.info(f"Gateway configured with {len(config.routes)} routes")

    async def route_tool_call(
        self,
        request: ToolCallRequest,
        session_id: Optional[str] = None,
        user: Optional[MCPUser] = None,
    ) -> ToolCallResponse:
        """Route a tool call to the appropriate server."""
        start_time = time.time()
        request_hash = hashlib.md5(str(request.arguments).encode()).hexdigest()[:8]

        # Check permissions
        if user and not check_tool_permission(user, request.name):
            logger.gateway_route(
                request_id=request_hash,
                server_id="gateway",
                path=f"/tools/{request.name}",
                method="POST",
                status=403,
                latency_ms=0,
            )
            return ToolCallResponse(
                content=[{"type": "text", "text": f"Permission denied for tool: {request.name}"}],
                isError=True,
            )

        # Find the server that has this tool
        result = server_registry.find_tool(request.name)
        if not result:
            logger.gateway_route(
                request_id=request_hash,
                server_id="gateway",
                path=f"/tools/{request.name}",
                method="POST",
                status=404,
                latency_ms=0,
            )
            return ToolCallResponse(
                content=[{"type": "text", "text": f"Tool not found: {request.name}"}],
                isError=True,
            )

        server_id, server = result

        # Update session activity if provided
        if session_id:
            await session_manager.update_activity(session_id)

        # Call the tool
        try:
            response = await server.call_tool(
                request.name,
                request.arguments,
                user.id if user else None,
            )

            latency_ms = (time.time() - start_time) * 1000
            logger.gateway_route(
                request_id=request_hash,
                server_id=server_id,
                path=f"/tools/{request.name}",
                method="POST",
                status=200 if not response.isError else 500,
                latency_ms=latency_ms,
            )

            return response

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            logger.gateway_route(
                request_id=request_hash,
                server_id=server_id,
                path=f"/tools/{request.name}",
                method="POST",
                status=500,
                latency_ms=latency_ms,
                error=str(e),
            )
            return ToolCallResponse(
                content=[{"type": "text", "text": f"Error: {str(e)}"}],
                isError=True,
            )

    async def list_tools(
        self,
        server_id: Optional[str] = None,
        user: Optional[MCPUser] = None,
    ) -> List[Dict[str, Any]]:
        """List available tools, optionally filtered by server and permissions."""
        if server_id:
            server = server_registry.get_server(server_id)
            if not server:
                return []
            tools = server.list_tools()
        else:
            tools = server_registry.list_all_tools()

        # Listing and executing tools have different permissions.
        # Users with tools:list should be able to discover tools even if
        # they cannot execute all of them.
        if user:
            if not check_permission(user, "tools:list"):
                return []

        return [t.model_dump() for t in tools]

    async def list_resources(
        self,
        server_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List available resources."""
        if server_id:
            server = server_registry.get_server(server_id)
            if not server:
                return []
            resources = server.list_resources()
        else:
            resources = server_registry.list_all_resources()

        return [r.model_dump() for r in resources]

    async def list_prompts(
        self,
        server_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List available prompts."""
        if server_id:
            server = server_registry.get_server(server_id)
            if not server:
                return []
            prompts = server.list_prompts()
        else:
            prompts = server_registry.list_all_prompts()

        return [p.model_dump() for p in prompts]

    async def read_resource(
        self,
        uri: str,
        user: Optional[MCPUser] = None,
    ) -> Dict[str, Any]:
        """Read a resource by URI."""
        # Find server that has this resource
        for server in server_registry._servers.values():
            for resource in server.list_resources():
                if resource.uri == uri:
                    response = await server.read_resource(uri)
                    return response.model_dump()

        return {"contents": [{"uri": uri, "text": f"Resource not found: {uri}"}]}

    async def get_prompt(
        self,
        name: str,
        arguments: Dict[str, Any],
        user: Optional[MCPUser] = None,
    ) -> Dict[str, Any]:
        """Get a prompt by name."""
        # Find server that has this prompt
        for server in server_registry._servers.values():
            for prompt in server.list_prompts():
                if prompt.name == name:
                    response = await server.get_prompt(name, arguments)
                    return response.model_dump()

        return {"messages": [{"role": "user", "content": f"Prompt not found: {name}"}]}


# Global instance
gateway = MCPGateway()
