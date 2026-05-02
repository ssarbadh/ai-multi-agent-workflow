"""Dashboard API endpoints."""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import Dashboard
from app.services.dashboards import dashboard_service

router = APIRouter(prefix="/dashboards", tags=["dashboards"])


@router.get("/", response_model=List[Dashboard])
async def list_dashboards():
    """List all available dashboards."""
    return dashboard_service.list_dashboards()


@router.get("/{dashboard_id}", response_model=Dashboard)
async def get_dashboard(
    dashboard_id: str,
    time_range_hours: int = Query(24, ge=1, le=168, description="Time range in hours")
):
    """
    Get dashboard with populated data.
    
    Available dashboards per HLD:
    - executive: Resolution rate, time-to-resolution, escalations, CSAT, safety incidents
    - rag: Recall@k, faithfulness, latency, freshness, index size
    - serving: LLM tokens/s, p95 latency, GPU util, cache hit
    - graph: Runs by status, node latency heatmap, interrupts
    - pipelines: Ingest backlog, embedding throughput, failures
    - infra: API p95, DB p95, Redis hit/evictions, error budgets
    """
    dashboard = await dashboard_service.get_dashboard_data(dashboard_id, time_range_hours)
    if not dashboard:
        raise HTTPException(status_code=404, detail=f"Dashboard {dashboard_id} not found")
    return dashboard
