"""Redis client configuration."""

import redis.asyncio as redis
import asyncio
import logging
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class RedisClient:
    """Async Redis client wrapper with retry logic."""
    
    def __init__(self):
        self._client: Optional[redis.Redis] = None
    
    async def connect(self, max_retries: int = 3) -> None:
        """Connect to Redis with retry logic."""
        for attempt in range(max_retries):
            try:
                self._client = await redis.from_url(
                    settings.REDIS_URL,
                    max_connections=settings.REDIS_MAX_CONNECTIONS,
                    socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
                    socket_connect_timeout=settings.REDIS_SOCKET_CONNECT_TIMEOUT,
                    decode_responses=True,
                    retry_on_timeout=True,  # Enable automatic retry on timeout
                    health_check_interval=30,  # Health check every 30 seconds
                )
                # Test connection
                await self._client.ping()
                logger.info("✅ Redis connected successfully")
                return
            except Exception as e:
                logger.warning(f"Redis connection attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                else:
                    logger.error(f"❌ Failed to connect to Redis after {max_retries} attempts")
                    raise
    
    async def close(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            logger.info("Redis connection closed")
    
    @property
    def client(self) -> redis.Redis:
        """Get Redis client instance."""
        if not self._client:
            raise RuntimeError("Redis client not connected. Call connect() first.")
        return self._client
    
    async def ping(self) -> bool:
        """Check Redis connection."""
        try:
            return await self.client.ping()
        except Exception as e:
            logger.error(f"Redis ping failed: {e}")
            return False


# Global Redis client instance
redis_client = RedisClient()


async def get_redis() -> redis.Redis:
    """Dependency for getting Redis client."""
    return redis_client.client
