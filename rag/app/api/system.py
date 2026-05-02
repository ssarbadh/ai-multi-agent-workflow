"""API router for system endpoints."""
from fastapi import APIRouter, Depends, Response
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from app.core.database import get_db, check_db_connection
from app.core.config import settings
from app.services.cache import cache_manager
from app.models.models import Document
from app.models.schemas import HealthResponse, StatsResponse

router = APIRouter(tags=["system"])


@router.get("/", response_model=dict)
async def root():
    """Root endpoint."""
    return {
        "service": "RAG Service",
        "version": settings.version,
        "status": "running"
    }


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    db_healthy = await check_db_connection()
    
    try:
        cache_stats = await cache_manager.get_stats()
        redis_healthy = True
    except:
        redis_healthy = False
    
    return HealthResponse(
        status="healthy" if db_healthy and redis_healthy else "degraded",
        version=settings.version,
        environment=settings.environment,
        database=db_healthy,
        redis=redis_healthy,
        embedding_model=settings.rag_embedding_model,
        llm_model=settings.rag_llm_model
    )


@router.get("/stats", response_model=StatsResponse)
async def get_stats(session: AsyncSession = Depends(get_db)):
    """Get service statistics."""
    # Count total documents
    stmt = select(func.count(Document.id)).where(Document.is_deleted == False)
    result = await session.execute(stmt)
    total_docs = result.scalar()
    
    # Count unique files
    stmt = select(func.count(func.distinct(Document.file_id))).where(Document.is_deleted == False)
    result = await session.execute(stmt)
    total_files = result.scalar()
    
    # Get cache stats
    cache_stats = await cache_manager.get_stats()
    
    return StatsResponse(
        total_documents=total_docs or 0,
        total_files=total_files or 0,
        total_chunks=total_docs or 0,
        embedding_model=settings.rag_embedding_model,
        embedding_dim=settings.rag_embedding_dim,
        cache_stats=cache_stats
    )


@router.post("/cache/clear")
async def clear_cache():
    """Clear all cache."""
    try:
        await cache_manager.clear_all()
        return {"message": "Cache cleared successfully"}
    except Exception as e:
        return {"error": str(e)}, 500


@router.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )
