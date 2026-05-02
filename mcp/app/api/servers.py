"""Server management endpoints for MCP service."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import MCPUser, PermissionChecker, get_current_user
from app.models.schemas import RegisteredServer, ServerStatus
from app.services.server_registry import server_registry

router = APIRouter(prefix="/servers", tags=["Servers"])


@router.get("", response_model=List[RegisteredServer])
async def list_servers(
    status_filter: Optional[ServerStatus] = None,
    user: MCPUser = Depends(get_current_user),
) -> List[RegisteredServer]:
    """List all registered MCP servers."""
    servers = server_registry.list_servers()

    if status_filter:
        servers = [s for s in servers if s.status == status_filter]

    return servers


@router.get("/{server_id}", response_model=RegisteredServer)
async def get_server(
    server_id: str,
    user: MCPUser = Depends(get_current_user),
) -> RegisteredServer:
    """Get a specific server by ID."""
    server = server_registry.get_registered(server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server not found: {server_id}",
        )
    return server


@router.get("/{server_id}/tools")
async def list_server_tools(
    server_id: str,
    user: MCPUser = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """List tools for a specific server."""
    server = server_registry.get_server(server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server not found: {server_id}",
        )
    return [t.model_dump() for t in server.list_tools()]


@router.get("/{server_id}/resources")
async def list_server_resources(
    server_id: str,
    user: MCPUser = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """List resources for a specific server."""
    server = server_registry.get_server(server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server not found: {server_id}",
        )
    return [r.model_dump() for r in server.list_resources()]


@router.get("/{server_id}/prompts")
async def list_server_prompts(
    server_id: str,
    user: MCPUser = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """List prompts for a specific server."""
    server = server_registry.get_server(server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server not found: {server_id}",
        )
    return [p.model_dump() for p in server.list_prompts()]


@router.get("/{server_id}/health")
async def check_server_health(
    server_id: str,
    user: MCPUser = Depends(get_current_user),
) -> Dict[str, Any]:
    """Check health of a specific server."""
    registered = server_registry.get_registered(server_id)
    if not registered:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server not found: {server_id}",
        )

    return {
        "server_id": server_id,
        "status": registered.status.value,
        "last_health_check": registered.last_health_check.isoformat() if registered.last_health_check else None,
        "tools_count": len(registered.tools),
        "resources_count": len(registered.resources),
    }
