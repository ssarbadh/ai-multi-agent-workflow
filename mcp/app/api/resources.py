"""Resource endpoints for MCP service."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends

from app.core.security import MCPUser, get_current_user
from app.models.schemas import ResourceDefinition, ResourceReadResponse
from app.services.gateway import gateway

router = APIRouter(prefix="/resources", tags=["Resources"])


@router.get("", response_model=List[ResourceDefinition])
async def list_resources(
    server_id: Optional[str] = None,
    user: MCPUser = Depends(get_current_user),
) -> List[ResourceDefinition]:
    """List all available resources."""
    resources = await gateway.list_resources(server_id)
    return [ResourceDefinition(**r) for r in resources]


@router.get("/read")
async def read_resource(
    uri: str,
    user: MCPUser = Depends(get_current_user),
) -> Dict[str, Any]:
    """Read a resource by URI."""
    return await gateway.read_resource(uri, user)
