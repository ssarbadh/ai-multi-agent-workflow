"""
Sessions API - CRUD operations for chat sessions.
Per HLD: REST for sessions/messages CRUD, SSE for streaming.
"""

import logging
import uuid
import asyncio
import json
from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc

from app.core.database import get_db
from app.core.redis_client import get_redis
from app.models.models import Session, Message, Run, RunStatus, RequestType
from app.agents.router_agent import RouterAgent
from app.agents.sr_cr_agent import ServiceChangeRequestAgent
from app.agents.provisioner_agent import ProvisionerAgent
from app.agents.incident_agent import IncidentAgent
from app.agents.telemetry_agent import TelemetryAgent
from app.agents.decision_agent import DecisionAgent
from app.agents.remediator_agent import RemediatorAgent
from app.agents.devops_agent import DevOpsAgent
from app.services.rag_client import RAGClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sessions", tags=["sessions"])


# ===================================
# Pydantic Models
# ===================================

class SessionCreate(BaseModel):
    """Request model for creating a session."""
    title: Optional[str] = Field(None, max_length=200)
    type: Optional[str] = Field("service-request", description="Session type: service-request, change-request, incident, problem")


class SessionResponse(BaseModel):
    """Response model for session."""
    id: str
    title: str
    status: str
    type: str
    snow_ticket_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    closed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class MessageCreate(BaseModel):
    """Request model for sending a message."""
    content: str = Field(..., min_length=1, max_length=10000)


class MessageResponse(BaseModel):
    """Response model for message."""
    id: str
    session_id: str
    run_id: Optional[str] = None
    role: str
    content: str
    agent_type: Optional[str] = None  # NEW: conversational, devops, cloudops, sre
    parent_message_id: Optional[str] = None  # NEW: Link to user message
    confidentiality_score: Optional[float] = None
    confidentiality_label: Optional[str] = None
    metadata: Optional[dict] = None  # NEW: Additional metadata
    created_at: datetime

    class Config:
        from_attributes = True
        # Map the extra_metadata attribute to metadata field
        populate_by_name = True
    
    @classmethod
    def model_validate(cls, obj):
        """Custom validation to handle extra_metadata -> metadata mapping."""
        if hasattr(obj, 'extra_metadata'):
            # Create a dict with all attributes
            data = {
                'id': obj.id,
                'session_id': obj.session_id,
                'run_id': obj.run_id,
                'role': obj.role,
                'content': obj.content,
                'agent_type': obj.agent_type,
                'parent_message_id': obj.parent_message_id,
                'confidentiality_score': obj.confidentiality_score,
                'confidentiality_label': obj.confidentiality_label,
                'metadata': obj.extra_metadata,  # Map extra_metadata to metadata
                'created_at': obj.created_at
            }
            return cls(**data)
        return super().model_validate(obj)


class SendMessageResponse(BaseModel):
    """Response model for sending a message."""
    run_id: str
    message: MessageResponse


class FeedbackCreate(BaseModel):
    """Request model for message feedback."""
    message_id: str
    feedback_type: str = Field(..., description="'up' or 'down'")
    comment: Optional[str] = None
    sensitivity_flag: Optional[bool] = False


# ===================================
# In-Memory Storage (DEPRECATED - now using database)
# ===================================

# REMOVED: _sessions and _messages dicts
# Now using database models: Session and Message


# ===================================
# Agent Processing (Background Task)
# ===================================

# Store for pending events (run_id -> list of events)
_pending_events: dict = {}


# ===================================
# Helper Functions
# ===================================

def get_pending_events(run_id: str) -> list:
    """Get pending events for a run (for SSE replay)."""
    events = _pending_events.get(run_id, [])
    logger.info(f"Retrieved {len(events)} pending events for run {run_id}")
    return events


async def publish_vm_event(redis_client, execution_id: str, event_type: str, data: dict):
    """Publish event to VM console SSE channel."""
    channel = f"vm:{execution_id}:events"
    event = {"event": event_type, "data": data}
    try:
        await redis_client.publish(channel, json.dumps(event))
    except Exception as e:
        logger.error(f"Failed to publish VM event: {e}")


async def process_agent_response(
    run_id: str,
    session_id: str,
    user_message: str,
    redis_client
):
    """
    Process user message through the orchestrator service.
    
    This function delegates all processing to the orchestrator service which handles:
    - Intent detection (conversational vs devops vs SR/CR)
    - Routing to appropriate agent
    - Workflow execution
    - Event streaming
    """
    from app.services.orchestrator import orchestrator_service
    
    try:
        # Delegate to orchestrator service
        # The orchestrator will handle all routing, intent detection, and execution
        await orchestrator_service.start_run(run_id, user_message)
        
        logger.info(f"Delegated run {run_id} to orchestrator service")
        
    except Exception as e:
        logger.error(f"Error delegating to orchestrator: {e}", exc_info=True)
        # Emit error event
        channel = f"run:{run_id}:events"
        error_event = {
            "event": "error",
            "data": {"error": str(e), "type": type(e).__name__}
        }
        try:
            await redis_client.publish(channel, json.dumps(error_event))
            logger.info(f"Published error event to {channel}")
        except Exception as pub_error:
            logger.error(f"Failed to publish error event: {pub_error}")


@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(
    request: SessionCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create a new chat session."""
    from app.services.context_client import context_client
    
    session_id = f"session_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow()
    
    session = Session(
        id=session_id,
        title=request.title or "New Session",
        status="active",
        type=request.type or "service-request",
        snow_ticket_id=None,
        created_at=now,
        updated_at=now,
        closed_at=None,
    )
    
    db.add(session)
    await db.commit()
    await db.refresh(session)
    
    logger.info(f"Created session: {session_id}")
    
    # Add session to context graph (non-blocking)
    try:
        await context_client.add_session_to_graph(
            session_id=session_id,
            user_id="system",  # Will be updated when auth is implemented
            title=session.title,
            metadata={
                "type": session.type,
                "status": session.status
            }
        )
        logger.info(f"Added session {session_id} to context graph")
    except Exception as e:
        logger.warning(f"Failed to add session to context graph: {e}")
    
    return SessionResponse.model_validate(session)


@router.get("", response_model=List[SessionResponse])
async def list_sessions(
    status: Optional[str] = Query(None, description="Filter by status"),
    type: Optional[str] = Query(None, description="Filter by type"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    """List all sessions with optional filters."""
    query = select(Session).order_by(desc(Session.created_at))
    
    # Apply filters
    if status:
        query = query.where(Session.status == status)
    if type:
        query = query.where(Session.type == type)
    
    # Apply pagination
    query = query.limit(limit).offset(offset)
    
    result = await db.execute(query)
    sessions = result.scalars().all()
    
    return [SessionResponse.model_validate(s) for s in sessions]


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get session by ID."""
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return SessionResponse.model_validate(session)


@router.post("/{session_id}/close", response_model=SessionResponse)
async def close_session(
    session_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Close a session."""
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if session.status == "closed":
        raise HTTPException(status_code=400, detail="Session already closed")
    
    now = datetime.utcnow()
    session.status = "closed"
    session.closed_at = now
    session.updated_at = now
    
    await db.commit()
    await db.refresh(session)
    
    logger.info(f"Closed session: {session_id}")
    
    return SessionResponse.model_validate(session)


# ===================================
# Message Endpoints
# ===================================

@router.get("/{session_id}/messages", response_model=List[MessageResponse])
async def get_messages(
    session_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    """Get messages for a session."""
    # Verify session exists
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Get messages
    query = (
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at)
        .limit(limit)
        .offset(offset)
    )
    
    result = await db.execute(query)
    messages = result.scalars().all()
    
    return [MessageResponse.model_validate(m) for m in messages]


@router.post("/{session_id}/messages", response_model=SendMessageResponse)
async def send_message(
    session_id: str,
    request: MessageCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis)
):
    """
    Send a message to start agent processing.
    Returns run_id for SSE streaming.
    """
    from app.services.context_client import context_client
    
    # Get session
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if session.status == "closed":
        raise HTTPException(status_code=400, detail="Cannot send message to closed session")

    print("Hello i am here",session_id,session)
    
    # Create user message
    message_id = f"msg_{uuid.uuid4().hex[:12]}"
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow()
    
    user_message = Message(
        id=message_id,
        session_id=session_id,
        run_id=run_id,
        role="user",
        content=request.content,
        confidentiality_score=None,
        confidentiality_label=None,
        created_at=now,
    )
    
    db.add(user_message)
    
    # Create Run record for orchestrator
    run = Run(
        id=run_id,
        session_id=session_id,
        user_id="system",  # Default user - will be updated by auth middleware if available
        request_type=RequestType.SERVICE_REQUEST,  # Default - will be updated by orchestrator
        status=RunStatus.PENDING,
        title=request.content[:100],
        description=None,
        priority="medium",
        routed_to=None,
        routing_confidence=None,
        created_at=now,
        updated_at=now
    )
    
    db.add(run)
    
    # Update session
    session.updated_at = now
    if session.title == "New Session":
        # Use first message as title
        session.title = request.content[:100] + ("..." if len(request.content) > 100 else "")
    
    await db.commit()
    await db.refresh(user_message)
    
    logger.info(f"Message sent in session {session_id}, run_id: {run_id}")
    
    # Add message to context graph (non-blocking)
    try:
        await context_client.add_message_to_graph(
            message_id=message_id,
            session_id=session_id,
            role="user",
            content=request.content,
            metadata={
                "run_id": run_id,
                "session_type": session.type
            }
        )
        logger.info(f"Added message {message_id} to context graph")
    except Exception as e:
        logger.warning(f"Failed to add message to context graph: {e}")
    
    # Start agent processing in background
    background_tasks.add_task(
        process_agent_response,
        run_id,
        session_id,
        request.content,
        redis
    )
    
    return SendMessageResponse(
        run_id=run_id,
        message=MessageResponse.model_validate(user_message)
    )


# ===================================
# Form Response Endpoint
# ===================================

class FormResponseRequest(BaseModel):
    """Request model for form response."""
    form_id: str
    run_id: str
    values: Dict[str, Any]


@router.post("/{session_id}/form-response", status_code=200)
async def submit_form_response(
    session_id: str,
    request: FormResponseRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis)
):
    """
    Handle form response submission.
    Resumes agent execution with the provided form values.
    """
    logger.info(f"Received form response for run {request.run_id}: {request.form_id}")
    
    # Verify session exists
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Verify run exists
    result = await db.execute(select(Run).where(Run.id == request.run_id))
    run = result.scalar_one_or_none()
    
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    
    # Publish form response event to Redis for agent to consume
    channel = f"run:{request.run_id}:events"
    event_data = {
        "event": "form_response",
        "data": {
            "form_id": request.form_id,
            "values": request.values
        },
        "timestamp": datetime.utcnow().isoformat()
    }
    
    await redis.publish(channel, json.dumps(event_data))
    logger.info(f"Published form_response event to {channel}")
    
    # Also store in Redis for agent to retrieve
    form_response_key = f"run:{request.run_id}:form_response"
    await redis.setex(
        form_response_key,
        300,  # 5 minute TTL
        json.dumps(request.values)
    )
    
    return {"status": "success", "message": "Form response received"}


# ===================================
# Feedback Endpoint
# ===================================

@router.post("/feedback", status_code=201)
async def submit_feedback(
    request: FeedbackCreate,
    db: AsyncSession = Depends(get_db)
):
    """Submit feedback for a message."""
    # Find the message
    result = await db.execute(select(Message).where(Message.id == request.message_id))
    message = result.scalar_one_or_none()
    
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    
    # Store feedback (in production, save to database)
    logger.info(f"Feedback received for message {request.message_id}: {request.feedback_type}")
    
    return {"status": "success", "message_id": request.message_id}


# ===================================
# Delete Session Endpoint (NEW)
# ===================================

@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis)
):
    """
    Delete a session and all associated data.
    
    Cascades to:
    - Messages
    - Runs
    - Approvals
    - VM Executions
    - Tool Calls
    
    Also cleans up:
    - Redis session cache
    - Redis SSE channels
    """
    # Get session
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Clean up Redis state
    try:
        # Delete session cache
        await redis.delete(f"session:{session_id}:state")
        await redis.delete(f"session:{session_id}:cache")
        
        # Clean up any pending events for runs in this session
        runs_result = await db.execute(
            select(Run).where(Run.session_id == session_id)
        )
        runs = runs_result.scalars().all()
        for run in runs:
            await redis.delete(f"run:{run.id}:events")
            
        logger.info(f"Cleaned up Redis state for session: {session_id}")
    except Exception as e:
        logger.warning(f"Failed to clean up Redis state: {e}")
    
    # Delete session (cascade will handle related records)
    await db.delete(session)
    await db.commit()
    
    logger.info(f"Deleted session: {session_id}")
    
    # Return 204 No Content
    from fastapi.responses import Response
    return Response(status_code=204)
