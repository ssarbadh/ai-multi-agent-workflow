"""Metrics API endpoints."""

from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Query, HTTPException

from app.models.schemas import (
    AgentEvaluationMetrics, RAGEvaluationMetrics,
    SystemHealth, MetricEvent
)
from app.services.metrics_collector import metrics_collector
from app.services.agent_evaluator import agent_evaluator
from app.services.rag_evaluator import rag_evaluator

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/health", response_model=SystemHealth)
async def get_system_health():
    """Get health status of all AegisOps services."""
    return await metrics_collector.check_all_services()


@router.get("/agent/evaluation", response_model=AgentEvaluationMetrics)
async def get_agent_evaluation_metrics(
    period_hours: int = Query(24, ge=1, le=168, description="Evaluation period in hours"),
    agent_type: Optional[str] = Query(None, description="Filter by agent type")
):
    """
    Get agent evaluation metrics per HLD requirements.
    
    Includes:
    - Task/Outcome: Resolution rate, time to resolution, rollback rate, etc.
    - Interaction & Safety: User satisfaction, feedback utilization, safety incidents
    - Efficiency: Steps per resolution, tool success rate, human wait time
    """
    return await agent_evaluator.calculate_metrics(period_hours, agent_type)


@router.get("/rag/evaluation", response_model=RAGEvaluationMetrics)
async def get_rag_evaluation_metrics(
    period_hours: int = Query(24, ge=1, le=168, description="Evaluation period in hours")
):
    """
    Get RAG evaluation metrics per HLD requirements.
    
    Includes:
    - Retrieval Quality: Recall@k, Precision@k, MRR, nDCG@k
    - Generation Quality: Faithfulness, hallucination rate, answer relevance
    - Performance: Retrieval latency, end-to-end latency, index freshness
    """
    return await rag_evaluator.calculate_metrics(period_hours)


@router.post("/ingest")
async def ingest_metrics(metrics: List[MetricEvent]):
    """
    Ingest metrics from other services.
    
    Used by services to push metrics to observability service.
    """
    # In production, store in database and/or push to Prometheus
    return {
        "status": "accepted",
        "count": len(metrics),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.post("/agent-run")
async def record_agent_run(run_data: dict):
    """
    Record agent run metrics.
    
    Used by agent-orchestration to record run completion metrics.
    """
    # In production, store in database and/or push to Prometheus
    return {
        "status": "recorded",
        "run_id": run_data.get("run_id"),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/prometheus")
async def get_prometheus_metrics():
    """Get metrics in Prometheus text format."""
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    from fastapi.responses import Response
    
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )
