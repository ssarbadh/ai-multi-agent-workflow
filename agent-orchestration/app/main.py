"""
FastAPI Application Entry Point
LangGraph-based multi-agent orchestration for Infra & Platform operations.
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.database import init_db, close_db, get_engine
from app.core.redis_client import redis_client
from app.core.observability import (
    setup_observability,
    shutdown_observability,
    instrument_app,
    instrument_sqlalchemy,
    instrument_redis,
    instrument_httpx,
    get_metrics,
)
from app.services.workflow_registry import initialize_workflow_registry, get_workflow_registry

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown events."""
    # Startup
    logger.info(f"Starting {settings.SERVICE_NAME} v{settings.SERVICE_VERSION}")
    
    try:
        # Initialize observability
        setup_observability()
        
        # Initialize database
        await init_db()
        engine = get_engine()
        instrument_sqlalchemy(engine)
        
        # Initialize Redis
        await redis_client.connect()
        instrument_redis()
        
        # Instrument HTTP clients
        instrument_httpx()
        
        # Initialize workflow registry
        registry = await initialize_workflow_registry()
        stats = registry.get_workflow_statistics()
        logger.info(f"Workflow registry initialized: {stats}")
        logger.info(
            f"Loaded {stats['total_workflows']} workflows "
            f"with {stats['total_steps']} total steps"
        )
        
        # Wire up approval service to approval agent
        from app.agents.safety_approval_agent import safety_approval_agent
        from app.services.approval_service import approval_service
        approval_service.set_approval_agent(safety_approval_agent)
        logger.info("Approval service connected to safety approval agent")
        
        # Set system health metrics
        metrics = get_metrics()
        metrics.system_health_status.labels(component="database").set(1)
        metrics.system_health_status.labels(component="redis").set(1)
        metrics.system_health_status.labels(component="context_mgmt").set(1)
        metrics.system_health_status.labels(component="rag").set(1)
        
        logger.info(f"{settings.SERVICE_NAME} started successfully")
        logger.info(f"API available at http://{settings.HOST}:{settings.PORT}")
        logger.info(f"Prometheus metrics at http://localhost:{settings.PROMETHEUS_PORT}")
        
        yield
        
    finally:
        # Shutdown
        logger.info(f"Shutting down {settings.SERVICE_NAME}")
        
        # Stop workflow registry watcher
        try:
            registry = get_workflow_registry()
            registry.stop_watching()
        except:
            pass
        
        # Update health metrics
        try:
            metrics = get_metrics()
            metrics.system_health_status.labels(component="database").set(0)
            metrics.system_health_status.labels(component="redis").set(0)
            metrics.system_health_status.labels(component="context_mgmt").set(0)
            metrics.system_health_status.labels(component="rag").set(0)
        except:
            pass
        
        await redis_client.close()
        await close_db()
        shutdown_observability()
        
        logger.info(f"{settings.SERVICE_NAME} shut down successfully")


# Create FastAPI app
app = FastAPI(
    title="Agent Orchestration Service",
    description="LangGraph-based multi-agent orchestration for Infra & Platform operations",
    version=settings.SERVICE_VERSION,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# Instrument FastAPI with OpenTelemetry
instrument_app(app)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler with sanitized error responses."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "type": type(exc).__name__,
        },
    )


# Import and include routers (will be created next)
from app.api import health, orchestration, streaming, approvals, vm_console, snow, notifications, ec2, metrics, devops, sessions, incident_analysis, sre_multi_agent

app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(sessions.router, prefix="/api/v1", tags=["sessions"])
app.include_router(orchestration.router, prefix="/api/v1", tags=["orchestration"])
app.include_router(streaming.router, prefix="/api/v1", tags=["streaming"])
app.include_router(approvals.router, prefix="/api/v1", tags=["approvals"])
app.include_router(vm_console.router, prefix="/api/v1", tags=["vm-console"])
app.include_router(snow.router, prefix="/api/v1", tags=["servicenow"])
app.include_router(notifications.router, prefix="/api/v1", tags=["notifications"])
app.include_router(ec2.router, tags=["ec2"])
app.include_router(metrics.router, tags=["metrics"])
app.include_router(devops.router, prefix="/api/v1", tags=["devops"])
app.include_router(incident_analysis.router, prefix="/api/v1", tags=["incident-analysis"])
app.include_router(sre_multi_agent.router, prefix="/api/v1", tags=["sre-multi-agent"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": settings.SERVICE_NAME,
        "version": settings.SERVICE_VERSION,
        "status": "operational",
        "environment": settings.ENVIRONMENT,
    }


@app.get("/health")
async def root_health():
    """Root health endpoint for frontend compatibility."""
    return {
        "status": "healthy",
        "services": {
            "agent-orchestration": "healthy",
            "database": "healthy",
            "redis": "healthy",
        }
    }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower(),
    )
