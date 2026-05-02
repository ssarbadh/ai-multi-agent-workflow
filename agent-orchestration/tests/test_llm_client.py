"""Tests for LLM Client (OpenRouter integration)."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx


class TestLLMClient:
    """Test suite for LLM client."""
    
    @pytest.fixture
    def mock_settings(self):
        """Mock settings for testing."""
        with patch('app.services.llm_client.settings') as mock:
            mock.LLM_API_KEY = "test-api-key"
            mock.LLM_BASE_URL = "https://openrouter.ai/api/v1"
            mock.LLM_MODEL = "meta-llama/llama-3.2-3b-instruct:free"
            mock.LLM_TEMPERATURE = 0.7
            mock.LLM_MAX_TOKENS = 4096
            yield mock
    
    @pytest.fixture
    def llm_client(self, mock_settings):
        """Create LLM client instance."""
        from app.services.llm_client import LLMClient
        return LLMClient()
    
    @pytest.mark.asyncio
    async def test_chat_completion_success(self, llm_client):
        """Test successful chat completion."""
        mock_response = {
            "id": "test-id",
            "choices": [{
                "message": {"content": "Hello! How can I help?"},
                "finish_reason": "stop"
            }],
            "model": "meta-llama/llama-3.2-3b-instruct:free",
            "usage": {"prompt_tokens": 10, "completion_tokens": 20}
        }
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            mock_http_response = MagicMock()
            mock_http_response.status_code = 200
            mock_http_response.json.return_value = mock_response
            mock_http_response.raise_for_status = MagicMock()
            mock_instance.post.return_value = mock_http_response
            
            result = await llm_client.chat_completion(
                messages=[{"role": "user", "content": "Hello"}]
            )
            
            assert result["content"] == "Hello! How can I help?"
            assert result["model"] == "meta-llama/llama-3.2-3b-instruct:free"
            assert "usage" in result
    
    @pytest.mark.asyncio
    async def test_route_request_service_request(self, llm_client):
        """Test routing a service request."""
        mock_response = {
            "id": "test-id",
            "choices": [{
                "message": {
                    "content": '{"request_type": "service_request", "confidence": 0.95, "reasoning": "User wants to create new infrastructure"}'
                },
                "finish_reason": "stop"
            }],
            "model": "meta-llama/llama-3.2-3b-instruct:free",
            "usage": {}
        }
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            mock_http_response = MagicMock()
            mock_http_response.status_code = 200
            mock_http_response.json.return_value = mock_response
            mock_http_response.raise_for_status = MagicMock()
            mock_instance.post.return_value = mock_http_response
            
            result = await llm_client.route_request("Create a new EC2 instance")
            
            assert result["request_type"] == "service_request"
            assert result["confidence"] == 0.95
    
    @pytest.mark.asyncio
    async def test_route_request_incident(self, llm_client):
        """Test routing an incident request."""
        mock_response = {
            "id": "test-id",
            "choices": [{
                "message": {
                    "content": '{"request_type": "incident", "confidence": 0.9, "reasoning": "System is down"}'
                },
                "finish_reason": "stop"
            }],
            "model": "meta-llama/llama-3.2-3b-instruct:free",
            "usage": {}
        }
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            mock_http_response = MagicMock()
            mock_http_response.status_code = 200
            mock_http_response.json.return_value = mock_response
            mock_http_response.raise_for_status = MagicMock()
            mock_instance.post.return_value = mock_http_response
            
            result = await llm_client.route_request("The server is down and not responding")
            
            assert result["request_type"] == "incident"
    
    @pytest.mark.asyncio
    async def test_fallback_routing(self, llm_client):
        """Test fallback routing when LLM fails."""
        # Test service request keywords
        result = llm_client._fallback_route("Create a new database")
        assert result["request_type"] == "service_request"
        
        # Test change request keywords
        result = llm_client._fallback_route("Update the server configuration")
        assert result["request_type"] == "change_request"
        
        # Test incident keywords
        result = llm_client._fallback_route("The application is not working")
        assert result["request_type"] == "incident"
        
        # Test default
        result = llm_client._fallback_route("Hello")
        assert result["request_type"] == "service_request"
    
    @pytest.mark.asyncio
    async def test_health_check_success(self, llm_client):
        """Test health check when LLM is available."""
        mock_response = {
            "id": "test-id",
            "choices": [{
                "message": {"content": "pong"},
                "finish_reason": "stop"
            }],
            "model": "meta-llama/llama-3.2-3b-instruct:free",
            "usage": {}
        }
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            mock_http_response = MagicMock()
            mock_http_response.status_code = 200
            mock_http_response.json.return_value = mock_response
            mock_http_response.raise_for_status = MagicMock()
            mock_instance.post.return_value = mock_http_response
            
            result = await llm_client.health_check()
            
            assert result["status"] == "healthy"
            assert result["provider"] == "openrouter"
    
    @pytest.mark.asyncio
    async def test_health_check_failure(self, llm_client):
        """Test health check when LLM is unavailable."""
        with patch('httpx.AsyncClient') as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.side_effect = httpx.ConnectError("Connection refused")
            
            result = await llm_client.health_check()
            
            assert result["status"] == "unhealthy"
            assert "error" in result
    
    def test_available_models(self, llm_client):
        """Test that available models are configured."""
        assert len(llm_client.available_models) > 0
        assert "meta-llama/llama-3.2-3b-instruct:free" in llm_client.available_models
        assert "google/gemma-2-9b-it:free" in llm_client.available_models
