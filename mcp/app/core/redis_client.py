"""Redis client for MCP service - sessions, caching."""

import json
from typing import Any, Dict, List, Optional

import redis.asyncio as redis

from app.core.config import settings
from app.core.logging import logger


class RedisClient:
    """Async Redis client for MCP service."""

    def __init__(self):
        self._client: Optional[redis.Redis] = None

    async def connect(self) -> None:
        """Connect to Redis."""
        try:
            if settings.REDIS_URL:
                self._client = redis.from_url(
                    settings.REDIS_URL,
                    encoding="utf-8",
                    decode_responses=True,
                )
            else:
                self._client = redis.Redis(
                    host=settings.REDIS_HOST,
                    port=settings.REDIS_PORT,
                    db=settings.REDIS_DB,
                    password=settings.REDIS_PASSWORD,
                    encoding="utf-8",
                    decode_responses=True,
                )
            await self._client.ping()
            logger.info("Redis connected successfully")
        except Exception as e:
            logger.error(f"Redis connection failed: {e}")
            self._client = None

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("Redis disconnected")

    @property
    def client(self) -> Optional[redis.Redis]:
        return self._client

    async def get(self, key: str) -> Optional[str]:
        """Get a value from Redis."""
        if not self._client:
            return None
        try:
            return await self._client.get(key)
        except Exception as e:
            logger.error(f"Redis get error: {e}", key=key)
            return None

    async def set(
        self,
        key: str,
        value: str,
        ttl: Optional[int] = None,
    ) -> bool:
        """Set a value in Redis."""
        if not self._client:
            return False
        try:
            if ttl:
                await self._client.setex(key, ttl, value)
            else:
                await self._client.set(key, value)
            return True
        except Exception as e:
            logger.error(f"Redis set error: {e}", key=key)
            return False

    async def delete(self, key: str) -> bool:
        """Delete a key from Redis."""
        if not self._client:
            return False
        try:
            await self._client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Redis delete error: {e}", key=key)
            return False

    async def get_json(self, key: str) -> Optional[Dict[str, Any]]:
        """Get a JSON value from Redis."""
        value = await self.get(key)
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return None
        return None

    async def set_json(
        self,
        key: str,
        value: Dict[str, Any],
        ttl: Optional[int] = None,
    ) -> bool:
        """Set a JSON value in Redis."""
        return await self.set(key, json.dumps(value), ttl)

    async def keys(self, pattern: str) -> List[str]:
        """Get keys matching a pattern."""
        if not self._client:
            return []
        try:
            return await self._client.keys(pattern)
        except Exception as e:
            logger.error(f"Redis keys error: {e}", pattern=pattern)
            return []

    async def incr(self, key: str) -> int:
        """Increment a counter."""
        if not self._client:
            return 0
        try:
            return await self._client.incr(key)
        except Exception as e:
            logger.error(f"Redis incr error: {e}", key=key)
            return 0

    async def expire(self, key: str, ttl: int) -> bool:
        """Set expiry on a key."""
        if not self._client:
            return False
        try:
            await self._client.expire(key, ttl)
            return True
        except Exception as e:
            logger.error(f"Redis expire error: {e}", key=key)
            return False


# Global instance
redis_client = RedisClient()
