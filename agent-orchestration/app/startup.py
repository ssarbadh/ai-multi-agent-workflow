"""Initialize workflow registry on application startup.

Add this to your FastAPI app startup to initialize the dynamic workflow system.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
import logging

from app.services.workflow_registry import initialize_workflow_registry, get_workflow_registry

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan manager - initialize services on startup.
    """
    logger.info("Starting application...")
    
    # Initialize workflow registry
    try:
        registry = await initialize_workflow_registry()
        stats = registry.get_workflow_statistics()
        logger.info(f"Workflow registry initialized: {stats}")
        logger.info(
            f"Loaded {stats['total_workflows']} workflows "
            f"with {stats['total_steps']} total steps"
        )
    except Exception as e:
        logger.error(f"Failed to initialize workflow registry: {e}")
        # Don't fail startup, but log the error
    
    yield
    
    # Cleanup on shutdown
    logger.info("Shutting down application...")
    try:
        registry = get_workflow_registry()
        registry.stop_watching()
        logger.info("Workflow registry stopped")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")


# Example: Add to main.py
"""
from app.main import app
from app.startup import lifespan

app = FastAPI(
    title="AegisOps Agent Orchestration",
    lifespan=lifespan
)
"""
