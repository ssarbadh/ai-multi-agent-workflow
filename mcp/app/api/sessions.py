"""Session management endpoints for MCP service."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import MCPUser, get_current_user
from app.models.schemas import Session, SessionCreate, SessionList
from app.services.session_manager import session_manager

router = APIRouter(prefix="/sessions", tags=["Sessions"])


@router.post("", response_model=Session, status_code=status.HTTP_201_CREATED)
async def create_session(
    request: SessionCreate,
    user: MCPUser = Depends(get_current_user),
) -> Session:
    """Create a new MCP session."""
    session = await session_manager.create_session(
        server_id=request.server_id,
        client_id=request.client_id,
        tenant_id=user.tenant_id,
        metadata=request.metadata,
    )
    return session


@router.get("", response_model=SessionList)
async def list_sessions(
    server_id: Optional[str] = None,
    session_status: Optional[str] = None,
    user: MCPUser = Depends(get_current_user),
) -> SessionList:
    """List sessions."""
    return await session_manager.list_sessions(
        server_id=server_id,
        tenant_id=user.tenant_id,
        status=session_status,
    )


@router.get("/{session_id}", response_model=Session)
async def get_session(
    session_id: str,
    user: MCPUser = Depends(get_current_user),
) -> Session:
    """Get a session by ID."""
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )

    # Check tenant access
    if user.tenant_id and session.tenant_id != user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this session",
        )

    return session


@router.post("/{session_id}/close")
async def close_session(
    session_id: str,
    user: MCPUser = Depends(get_current_user),
) -> Dict[str, Any]:
    """Close a session."""
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )

    # Check tenant access
    if user.tenant_id and session.tenant_id != user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this session",
        )

    success = await session_manager.close_session(session_id)
    return {"success": success, "session_id": session_id}


@router.post("/{session_id}/activity")
async def update_session_activity(
    session_id: str,
    user: MCPUser = Depends(get_current_user),
) -> Dict[str, Any]:
    """Update session activity timestamp."""
    success = await session_manager.update_activity(session_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )
    return {"success": success, "session_id": session_id}
