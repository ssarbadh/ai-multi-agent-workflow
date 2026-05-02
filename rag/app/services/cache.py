"""Redis cache management for RAG system."""
import json
import logging
import pickle
from typing import Any, Optional, List
import hashlib

import redis.asyncio as aioredis
from redis.asyncio import Redis

from app.core.config import settings

logger = logging.getLogger(__name__)


class CacheManager:
    """Manage Redis cache for embeddings, results, and metadata."""
    
    def __init__(self):
        self.redis: Optional[Redis] = None
        self.embedding_ttl = settings.embedding_cache_ttl
        self.context_ttl = settings.context_cache_ttl
        
    async def connect(self):
        """Connect to Redis."""
        try:
            self.redis = await aioredis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=False,  # We'll handle encoding/decoding
                socket_keepalive=True,
                socket_connect_timeout=5,
            )
            await self.redis.ping()
            logger.info("Connected to Redis successfully")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
    
    async def close(self):
        """Close Redis connection."""
        if self.redis:
            await self.redis.close()
            logger.info("Redis connection closed")
    
    def _make_key(self, prefix: str, identifier: str) -> str:
        """Create a cache key."""
        return f"rag:{prefix}:{identifier}"
    
    def _hash_content(self, content: str) -> str:
        """Create hash of content for cache key."""
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    async def get_embedding(self, text: str, model: str) -> Optional[List[float]]:
        """Get cached embedding for text."""
        if not settings.rag_cache_embeddings or not self.redis:
            return None
        
        try:
            key = self._make_key("emb", f"{model}:{self._hash_content(text)}")
            cached = await self.redis.get(key)
            if cached:
                return pickle.loads(cached)
        except Exception as e:
            logger.warning(f"Failed to get embedding from cache: {e}")
        return None
    
    async def set_embedding(self, text: str, model: str, embedding: List[float]):
        """Cache embedding for text."""
        if not settings.rag_cache_embeddings or not self.redis:
            return
        
        try:
            key = self._make_key("emb", f"{model}:{self._hash_content(text)}")
            await self.redis.setex(
                key,
                self.embedding_ttl,
                pickle.dumps(embedding)
            )
        except Exception as e:
            logger.warning(f"Failed to cache embedding: {e}")
    
    async def get_query_results(self, query: str, top_k: int) -> Optional[dict]:
        """Get cached query results."""
        if not settings.rag_cache_results or not self.redis:
            return None
        
        try:
            key = self._make_key("query", f"{self._hash_content(query)}:{top_k}")
            cached = await self.redis.get(key)
            if cached:
                return json.loads(cached.decode() if isinstance(cached, bytes) else cached)
        except Exception as e:
            logger.warning(f"Failed to get query results from cache: {e}")
        return None
    
    async def set_query_results(self, query: str, top_k: int, results: dict):
        """Cache query results."""
        if not settings.rag_cache_results or not self.redis:
            return
        
        try:
            key = self._make_key("query", f"{self._hash_content(query)}:{top_k}")
            await self.redis.setex(
                key,
                self.context_ttl,
                json.dumps(results)
            )
        except Exception as e:
            logger.warning(f"Failed to cache query results: {e}")
    
    async def invalidate_pattern(self, pattern: str):
        """Invalidate cache keys matching pattern."""
        if not self.redis:
            return
        
        try:
            full_pattern = self._make_key("*", pattern)
            cursor = 0
            count = 0
            while True:
                cursor, keys = await self.redis.scan(
                    cursor, match=full_pattern, count=100
                )
                if keys:
                    await self.redis.delete(*keys)
                    count += len(keys)
                if cursor == 0:
                    break
            logger.info(f"Invalidated {count} cache keys matching pattern: {pattern}")
        except Exception as e:
            logger.warning(f"Failed to invalidate cache: {e}")
    
    async def clear_all(self):
        """Clear all RAG cache keys."""
        await self.invalidate_pattern("*")
    
    async def get_stats(self) -> dict:
        """Get cache statistics."""
        if not self.redis:
            return {}
        
        try:
            info = await self.redis.info("stats")
            return {
                "hits": info.get("keyspace_hits", 0),
                "misses": info.get("keyspace_misses", 0),
                "total_keys": await self.redis.dbsize(),
            }
        except Exception as e:
            logger.warning(f"Failed to get cache stats: {e}")
            return {}


# Global cache manager instance
cache_manager = CacheManager()
