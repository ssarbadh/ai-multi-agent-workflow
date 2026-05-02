"""API endpoints for LangGraph-based SRE multi-agent incident workflow."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agents.sre_multi_agent import sre_multi_agent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/incident", tags=["sre-multi-agent"])


class IncidentAnalyzeRequest(BaseModel):
    """Request to start autonomous incident analysis."""

    user_id: str = Field(..., description="User initiating incident response")
    title: str = Field(..., description="Incident title")
    description: str = Field(..., description="Incident details")
    target_service: str = Field(default="unknown-service", description="Service impacted by incident")
    environment: Optional[str] = Field(
        default=None,
        description="Incident environment (e.g. dev, staging, prod)",
    )
    cloud_providers: Optional[List[str]] = Field(
        default=None,
        description="Cloud provider scope (e.g. aws, azure, gcp)",
    )
    resource_types: Optional[List[str]] = Field(
        default=None,
        description="Resource/runtime scope (e.g. kubernetes, vm, database, load_balancer, dns)",
    )
    regions: Optional[List[str]] = Field(
        default=None,
        description="Optional region scope list (e.g. us-east-1, europe-west1)",
    )
    vendors: Optional[List[str]] = Field(
        default=None,
        description="Infra/runtime vendors to scope web research (e.g. kubernetes, istio)",
    )
    clouds: Optional[List[str]] = Field(
        default=None,
        description="Cloud providers to check status against (e.g. aws, azure, gcp)",
    )
    region: Optional[str] = Field(
        default=None,
        description="Primary deployment region used for status correlation",
    )
    servicenow_incident_id: Optional[str] = Field(default=None, description="ServiceNow incident sys_id")
    auto_approve: Optional[bool] = Field(default=None, description="Optional immediate remediation approval")


class IncidentAnalyzeResponse(BaseModel):
    """Async workflow trigger response."""

    incident_id: str
    status: str
    message: str


class RemediationApprovalRequest(BaseModel):
    """Approval response payload."""

    approved: bool = Field(..., description="Whether remediation is approved")
    comment: Optional[str] = Field(default=None, description="Optional approval comment")


class PromptCatalogReloadResponse(BaseModel):
    """Response from prompt catalog reload endpoint."""

    status: str
    catalog_path: str
    prompt_count: int


class IncidentEventsResponse(BaseModel):
    """Incremental incident event feed payload."""

    incident_id: str
    status: str
    current_node: Optional[str]
    last_event_seq: int
    has_more: bool
    events: List[Dict[str, Any]]


@router.post("/analyze", response_model=IncidentAnalyzeResponse)
async def analyze_incident(request: IncidentAnalyzeRequest, background_tasks: BackgroundTasks):
    """Start multi-agent incident analysis workflow."""
    try:
        state = await sre_multi_agent.create_incident(request.model_dump())
        incident_id = state["incident_id"]
        background_tasks.add_task(sre_multi_agent.run_incident_workflow, incident_id)
        return IncidentAnalyzeResponse(
            incident_id=incident_id,
            status="accepted",
            message="Incident analysis started. Poll status endpoint for progress.",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed starting SRE multi-agent workflow: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{incident_id}/status")
async def get_incident_status(incident_id: str) -> Dict[str, Any]:
    """Get current incident workflow status and outputs."""
    status = await sre_multi_agent.get_incident_status(incident_id)
    if not status:
        raise HTTPException(status_code=404, detail="Incident not found")
    return status


@router.get("/{incident_id}/events", response_model=IncidentEventsResponse)
async def get_incident_events(
    incident_id: str,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> IncidentEventsResponse:
    """Return structured workflow events after the given sequence number."""
    payload = await sre_multi_agent.get_incident_events(incident_id, after_seq=after_seq, limit=limit)
    if not payload:
        raise HTTPException(status_code=404, detail="Incident not found")
    return IncidentEventsResponse(**payload)


@router.get("/{incident_id}/events/stream")
async def stream_incident_events(
    incident_id: str,
    after_seq: int = Query(default=0, ge=0),
    poll_interval_seconds: float = Query(default=1.0, ge=0.2, le=5.0),
    stop_on_waiting_approval: bool = Query(default=True),
):
    """SSE stream of incident workflow events."""

    async def _event_generator():
        cursor = after_seq
        terminal_event_seen = False
        approval_required_seen = False
        while True:
            payload = await sre_multi_agent.get_incident_events(incident_id, after_seq=cursor, limit=200)
            if not payload:
                error_event = {"type": "stream_error", "message": "Incident not found", "incident_id": incident_id}
                yield "event: stream_error\n"
                yield f"data: {json.dumps(error_event)}\n\n"
                break

            events = payload.get("events", [])
            for event in events:
                seq = int(event.get("seq", 0) or 0)
                if seq > cursor:
                    cursor = seq
                event_type = str(event.get("type", "")).strip().lower()
                if event_type in {"workflow_completed", "workflow_failed"}:
                    terminal_event_seen = True
                if event_type == "approval_required":
                    approval_required_seen = True
                yield f"event: {event.get('type', 'message')}\n"
                yield f"data: {json.dumps(event, default=str)}\n\n"

            status = payload.get("status")
            last_event_seq = int(payload.get("last_event_seq", cursor) or cursor)
            # Exit only on explicit lifecycle events to avoid breaking on transient
            # operation_status values during long-running nodes.
            if terminal_event_seen and cursor >= last_event_seq:
                break
            if stop_on_waiting_approval and approval_required_seen and cursor >= last_event_seq:
                break
            if not events:
                # Keep SSE connections alive across long-running node execution.
                yield ": keepalive\n\n"
            await asyncio.sleep(poll_interval_seconds)

    return StreamingResponse(_event_generator(), media_type="text/event-stream")


@router.post("/{incident_id}/approve-remediation")
async def approve_remediation(incident_id: str, request: RemediationApprovalRequest) -> Dict[str, Any]:
    """
    Approve or reject remediation and resume paused workflow.

    This endpoint is the human-in-the-loop gate that unblocks execution.
    """
    try:
        state = await sre_multi_agent.approve_remediation(
            incident_id=incident_id,
            approved=request.approved,
            comment=request.comment,
        )
        return {
            "incident_id": incident_id,
            "status": state.get("operation_status"),
            "approved": request.approved,
            "current_node": state.get("current_node"),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed applying remediation approval: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/admin/prompts/reload", response_model=PromptCatalogReloadResponse)
async def reload_prompt_catalog() -> PromptCatalogReloadResponse:
    """Hot-reload SRE multi-agent prompt catalog from disk."""
    try:
        result = sre_multi_agent.reload_prompt_catalog()
        return PromptCatalogReloadResponse(**result)
    except Exception as exc:
        logger.exception("Failed reloading prompt catalog: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

