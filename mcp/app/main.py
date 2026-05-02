"""Main FastAPI application for MCP service."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging import configure_logging, logger
from app.core.redis_client import redis_client
from app.services.server_registry import server_registry
from app.services.gateway import gateway
from app.services.openapi_bridge import openapi_bridge

# Import routers
from app.api import health, servers, tools, resources, prompts, sessions, openapi_bridge as openapi_router, sse, metrics, graph


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    configure_logging()
    logger.info(f"Starting {settings.SERVICE_NAME} v{settings.VERSION}")

    # Connect to Redis
    await redis_client.connect()

    # Initialize services
    await server_registry.initialize()
    await gateway.initialize()
    await openapi_bridge.initialize()

    logger.info("MCP service started successfully")

    yield

    # Shutdown
    logger.info("Shutting down MCP service")
    await server_registry.shutdown()
    await gateway.shutdown()
    await openapi_bridge.shutdown()
    await redis_client.disconnect()
    logger.info("MCP service shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="AegisOps MCP Service",
    description="Model Context Protocol service for AegisOps - exposes tools, resources, and prompts for AI agents",
    version=settings.VERSION,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler."""
    logger.error(f"Unhandled exception: {exc}", path=request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc) if settings.DEBUG else "An error occurred",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


# Include routers
app.include_router(health.router, prefix="/api/v1")
app.include_router(metrics.router)
app.include_router(servers.router, prefix="/api/v1")
app.include_router(tools.router, prefix="/api/v1")
app.include_router(resources.router, prefix="/api/v1")
app.include_router(prompts.router, prefix="/api/v1")
app.include_router(sessions.router, prefix="/api/v1")
app.include_router(openapi_router.router, prefix="/api/v1")
app.include_router(sse.router, prefix="/api/v1")
app.include_router(graph.router, prefix="/api/v1")


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": settings.SERVICE_NAME,
        "version": settings.VERSION,
        "status": "running",
        "docs": "/api/docs",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.DEBUG,
    )
