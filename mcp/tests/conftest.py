"""Test fixtures for MCP service."""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=True)
    redis.keys = AsyncMock(return_value=[])
    redis.ping = AsyncMock(return_value=True)
    return redis


@pytest.fixture
def mock_http_client():
    """Mock HTTP client."""
    client = AsyncMock()
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"status": "ok"}
    response.text = '{"status": "ok"}'
    client.get = AsyncMock(return_value=response)
    client.post = AsyncMock(return_value=response)
    return client
