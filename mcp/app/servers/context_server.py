"""Context Management MCP server - tools for sessions, memory, prompts."""

from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.core.logging import logger
from app.servers.base import BaseMCPServer


class ContextMCPServer(BaseMCPServer):
    """MCP server exposing context management tools."""

    def __init__(self):
        super().__init__(
            name="context-server",
            version="0.1.0",
            description="Context management tools for sessions, memory, and prompts",
        )
        self._http_client: Optional[httpx.AsyncClient] = None

    async def initialize(self) -> None:
        """Initialize and register context tools."""
        self._http_client = httpx.AsyncClient(timeout=30.0)

        # Session tools
        self.register_tool(
            name="context_create_session",
            description="Create a new context session",
            handler=self._create_session,
            input_schema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "User ID"},
                    "metadata": {"type": "object", "description": "Session metadata"},
                },
                "required": ["user_id"],
            },
        )

        self.register_tool(
            name="context_get_session",
            description="Get session details",
            handler=self._get_session,
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID"},
                },
                "required": ["session_id"],
            },
        )

        # Memory tools
        self.register_tool(
            name="context_get_memory",
            description="Get short-term and long-term memory for a session",
            handler=self._get_memory,
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID"},
                    "include_ltm": {"type": "boolean", "description": "Include long-term memory", "default": True},
                },
                "required": ["session_id"],
            },
        )

        self.register_tool(
            name="context_add_memory",
            description="Add an entry to session memory",
            handler=self._add_memory,
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID"},
                    "content": {"type": "string", "description": "Memory content"},
                    "memory_type": {"type": "string", "enum": ["stm", "ltm"], "default": "stm"},
                    "metadata": {"type": "object", "description": "Memory metadata"},
                },
                "required": ["session_id", "content"],
            },
        )

        # Prompt tools
        self.register_tool(
            name="context_get_prompt",
            description="Get a prompt template by name and version",
            handler=self._get_prompt,
            input_schema={
                "type": "object",
                "properties": {
                    "prompt_name": {"type": "string", "description": "Prompt name"},
                    "version": {"type": "string", "description": "Prompt version"},
                    "channel": {"type": "string", "enum": ["dev", "canary", "prod"], "default": "prod"},
                },
                "required": ["prompt_name"],
            },
        )

        # Feedback tools
        self.register_tool(
            name="context_submit_feedback",
            description="Submit feedback for a message",
            handler=self._submit_feedback,
            input_schema={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "Message ID"},
                    "is_positive": {"type": "boolean", "description": "Positive feedback"},
                    "comment": {"type": "string", "description": "Optional comment"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Feedback tags"},
                },
                "required": ["message_id", "is_positive"],
            },
        )

        # Register resources
        self.register_resource(
            uri="context://prompts",
            name="Available Prompts",
            handler=self._list_prompts_resource,
            description="List of available prompt templates",
            mime_type="application/json",
        )

        logger.info("Context MCP server initialized")

    async def _create_session(
        self,
        user_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a new session."""
        try:
            response = await self._http_client.post(
                f"{settings.CONTEXT_MANAGEMENT_URL}/api/v1/sessions",
                json={"user_id": user_id, "metadata": metadata or {}},
            )
            if response.status_code in (200, 201):
                data = response.json()
                return {"type": "text", "text": f"Session created: {data.get('session_id', 'unknown')}"}
            return {"type": "text", "text": f"Error: {response.status_code}"}
        except Exception as e:
            return {"type": "text", "text": f"Context service unavailable: {str(e)}"}

    async def _get_session(self, session_id: str) -> Dict[str, Any]:
        """Get session details."""
        try:
            response = await self._http_client.get(
                f"{settings.CONTEXT_MANAGEMENT_URL}/api/v1/sessions/{session_id}"
            )
            if response.status_code == 200:
                return {"type": "text", "text": str(response.json())}
            return {"type": "text", "text": f"Session not found: {session_id}"}
        except Exception as e:
            return {"type": "text", "text": f"Context service unavailable: {str(e)}"}

    async def _get_memory(
        self,
        session_id: str,
        include_ltm: bool = True,
    ) -> Dict[str, Any]:
        """Get session memory."""
        try:
            response = await self._http_client.get(
                f"{settings.CONTEXT_MANAGEMENT_URL}/api/v1/memory/{session_id}",
                params={"include_ltm": include_ltm},
            )
            if response.status_code == 200:
                data = response.json()
                stm = data.get("stm", [])
                ltm = data.get("ltm", [])
                result = f"**Short-term Memory ({len(stm)} items):**\n"
                for item in stm[:5]:
                    result += f"- {item.get('content', '')[:100]}...\n"
                if include_ltm:
                    result += f"\n**Long-term Memory ({len(ltm)} items):**\n"
                    for item in ltm[:5]:
                        result += f"- {item.get('content', '')[:100]}...\n"
                return {"type": "text", "text": result}
            return {"type": "text", "text": f"Memory not found for session: {session_id}"}
        except Exception as e:
            return {"type": "text", "text": f"Context service unavailable: {str(e)}"}

    async def _add_memory(
        self,
        session_id: str,
        content: str,
        memory_type: str = "stm",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Add memory entry."""
        try:
            response = await self._http_client.post(
                f"{settings.CONTEXT_MANAGEMENT_URL}/api/v1/memory/{session_id}",
                json={
                    "content": content,
                    "memory_type": memory_type,
                    "metadata": metadata or {},
                },
            )
            if response.status_code in (200, 201):
                return {"type": "text", "text": f"Memory added to {memory_type}"}
            return {"type": "text", "text": f"Error: {response.status_code}"}
        except Exception as e:
            return {"type": "text", "text": f"Context service unavailable: {str(e)}"}

    async def _get_prompt(
        self,
        prompt_name: str,
        version: Optional[str] = None,
        channel: str = "prod",
    ) -> Dict[str, Any]:
        """Get prompt template."""
        try:
            response = await self._http_client.get(
                f"{settings.CONTEXT_MANAGEMENT_URL}/api/v1/prompts/{prompt_name}",
                params={"version": version, "channel": channel},
            )
            if response.status_code == 200:
                data = response.json()
                return {"type": "text", "text": data.get("template", "No template found")}
            return {"type": "text", "text": f"Prompt not found: {prompt_name}"}
        except Exception as e:
            return {"type": "text", "text": f"Context service unavailable: {str(e)}"}

    async def _submit_feedback(
        self,
        message_id: str,
        is_positive: bool,
        comment: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Submit feedback."""
        try:
            response = await self._http_client.post(
                f"{settings.CONTEXT_MANAGEMENT_URL}/api/v1/feedback",
                json={
                    "message_id": message_id,
                    "is_positive": is_positive,
                    "comment": comment,
                    "tags": tags or [],
                },
            )
            if response.status_code in (200, 201):
                return {"type": "text", "text": "Feedback submitted successfully"}
            return {"type": "text", "text": f"Error: {response.status_code}"}
        except Exception as e:
            return {"type": "text", "text": f"Context service unavailable: {str(e)}"}

    async def _list_prompts_resource(self) -> str:
        """List available prompts."""
        try:
            response = await self._http_client.get(
                f"{settings.CONTEXT_MANAGEMENT_URL}/api/v1/prompts"
            )
            if response.status_code == 200:
                return response.text
            return '{"prompts": []}'
        except Exception:
            return '{"prompts": []}'

    async def cleanup(self) -> None:
        """Cleanup resources."""
        if self._http_client:
            await self._http_client.aclose()
