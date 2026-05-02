"""Health check endpoints."""

import logging
from datetime import datetime
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.database import get_db
from app.core.redis_client import get_redis
from app.core.config import settings
from app.models.schemas import HealthResponse
from app.services.health_checker import health_checker
import httpx

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check(
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis)
):
    """
    Health check endpoint.
    
    Checks:
    - Database connectivity
    - Redis connectivity
    - Backend services (Context Management, RAG, MCP, Observability)
    """
    components = {}
    
    # Check database
    try:
        await db.execute(text("SELECT 1"))
        components["database"] = True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        components["database"] = False
    
    # Check Redis
    try:
        await redis.ping()
        components["redis"] = True
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        components["redis"] = False
    
    # Get cached service status from app state (set during startup)
    service_status = getattr(request.app.state, "service_status", {})
    
    # Add backend services to components
    for service_name, status in service_status.items():
        components[service_name] = status.get("healthy", False)
    
    # Overall status
    all_healthy = all(components.values())
    status = "healthy" if all_healthy else "degraded"
    
    return HealthResponse(
        status=status,
        version=settings.SERVICE_VERSION,
        environment=settings.ENVIRONMENT,
        components=components,
        timestamp=datetime.utcnow()
    )


@router.get("/health/services")
async def services_health_check(request: Request):
    """
    Detailed health check for backend services.
    
    Returns detailed status of:
    - Context Management
    - RAG
    - MCP
    - Observability
    """
    # Get cached status from app state
    service_status = getattr(request.app.state, "service_status", {})
    
    # If no cached status, check now
    if not service_status:
        service_status = await health_checker.check_all_services()
        request.app.state.service_status = service_status
    
    return {
        "services": service_status,
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/ready")
async def readiness_check():
    """Readiness probe for Kubernetes."""
    return {"status": "ready"}


@router.get("/live")
async def liveness_check():
    """Liveness probe for Kubernetes."""
    return {"status": "alive"}
