"""Graph load endpoint - triggers enrichment ingestion into Neo4j."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logging import logger
from app.ingestion.runner import run_enrichment_async

router = APIRouter(tags=["Graph"])


class GraphLoadRequest(BaseModel):
    """Request body for graph load endpoint."""

    services: Optional[List[str]] = Field(
        default=None,
        description="Service names to enrich. If empty, uses services from graph or defaults.",
    )
    use_simulated: bool = Field(
        default=True,
        description="Use simulated Prometheus/logs data when real sources unavailable.",
    )
    create_incident: bool = Field(
        default=False,
        description="Create a sample Incident node and link to anomalies/patterns.",
    )
    ingest_databases: bool = Field(
        default=True,
        description="Ingest Database nodes and (Service)-[:USES]->(Database).",
    )
    ingest_istio: bool = Field(
        default=True,
        description="Ingest Istio call graph (Service)-[:CALLS]->(Service|Database).",
    )


class GraphLoadResponse(BaseModel):
    """Response from graph load endpoint."""

    status: str
    anomalies_written: int
    error_patterns_written: int
    incidents_created: int
    databases_written: int
    istio_calls_written: int
    istio_call_edges_discovered: int = 0
    services_processed: List[str]
    errors: List[str]
    incident_id: Optional[str] = None


@router.post("/graph/load", response_model=GraphLoadResponse)
async def graph_load(request: GraphLoadRequest) -> GraphLoadResponse:
    """
    Trigger graph enrichment ingestion.

    Ingests runtime signals from Prometheus (anomalies) and logs (error patterns)
    into Neo4j, linking to existing Service/Pod nodes from Cartography.
    Does NOT duplicate infrastructure - only adds Anomaly, ErrorPattern, Incident.

    For Cartography (K8s/AWS infra sync): run separately via cron or
    `docker compose run cartography`.
    """
    if not getattr(settings, "GRAPH_MCP_ENABLED", False):
        raise HTTPException(
            status_code=503,
            detail="Graph MCP not enabled. Set GRAPH_MCP_ENABLED=true and configure Neo4j.",
        )
    if not getattr(settings, "GRAPH_MCP_NEO4J_URI", ""):
        raise HTTPException(
            status_code=503,
            detail="GRAPH_MCP_NEO4J_URI not configured.",
        )
    try:
        result = await run_enrichment_async(
            services=request.services,
            use_simulated=request.use_simulated,
            create_incident=request.create_incident,
            ingest_databases=request.ingest_databases,
            ingest_istio=request.ingest_istio,
        )
        return GraphLoadResponse(
            status="completed",
            anomalies_written=result.get("anomalies_written", 0),
            error_patterns_written=result.get("error_patterns_written", 0),
            incidents_created=result.get("incidents_created", 0),
            databases_written=result.get("databases_written", 0),
            istio_calls_written=result.get("istio_calls_written", 0),
            istio_call_edges_discovered=result.get("istio_call_edges_discovered", 0),
            services_processed=result.get("services_processed", []),
            errors=result.get("errors", []),
            incident_id=result.get("incident_id"),
        )
    except Exception as exc:
        logger.exception("Graph load failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
