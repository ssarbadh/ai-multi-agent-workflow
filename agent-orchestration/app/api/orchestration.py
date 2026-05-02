"""Orchestration endpoints for starting and managing agent runs."""

import logging
import uuid
from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.models.models import Run, RunStatus
from app.models.schemas import OrchestrationRequest, RunResponse, StatsResponse
from app.services.orchestrator import orchestrator_service
from app.core.observability import get_metrics

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/orchestrate", response_model=RunResponse, status_code=202)
async def start_orchestration(
    request: OrchestrationRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Start a new agent orchestration run.
    
    This endpoint:
    1. Creates a new run record
    2. Starts the LangGraph orchestration asynchronously
    3. Returns the run ID immediately
    4. Client can stream progress via SSE endpoint
    """
    try:
        # Create run record
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        run = Run(
            id=run_id,
            session_id=request.session_id,
            user_id=request.user_id,
            request_type="service_request",  # Will be determined by router agent
            status=RunStatus.PENDING,
            title=request.message[:200],  # Truncate for title
            description=request.message,
            priority=request.priority,
            metadata=request.metadata or {},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        
        db.add(run)
        await db.commit()
        await db.refresh(run)
        
        # Start orchestration asynchronously
        await orchestrator_service.start_run(run_id, request.message, db)
        
        # Record metrics
        metrics = get_metrics()
        metrics.agent_runs_total.labels(
            agent_type="orchestrator",
            status="started"
        ).inc()
        
        logger.info(f"Started orchestration run: {run_id}")
        
        return RunResponse.model_validate(run)
        
    except Exception as e:
        logger.error(f"Failed to start orchestration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get run details by ID."""
    result = await db.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one_or_none()
    
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    
    return RunResponse.model_validate(run)


@router.get("/runs", response_model=List[RunResponse])
async def list_runs(
    session_id: str = Query(None, description="Filter by session ID"),
    user_id: str = Query(None, description="Filter by user ID"),
    status: RunStatus = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=100, description="Number of runs to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: AsyncSession = Depends(get_db)
):
    """List runs with optional filters."""
    query = select(Run).order_by(Run.created_at.desc())
    
    if session_id:
        query = query.where(Run.session_id == session_id)
    if user_id:
        query = query.where(Run.user_id == user_id)
    if status:
        query = query.where(Run.status == status)
    
    query = query.limit(limit).offset(offset)
    
    result = await db.execute(query)
    runs = result.scalars().all()
    
    return [RunResponse.model_validate(run) for run in runs]


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Cancel a running orchestration."""
    result = await db.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one_or_none()
    
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    
    if run.status not in [RunStatus.PENDING, RunStatus.RUNNING, RunStatus.WAITING_APPROVAL]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel run in status: {run.status}"
        )
    
    # Cancel the run
    await orchestrator_service.cancel_run(run_id, db)
    
    run.status = RunStatus.CANCELLED
    run.completed_at = datetime.utcnow()
    run.updated_at = datetime.utcnow()
    
    await db.commit()
    
    logger.info(f"Cancelled run: {run_id}")
    
    return {"status": "cancelled", "run_id": run_id}


@router.get("/stats", response_model=StatsResponse)
async def get_stats(db: AsyncSession = Depends(get_db)):
    """Get orchestration statistics."""
    
    # Total runs
    total_result = await db.execute(select(func.count(Run.id)))
    total_runs = total_result.scalar() or 0
    
    # Active runs
    active_result = await db.execute(
        select(func.count(Run.id)).where(
            Run.status.in_([RunStatus.RUNNING, RunStatus.PENDING])
        )
    )
    active_runs = active_result.scalar() or 0
    
    # Completed runs
    completed_result = await db.execute(
        select(func.count(Run.id)).where(Run.status == RunStatus.COMPLETED)
    )
    completed_runs = completed_result.scalar() or 0
    
    # Failed runs
    failed_result = await db.execute(
        select(func.count(Run.id)).where(Run.status == RunStatus.FAILED)
    )
    failed_runs = failed_result.scalar() or 0
    
    # Average run duration
    avg_duration_result = await db.execute(
        select(func.avg(Run.duration_seconds)).where(
            Run.status == RunStatus.COMPLETED
        )
    )
    avg_run_duration = avg_duration_result.scalar()
    
    return StatsResponse(
        total_runs=total_runs,
        active_runs=active_runs,
        completed_runs=completed_runs,
        failed_runs=failed_runs,
        pending_approvals=0,  # Will be implemented
        active_vm_executions=0,  # Will be implemented
        avg_run_duration_seconds=avg_run_duration,
        avg_approval_wait_time_seconds=None,
        tool_call_success_rate=None,
    )
