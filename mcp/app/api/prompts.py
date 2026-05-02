"""Prompt endpoints for MCP service."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends

from app.core.security import MCPUser, get_current_user
from app.models.schemas import PromptDefinition, PromptGetRequest, PromptGetResponse
from app.services.gateway import gateway

router = APIRouter(prefix="/prompts", tags=["Prompts"])


@router.get("", response_model=List[PromptDefinition])
async def list_prompts(
    server_id: Optional[str] = None,
    user: MCPUser = Depends(get_current_user),
) -> List[PromptDefinition]:
    """List all available prompts."""
    prompts = await gateway.list_prompts(server_id)
    return [PromptDefinition(**p) for p in prompts]


@router.post("/get")
async def get_prompt(
    request: PromptGetRequest,
    user: MCPUser = Depends(get_current_user),
) -> Dict[str, Any]:
    """Get a prompt by name with arguments."""
    return await gateway.get_prompt(request.name, request.arguments, user)


@router.get("/{prompt_name}")
async def get_prompt_by_name(
    prompt_name: str,
    user: MCPUser = Depends(get_current_user),
) -> Dict[str, Any]:
    """Get a prompt by name."""
    return await gateway.get_prompt(prompt_name, {}, user)
