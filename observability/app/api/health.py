"""Health check endpoints."""

from datetime import datetime, timezone
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Basic health check."""
    return {
        "status": "healthy",
        "service": "observability",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/ready")
async def readiness_check():
    """Readiness check for Kubernetes."""
    return {
        "status": "ready",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/live")
async def liveness_check():
    """Liveness check for Kubernetes."""
    return {
        "status": "live",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
