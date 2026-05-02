"""Approval and human-in-the-loop endpoints."""

import logging
from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.models import Approval, ApprovalStatus
from app.models.schemas import ApprovalResponse as ApprovalResponseReq, ApprovalResponseSchema
from app.services.approval_service import approval_service
from app.core.observability import get_metrics

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/approvals", response_model=List[ApprovalResponseSchema])
async def list_approvals(
    run_id: str = Query(None, description="Filter by run ID"),
    status: ApprovalStatus = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """List approval requests."""
    query = select(Approval).order_by(Approval.requested_at.desc())
    
    if run_id:
        query = query.where(Approval.run_id == run_id)
    if status:
        query = query.where(Approval.status == status)
    
    query = query.limit(limit)
    
    result = await db.execute(query)
    approvals = result.scalars().all()
    
    return [ApprovalResponseSchema.model_validate(a) for a in approvals]


@router.get("/approvals/{approval_id}", response_model=ApprovalResponseSchema)
async def get_approval(
    approval_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get approval details."""
    result = await db.execute(select(Approval).where(Approval.id == approval_id))
    approval = result.scalar_one_or_none()
    
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    
    return ApprovalResponseSchema.model_validate(approval)


@router.post("/approvals/{approval_id}/respond")
async def respond_to_approval(
    approval_id: str,
    response: ApprovalResponseReq,
    db: AsyncSession = Depends(get_db)
):
    """
    Respond to an approval request.
    
    For approval type: approved=True/False
    For password/input type: provide response text
    """
    result = await db.execute(select(Approval).where(Approval.id == approval_id))
    approval = result.scalar_one_or_none()
    
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    
    if approval.status != ApprovalStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Approval already {approval.status}"
        )
    
    # Update approval
    approval.status = ApprovalStatus.APPROVED if response.approved else ApprovalStatus.REJECTED
    approval.response = response.response
    approval.responded_at = datetime.utcnow()
    approval.wait_time_seconds = (
        approval.responded_at - approval.requested_at
    ).total_seconds()
    
    await db.commit()
    
    # Notify safety approval agent to unblock execution
    from app.agents.safety_approval_agent import safety_approval_agent
    safety_approval_agent.respond_to_approval(
        approval_id=approval_id,
        approved=response.approved,
        response=response.response,
        comment=None,
        approved_by="user"  # TODO: Get from auth context
    )
    
    # Notify orchestrator via approval service
    await approval_service.notify_approval_response(approval_id, response.approved, response.response)
    
    # Record metrics
    metrics = get_metrics()
    metrics.approvals_total.labels(
        approval_type=approval.approval_type,
        outcome="approved" if response.approved else "rejected"
    ).inc()
    metrics.approval_wait_time.labels(
        approval_type=approval.approval_type
    ).observe(approval.wait_time_seconds)
    
    logger.info(f"Approval {approval_id} responded: {approval.status}")
    
    return {"status": "success", "approval_id": approval_id}
