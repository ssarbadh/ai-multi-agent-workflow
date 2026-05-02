"""SSE transport endpoints for MCP service."""

import asyncio
import json
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from app.core.config import settings
from app.core.logging import logger
from app.core.security import MCPUser, get_current_user_optional
from app.services.server_registry import server_registry
from app.services.session_manager import session_manager

router = APIRouter(prefix="/sse", tags=["SSE Transport"])


async def mcp_event_generator(
    session_id: str,
    server_id: str,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Generate MCP events for SSE stream."""
    # Send server info on connect
    server = server_registry.get_registered(server_id)
    if server:
        yield {
            "event": "server_info",
            "data": json.dumps({
                "name": server.name,
                "version": settings.MCP_SERVER_VERSION,
                "protocol_version": "2024-11-05",
                "capabilities": {
                    "tools": {"listChanged": True},
                    "resources": {"subscribe": False, "listChanged": True},
                    "prompts": {"listChanged": True},
                },
            }),
        }

    # Send tools list
    if server:
        tools = [t.model_dump() for t in server.tools]
        yield {
            "event": "tools_list",
            "data": json.dumps({"tools": tools}),
        }

    # Keepalive loop
    while True:
        await asyncio.sleep(15)

        # Check if session is still active
        session = await session_manager.get_session(session_id)
        if not session or session.status != "active":
            yield {
                "event": "session_closed",
                "data": json.dumps({"session_id": session_id}),
            }
            break

        # Send keepalive
        yield {
            "event": "keepalive",
            "data": json.dumps({"session_id": session_id}),
        }


@router.get("/{server_id}")
async def sse_connect(
    server_id: str,
    request: Request,
    session_id: Optional[str] = None,
    user: Optional[MCPUser] = Depends(get_current_user_optional),
) -> EventSourceResponse:
    """Connect to MCP server via SSE transport."""
    # Verify server exists
    server = server_registry.get_server(server_id)
    if not server:
        return EventSourceResponse(
            content=iter([{
                "event": "error",
                "data": json.dumps({"error": f"Server not found: {server_id}"}),
            }])
        )

    # Create or get session
    if not session_id:
        session = await session_manager.create_session(
            server_id=server_id,
            client_id=user.id if user else None,
            tenant_id=user.tenant_id if user else None,
        )
        session_id = session.session_id

    logger.session_event(session_id, "sse_connected", server_id=server_id)

    return EventSourceResponse(
        mcp_event_generator(session_id, server_id),
        media_type="text/event-stream",
    )


@router.get("/{server_id}/tools")
async def sse_tools_stream(
    server_id: str,
    request: Request,
) -> EventSourceResponse:
    """Stream tools list updates via SSE."""
    async def tools_generator() -> AsyncGenerator[Dict[str, Any], None]:
        server = server_registry.get_server(server_id)
        if not server:
            yield {
                "event": "error",
                "data": json.dumps({"error": f"Server not found: {server_id}"}),
            }
            return

        # Send initial tools list
        tools = [t.model_dump() for t in server.list_tools()]
        yield {
            "event": "tools_list",
            "data": json.dumps({"tools": tools}),
        }

        # Keepalive
        while True:
            await asyncio.sleep(30)
            yield {
                "event": "keepalive",
                "data": json.dumps({}),
            }

    return EventSourceResponse(
        tools_generator(),
        media_type="text/event-stream",
    )
