"""Logs API endpoints for log ingestion and querying."""

from datetime import datetime, timezone, timedelta
from typing import List, Optional
from fastapi import APIRouter, Query, HTTPException

from app.models.schemas import LogEntry

router = APIRouter(prefix="/logs", tags=["logs"])


@router.post("/ingest")
async def ingest_logs(logs: List[LogEntry]):
    """
    Ingest structured logs from services.
    
    Log envelope per HLD:
    - ts, level, service, env, request_id, session_id, run_id, user_id, role, ip_hash
    """
    # In production, store in database or forward to log aggregator
    return {
        "status": "accepted",
        "count": len(logs),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/search")
async def search_logs(
    service: Optional[str] = Query(None, description="Filter by service"),
    level: Optional[str] = Query(None, description="Filter by log level"),
    run_id: Optional[str] = Query(None, description="Filter by run ID"),
    session_id: Optional[str] = Query(None, description="Filter by session ID"),
    start_time: Optional[datetime] = Query(None, description="Start time"),
    end_time: Optional[datetime] = Query(None, description="End time"),
    limit: int = Query(100, ge=1, le=1000, description="Max results")
):
    """
    Search logs with filters.
    
    Supports filtering by service, level, run_id, session_id, and time range.
    """
    # In production, query database or log aggregator
    return {
        "logs": [],
        "total": 0,
        "filters": {
            "service": service,
            "level": level,
            "run_id": run_id,
            "session_id": session_id,
            "start_time": start_time.isoformat() if start_time else None,
            "end_time": end_time.isoformat() if end_time else None,
        }
    }


@router.get("/run/{run_id}")
async def get_run_logs(
    run_id: str,
    include_tool_calls: bool = Query(True, description="Include tool call logs"),
    include_approvals: bool = Query(True, description="Include approval logs")
):
    """
    Get all logs for a specific agent run.
    
    Per HLD: Given a SNOW ticket, team can reconstruct full run via run_id and spans.
    """
    # In production, query logs by run_id
    return {
        "run_id": run_id,
        "logs": [],
        "tool_calls": [] if include_tool_calls else None,
        "approvals": [] if include_approvals else None
    }
