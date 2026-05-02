"""Base MCP server implementation using FastMCP."""

import hashlib
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

from app.core.config import settings
from app.core.logging import logger
from app.models.schemas import (
    PromptDefinition,
    PromptGetResponse,
    ResourceDefinition,
    ResourceReadResponse,
    ServerInfo,
    ToolCallResponse,
    ToolDefinition,
    ToolInputSchema,
)


class BaseMCPServer(ABC):
    """Base class for MCP servers."""

    def __init__(
        self,
        name: str,
        version: str = "0.1.0",
        description: Optional[str] = None,
    ):
        self.name = name
        self.version = version
        self.description = description or f"{name} MCP Server"
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._resources: Dict[str, Dict[str, Any]] = {}
        self._prompts: Dict[str, Dict[str, Any]] = {}

    def get_server_info(self) -> ServerInfo:
        """Get server information."""
        return ServerInfo(
            name=self.name,
            version=self.version,
            protocol_version="2024-11-05",
            capabilities={
                "tools": {"listChanged": True} if self._tools else {},
                "resources": {"subscribe": False, "listChanged": True} if self._resources else {},
                "prompts": {"listChanged": True} if self._prompts else {},
            },
        )

    def register_tool(
        self,
        name: str,
        description: str,
        handler: Callable,
        input_schema: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Register a tool with the server."""
        self._tools[name] = {
            "name": name,
            "description": description,
            "handler": handler,
            "input_schema": input_schema or {"type": "object", "properties": {}},
        }
        logger.info(f"Registered tool: {name}", server=self.name)

    def register_resource(
        self,
        uri: str,
        name: str,
        handler: Callable,
        description: Optional[str] = None,
        mime_type: Optional[str] = None,
    ) -> None:
        """Register a resource with the server."""
        self._resources[uri] = {
            "uri": uri,
            "name": name,
            "description": description,
            "mime_type": mime_type,
            "handler": handler,
        }
        logger.info(f"Registered resource: {uri}", server=self.name)

    def register_prompt(
        self,
        name: str,
        handler: Callable,
        description: Optional[str] = None,
        arguments: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Register a prompt with the server."""
        self._prompts[name] = {
            "name": name,
            "description": description,
            "arguments": arguments or [],
            "handler": handler,
        }
        logger.info(f"Registered prompt: {name}", server=self.name)

    def list_tools(self) -> List[ToolDefinition]:
        """List all registered tools."""
        return [
            ToolDefinition(
                name=tool["name"],
                description=tool["description"],
                inputSchema=ToolInputSchema(**tool["input_schema"]),
                server_id=self.name,
            )
            for tool in self._tools.values()
        ]

    def list_resources(self) -> List[ResourceDefinition]:
        """List all registered resources."""
        return [
            ResourceDefinition(
                uri=res["uri"],
                name=res["name"],
                description=res["description"],
                mimeType=res["mime_type"],
            )
            for res in self._resources.values()
        ]

    def list_prompts(self) -> List[PromptDefinition]:
        """List all registered prompts."""
        return [
            PromptDefinition(
                name=prompt["name"],
                description=prompt["description"],
                arguments=prompt["arguments"],
            )
            for prompt in self._prompts.values()
        ]

    async def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        user_id: Optional[str] = None,
    ) -> ToolCallResponse:
        """Call a registered tool."""
        if name not in self._tools:
            return ToolCallResponse(
                content=[{"type": "text", "text": f"Tool not found: {name}"}],
                isError=True,
            )

        tool = self._tools[name]
        start_time = time.time()
        params_hash = hashlib.md5(str(arguments).encode()).hexdigest()[:8]

        try:
            handler = tool["handler"]
            result = await handler(**arguments) if callable(handler) else handler

            latency_ms = (time.time() - start_time) * 1000
            logger.tool_call(
                tool_id=name,
                server_id=self.name,
                params_hash=params_hash,
                outcome="ok",
                latency_ms=latency_ms,
            )

            if isinstance(result, str):
                return ToolCallResponse(content=[{"type": "text", "text": result}])
            elif isinstance(result, dict):
                return ToolCallResponse(content=[result])
            elif isinstance(result, list):
                return ToolCallResponse(content=result)
            else:
                return ToolCallResponse(content=[{"type": "text", "text": str(result)}])

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            logger.tool_call(
                tool_id=name,
                server_id=self.name,
                params_hash=params_hash,
                outcome="error",
                latency_ms=latency_ms,
                error=str(e),
            )
            return ToolCallResponse(
                content=[{"type": "text", "text": f"Error: {str(e)}"}],
                isError=True,
            )

    async def read_resource(self, uri: str) -> ResourceReadResponse:
        """Read a registered resource."""
        if uri not in self._resources:
            return ResourceReadResponse(
                contents=[{"uri": uri, "text": f"Resource not found: {uri}"}]
            )

        resource = self._resources[uri]
        try:
            handler = resource["handler"]
            result = await handler() if callable(handler) else handler

            if isinstance(result, str):
                return ResourceReadResponse(
                    contents=[{
                        "uri": uri,
                        "mimeType": resource["mime_type"] or "text/plain",
                        "text": result,
                    }]
                )
            elif isinstance(result, dict):
                return ResourceReadResponse(contents=[result])
            else:
                return ResourceReadResponse(
                    contents=[{"uri": uri, "text": str(result)}]
                )

        except Exception as e:
            logger.error(f"Resource read error: {e}", uri=uri)
            return ResourceReadResponse(
                contents=[{"uri": uri, "text": f"Error: {str(e)}"}]
            )

    async def get_prompt(
        self,
        name: str,
        arguments: Dict[str, Any],
    ) -> PromptGetResponse:
        """Get a registered prompt."""
        if name not in self._prompts:
            return PromptGetResponse(
                messages=[{"role": "user", "content": f"Prompt not found: {name}"}]
            )

        prompt = self._prompts[name]
        try:
            handler = prompt["handler"]
            result = await handler(**arguments) if callable(handler) else handler

            if isinstance(result, list):
                return PromptGetResponse(
                    description=prompt["description"],
                    messages=result,
                )
            elif isinstance(result, str):
                return PromptGetResponse(
                    description=prompt["description"],
                    messages=[{"role": "user", "content": {"type": "text", "text": result}}],
                )
            else:
                return PromptGetResponse(
                    description=prompt["description"],
                    messages=[{"role": "user", "content": {"type": "text", "text": str(result)}}],
                )

        except Exception as e:
            logger.error(f"Prompt get error: {e}", name=name)
            return PromptGetResponse(
                messages=[{"role": "user", "content": {"type": "text", "text": f"Error: {str(e)}"}}]
            )

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the server and register tools/resources/prompts."""
        pass
