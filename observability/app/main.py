"""Main FastAPI application for Observability service."""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import start_http_server

from app.core.config import settings
from app.core.logging import setup_logging, get_logger
from app.core.telemetry import setup_telemetry
from app.api import health, metrics, alerts, dashboards, logs, traces
from app.services.metrics_collector import metrics_collector
from app.services.alerting import alerting_service

# Setup logging
setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("Starting Observability service", extra_data={
        "environment": settings.ENVIRONMENT,
        "port": settings.API_PORT
    })
    
    # Start Prometheus metrics server
    try:
        start_http_server(settings.PROMETHEUS_PORT)
        logger.info(f"Prometheus metrics available on port {settings.PROMETHEUS_PORT}")
    except Exception as e:
        logger.warning(f"Failed to start Prometheus server: {e}")
    
    yield
    
    # Cleanup
    logger.info("Shutting down Observability service")
    await metrics_collector.close()
    await alerting_service.close()


# Create FastAPI app
app = FastAPI(
    title="AegisOps Observability",
    description="""
    Observability service for AegisOps platform.
    
    Provides:
    - Agent evaluation metrics (resolution rate, time-to-resolution, etc.)
    - RAG evaluation metrics (recall@k, faithfulness, latency, etc.)
    - System health monitoring
    - Alerting with SLO-based rules
    - Dashboard data for visualization
    - Log aggregation and search
    - Distributed tracing
    
    Per HLD requirements for metrics, logging, tracing, and alerting.
    """,
    version="0.1.0",
    lifespan=lifespan
)

# Initialize OpenTelemetry instrumentation
setup_telemetry(app)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router)
app.include_router(metrics.router)
app.include_router(alerts.router)
app.include_router(alerts.webhook_router)  # Add webhook router
app.include_router(dashboards.router)
app.include_router(logs.router)
app.include_router(traces.router)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "AegisOps Observability",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.DEBUG
    )
