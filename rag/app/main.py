"""FastAPI application for RAG service."""
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import init_db, close_db, get_engine
from app.core.observability import init_observability, get_metrics
from app.services.cache import cache_manager
from app.services.embeddings import embedding_service

# Import API routers
from app.api import system, search, ask, indexing, eval

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(request_id)s] - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for startup and shutdown."""
    # Startup
    logger.info("Starting RAG service...")
    
    try:
        # Initialize observability (Prometheus, OpenTelemetry) - but don't instrument FastAPI yet
        obs_manager = init_observability(
            service_name="rag-service",
            service_version=settings.version,
            environment=settings.environment,
            enable_prometheus=True,
            prometheus_port=8011,  # Use different port from FastAPI (8001)
            enable_otlp=False,  # Enable if you have OTLP collector
        )
        
        # Initialize database
        await init_db()
        
        # Instrument database
        engine = get_engine()
        obs_manager.instrument_sqlalchemy(engine)
        
        # Instrument Redis
        obs_manager.instrument_redis()
        
        # Instrument HTTPX
        obs_manager.instrument_httpx()
        
        # Note: FastAPI instrumentation happens at app creation time (see below)
        
        # Connect to Redis
        await cache_manager.connect()
        
        # Load embedding model
        embedding_service.load_model()
        
        # Set system health metrics
        metrics = get_metrics()
        metrics.system_health_status.labels(component="database").set(1)
        metrics.system_health_status.labels(component="redis").set(1)
        metrics.system_health_status.labels(component="embeddings").set(1)
        
        logger.info("RAG service started successfully")
        logger.info("Prometheus metrics available at http://localhost:8011")
        
        yield
        
    finally:
        # Shutdown
        logger.info("Shutting down RAG service...")
        
        # Update health metrics
        try:
            metrics = get_metrics()
            metrics.system_health_status.labels(component="database").set(0)
            metrics.system_health_status.labels(component="redis").set(0)
            metrics.system_health_status.labels(component="embeddings").set(0)
        except:
            pass
        
        await cache_manager.close()
        await close_db()
        embedding_service.unload_model()
        
        logger.info("RAG service shut down successfully")


# Create FastAPI app
app = FastAPI(
    title="RAG Service",
    description="Retrieval-Augmented Generation service with Google Drive integration",
    version=settings.version,
    lifespan=lifespan
)

# Instrument FastAPI with OpenTelemetry (before adding middleware)
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
FastAPIInstrumentor.instrument_app(app)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add request logging middleware with Prometheus metrics
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all requests with timing, request ID, and record metrics."""
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    
    start_time = time.time()
    
    # Add request_id to logging context
    logger.info(
        f"Request started: {request.method} {request.url.path}",
        extra={"request_id": request_id}
    )
    
    # Process request
    try:
        response = await call_next(request)
        status = response.status_code
    except Exception as e:
        status = 500
        logger.error(f"Request failed: {e}", extra={"request_id": request_id})
        raise
    finally:
        # Calculate duration
        duration = time.time() - start_time
        
        # Record metrics
        try:
            metrics = get_metrics()
            metrics.http_requests_total.labels(
                method=request.method,
                endpoint=request.url.path,
                status=status
            ).inc()
            metrics.http_request_duration.labels(
                method=request.method,
                endpoint=request.url.path
            ).observe(duration)
        except Exception as e:
            logger.warning(f"Failed to record metrics: {e}")
        
        # Log completion
        duration_ms = duration * 1000
        logger.info(
            f"Request completed: {request.method} {request.url.path} - "
            f"Status: {status} - Duration: {duration_ms:.2f}ms",
            extra={"request_id": request_id, "latency_ms": duration_ms}
        )
    
    response.headers["X-Request-ID"] = request_id
    return response

# Include routers
app.include_router(system.router)
app.include_router(search.router)
app.include_router(ask.router)
app.include_router(indexing.router)
app.include_router(eval.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.rag_api_host,
        port=settings.rag_api_port,
        reload=settings.rag_api_reload,
        workers=1  # Use 1 worker for development
    )
