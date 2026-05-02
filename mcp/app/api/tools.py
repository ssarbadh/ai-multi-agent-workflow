"""Tool endpoints for MCP service."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import MCPUser, check_tool_permission, get_current_user
from app.models.schemas import ToolCallRequest, ToolCallResponse, ToolDefinition
from app.services.gateway import gateway
from app.services.server_registry import server_registry

router = APIRouter(prefix="/tools", tags=["Tools"])


@router.get("", response_model=List[ToolDefinition])
async def list_tools(
    server_id: Optional[str] = None,
    user: MCPUser = Depends(get_current_user),
) -> List[ToolDefinition]:
    """List all available tools."""
    tools = await gateway.list_tools(server_id, user)
    return [ToolDefinition(**t) for t in tools]


@router.get("/{tool_name}")
async def get_tool(
    tool_name: str,
    user: MCPUser = Depends(get_current_user),
) -> Dict[str, Any]:
    """Get details of a specific tool."""
    result = server_registry.find_tool(tool_name)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool not found: {tool_name}",
        )

    server_id, server = result
    for tool in server.list_tools():
        if tool.name == tool_name:
            return tool.model_dump()

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Tool not found: {tool_name}",
    )


@router.post("/call", response_model=ToolCallResponse)
async def call_tool(
    request: ToolCallRequest,
    session_id: Optional[str] = None,
    user: MCPUser = Depends(get_current_user),
) -> ToolCallResponse:
    """Call a tool by name."""
    # Check permission
    if not check_tool_permission(user, request.name):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied for tool: {request.name}",
        )

    response = await gateway.route_tool_call(request, session_id, user)
    return response


@router.post("/{tool_name}/call", response_model=ToolCallResponse)
async def call_tool_by_name(
    tool_name: str,
    arguments: Dict[str, Any] = None,
    session_id: Optional[str] = None,
    user: MCPUser = Depends(get_current_user),
) -> ToolCallResponse:
    """Call a specific tool by name."""
    # Check permission
    if not check_tool_permission(user, tool_name):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied for tool: {tool_name}",
        )

    request = ToolCallRequest(name=tool_name, arguments=arguments or {})
    response = await gateway.route_tool_call(request, session_id, user)
    return response
