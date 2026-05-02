"""Health check endpoints for MCP service."""

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Response

from app.core.config import settings
from app.core.redis_client import redis_client
from app.models.schemas import HealthStatus
from app.services.server_registry import server_registry

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthStatus)
async def health_check() -> HealthStatus:
    """Basic health check."""
    return HealthStatus(
        status="healthy",
        service=settings.SERVICE_NAME,
        version=settings.VERSION,
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/ready")
async def readiness_check() -> Dict[str, Any]:
    """Readiness check - verifies all dependencies."""
    checks = {}

    # Check Redis
    try:
        if redis_client.client:
            await redis_client.client.ping()
            checks["redis"] = "ok"
        else:
            checks["redis"] = "not_connected"
    except Exception as e:
        checks["redis"] = f"error: {str(e)}"

    # Check servers
    servers = server_registry.list_servers()
    checks["servers"] = {
        "count": len(servers),
        "status": "ok" if servers else "no_servers",
    }

    # Overall status
    all_ok = all(
        v == "ok" or (isinstance(v, dict) and v.get("status") == "ok")
        for v in checks.values()
    )

    return {
        "status": "ready" if all_ok else "degraded",
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/live")
async def liveness_check(response: Response) -> Dict[str, str]:
    """Liveness check - basic service alive check."""
    return {"status": "alive"}


@router.get("/metrics")
async def metrics() -> Dict[str, Any]:
    """Basic metrics endpoint."""
    servers = server_registry.list_servers()
    tools = server_registry.list_all_tools()
    resources = server_registry.list_all_resources()

    return {
        "servers_count": len(servers),
        "tools_count": len(tools),
        "resources_count": len(resources),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
