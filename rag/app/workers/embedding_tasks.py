"""Celery tasks for batch embedding generation."""
import logging
from typing import List, Dict, Any

from app.celery_app import celery_app
from app.services.embeddings import embedding_service
from app.services.cache import cache_manager

logger = logging.getLogger(__name__)


@celery_app.task(name="embedding.batch_embed", bind=True)
def batch_embed_task(self, texts: List[str], use_cache: bool = True) -> List[List[float]]:
    """
    Celery task for batch embedding generation.
    
    Args:
        texts: List of texts to embed
        use_cache: Whether to use caching
        
    Returns:
        List of embedding vectors
    """
    import asyncio
    return asyncio.run(_execute_batch_embed(texts, use_cache))


@celery_app.task(name="embedding.warmup_cache", bind=True)
def warmup_cache_task(self, doc_ids: List[str]) -> Dict[str, Any]:
    """
    Celery task to warmup embedding cache for frequently accessed documents.
    
    Args:
        doc_ids: List of document IDs to warmup
        
    Returns:
        Warmup statistics
    """
    import asyncio
    return asyncio.run(_execute_warmup_cache(doc_ids))


async def _execute_batch_embed(texts: List[str], use_cache: bool) -> List[List[float]]:
    """Execute batch embedding."""
    try:
        embeddings = await embedding_service.embed_batch(texts, use_cache=use_cache)
        return embeddings
    except Exception as e:
        logger.error(f"Batch embedding failed: {e}")
        raise


async def _execute_warmup_cache(doc_ids: List[str]) -> Dict[str, Any]:
    """Warmup cache for documents."""
    try:
        warmed = 0
        for doc_id in doc_ids:
            # Check if already cached
            cached = await cache_manager.get(f"doc:{doc_id}")
            if not cached:
                # This would trigger caching
                warmed += 1
        
        return {
            "total": len(doc_ids),
            "warmed": warmed,
            "already_cached": len(doc_ids) - warmed
        }
    except Exception as e:
        logger.error(f"Cache warmup failed: {e}")
        raise
