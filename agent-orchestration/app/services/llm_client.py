"""LLM Client for multiple LLM providers.

Supports:
- Google Gemini (Primary)
- OpenRouter (Fallback)
- OpenAI (Alternative)
"""

import logging
import httpx
from typing import Dict, Any, Optional, List, AsyncGenerator, Union

from langsmith import traceable

from app.core.config import settings

logger = logging.getLogger(__name__)


def _normalize_message_content(content: Union[str, List[Any], None]) -> str:
    """OpenAI-compatible APIs may return message.content as a string or a list of parts."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text" and "text" in part:
                    parts.append(str(part["text"]))
                elif "text" in part:
                    parts.append(str(part["text"]))
            elif isinstance(part, str):
                parts.append(part)
        return "".join(parts)
    return str(content)


class LLMClient:
    """
    Universal LLM Client supporting multiple providers.
    
    Supports:
    - Google Gemini API
    - OpenRouter API
    - OpenAI API
    - Chat completions (streaming and non-streaming)
    - Token usage tracking
    - Error handling with retries
    """
    
    def __init__(self):
        # HOTFIX: Force LLM configuration from .env file if available
        import os
        from pathlib import Path
        env_file = Path("/app/.env")
        if env_file.exists():
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        if key in [
                            "LLM_PROVIDER",
                            "LLM_MODEL",
                            "LLM_API_KEY",
                            "LLM_BASE_URL",
                            "OPENROUTER_API_KEY",
                            "GEMINI_API_KEY",
                            "GOOGLE_API_KEY",
                        ]:
                            os.environ[key] = value
        
        self.provider = os.getenv("LLM_PROVIDER", settings.LLM_PROVIDER).lower()
        self.base_url = os.getenv("LLM_BASE_URL", settings.LLM_BASE_URL).rstrip("/")
        self.model = os.getenv("LLM_MODEL", settings.LLM_MODEL)
        self.temperature = settings.LLM_TEMPERATURE
        self.max_tokens = settings.LLM_MAX_TOKENS
        self.google_openai_compat = False
        default_api_key = os.getenv("LLM_API_KEY", settings.LLM_API_KEY)
        openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
        gemini_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

        # Resolve provider-specific key first, then generic LLM_API_KEY.
        if self.provider == "openrouter":
            self.api_key = openrouter_api_key or default_api_key
        elif self.provider == "google":
            self.api_key = gemini_api_key or default_api_key
        else:
            self.api_key = default_api_key
        
        # Provider-specific configuration
        if self.provider == "google":
            # Support both native Gemini API and Google OpenAI-compatible API.
            self.google_openai_compat = "/openai" in self.base_url
            if self.google_openai_compat:
                self.headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                }
                self.api_url = f"{self.base_url}/chat/completions"
            else:
                self.headers = {
                    "Content-Type": "application/json",
                }
                # Gemini native API uses API key in URL query string.
                self.api_url = f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"
        elif self.provider == "openrouter":
            self.headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:3000",
                "X-Title": "AegisOps Agent Orchestration"
            }
            self.api_url = f"{self.base_url}/chat/completions"
        else:  # openai or default
            self.headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            self.api_url = f"{self.base_url}/chat/completions"
        
        mode = "openai-compatible" if self.google_openai_compat else "native"
        logger.info(f"LLM Client initialized with provider: {self.provider}, model: {self.model}, mode: {mode}")
    
    def override_model(self, model: str, base_url: str = None):
        """Override the model and base URL at runtime."""
        self.model = model
        if base_url:
            self.base_url = base_url
        logger.info(f"LLM client model overridden to: {self.model} at {self.base_url}")
    
    def _convert_to_gemini_format(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """Convert OpenAI-style messages to Gemini format."""
        contents = []
        system_instruction = None
        
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            
            if role == "system":
                system_instruction = content
            elif role == "user":
                contents.append({
                    "role": "user",
                    "parts": [{"text": content}]
                })
            elif role == "assistant":
                contents.append({
                    "role": "model",
                    "parts": [{"text": content}]
                })
        
        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_tokens,
            }
        }
        
        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }
        
        return payload
    
    def _convert_gemini_response(self, response_data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Gemini response to OpenAI format."""
        try:
            logger.debug(f"Raw Gemini response: {response_data}")
            candidate = response_data.get("candidates", [{}])[0]
            content_parts = candidate.get("content", {}).get("parts", [{}])
            text = content_parts[0].get("text", "") if content_parts else ""
            text = _normalize_message_content(text)

            logger.debug(f"Extracted text from Gemini: '{text}'")
            
            # Extract usage info if available
            usage_metadata = response_data.get("usageMetadata", {})
            
            return {
                "content": text,
                "model": self.model,
                "usage": {
                    "prompt_tokens": usage_metadata.get("promptTokenCount", 0),
                    "completion_tokens": usage_metadata.get("candidatesTokenCount", 0),
                    "total_tokens": usage_metadata.get("totalTokenCount", 0)
                },
                "finish_reason": candidate.get("finishReason", "stop")
            }
        except Exception as e:
            logger.error(f"Error converting Gemini response: {e}")
            return {
                "content": "",
                "model": self.model,
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "error": str(e)
            }
    
    @traceable(name="llm_chat_completion", run_type="llm")
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False
    ) -> Dict[str, Any]:
        """
        Send a chat completion request to the configured LLM provider.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            model: Model to use (defaults to configured model)
            temperature: Sampling temperature (defaults to configured)
            max_tokens: Max tokens to generate (defaults to configured)
            stream: Whether to stream the response
            
        Returns:
            Response dict with 'content', 'model', 'usage', etc.
        """
        model = model or self.model
        temperature = temperature if temperature is not None else self.temperature
        max_tokens = max_tokens or self.max_tokens
        
        logger.info(f"Sending LLM request to {self.provider} with model {model}")
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                if self.provider == "google" and not self.google_openai_compat:
                    # Convert to Gemini format
                    payload = self._convert_to_gemini_format(messages)
                    payload["generationConfig"]["temperature"] = temperature
                    payload["generationConfig"]["maxOutputTokens"] = max_tokens
                    
                    response = await client.post(
                        self.api_url,
                        headers=self.headers,
                        json=payload
                    )
                    response.raise_for_status()
                    response_data = response.json()
                    
                    import json as json_lib
                    logger.info(f"Raw Gemini API response: {json_lib.dumps(response_data, indent=2)}")
                    
                    return self._convert_gemini_response(response_data)
                    
                else:  # OpenRouter/OpenAI/Google OpenAI-compatible format
                    payload = {
                        "model": model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "stream": stream
                    }
                    
                    response = await client.post(
                        self.api_url,
                        headers=self.headers,
                        json=payload
                    )
                
                logger.info(f"LLM response status: {response.status_code}")
                
                if response.status_code != 200:
                    logger.error(f"LLM API error: {response.status_code} - {response.text}")
                    response.raise_for_status()
                
                data = response.json()
                logger.debug(f"LLM response data: {data}")
                
                if not data.get("choices") or len(data["choices"]) == 0:
                    logger.error(f"No choices in LLM response: {data}")
                    raise ValueError("No choices returned from LLM")
                
                content = _normalize_message_content(data["choices"][0]["message"].get("content"))
                if not content or content.strip() == "":
                    logger.error(f"Empty content in LLM response: {data}")
                    raise ValueError("Empty content returned from LLM")
                
                logger.info(f"LLM response received, content length: {len(content)}")
                
                return {
                    "content": content,
                    "model": data.get("model", model),
                    "usage": data.get("usage", {}),
                    "finish_reason": data["choices"][0].get("finish_reason"),
                    "id": data.get("id")
                }
                
        except httpx.HTTPStatusError as e:
            logger.error(f"LLM API error: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"LLM request failed: {e}")
            raise
    
    async def chat_completion_stream(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ) -> AsyncGenerator[str, None]:
        """
        Stream chat completion response from OpenRouter.
        
        Args:
            messages: List of message dicts
            model: Model to use
            temperature: Sampling temperature
            max_tokens: Max tokens to generate
            
        Yields:
            Content chunks as they arrive
        """
        model = model or self.model
        temperature = temperature if temperature is not None else self.temperature
        max_tokens = max_tokens or self.max_tokens
        
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True
        }
        
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self.headers,
                    json=payload
                ) as response:
                    response.raise_for_status()
                    
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                break
                            
                            try:
                                import json
                                chunk = json.loads(data)
                                delta = chunk["choices"][0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except json.JSONDecodeError:
                                continue
                                
        except httpx.HTTPStatusError as e:
            logger.error(f"LLM streaming error: {e.response.status_code}")
            raise
        except Exception as e:
            logger.error(f"LLM streaming failed: {e}")
            raise
    
    async def route_request(self, message: str) -> Dict[str, Any]:
        """
        Use LLM to route a request to the appropriate agent path.
        
        Args:
            message: User message to classify
            
        Returns:
            Dict with 'request_type', 'confidence', 'reasoning'
        """
        system_prompt = """You are a request classifier for an IT operations system.
Classify the user's request into one of these categories:
- service_request: New service provisioning, deployments, setups
- change_request: Modifications, updates, upgrades to existing systems
- incident: System issues, errors, outages, problems
- problem: Root cause analysis, recurring issues

Respond in JSON format:
{"request_type": "category", "confidence": 0.0-1.0, "reasoning": "brief explanation"}"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message}
        ]
        
        try:
            response = await self.chat_completion(
                messages=messages,
                temperature=0.1,
                max_tokens=200
            )
            
            import json
            result = json.loads(response["content"])
            return result
            
        except Exception as e:
            logger.error(f"LLM routing failed: {e}")
            raise ValueError(f"Unable to route request - LLM classification failed: {e}")
    
    async def generate_analysis(
        self,
        context: str,
        query: str,
        rag_results: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """
        Generate analysis using RAG context.
        
        Args:
            context: Current context/state
            query: User query
            rag_results: Retrieved documents from RAG
            
        Returns:
            Analysis dict with 'analysis', 'recommendations', 'confidence'
        """
        rag_context = ""
        if rag_results:
            rag_context = "\n\nRelevant Knowledge:\n"
            for i, doc in enumerate(rag_results[:5], 1):
                rag_context += f"{i}. {doc.get('content', '')[:500]}\n"
        
        system_prompt = f"""You are an IT operations analyst. Analyze the situation and provide recommendations.

Current Context:
{context}
{rag_context}

Provide your analysis in JSON format:
{{
    "analysis": "detailed analysis",
    "recommendations": ["action1", "action2"],
    "confidence": 0.0-1.0,
    "risk_level": "low|medium|high",
    "estimated_time": "time estimate"
}}"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ]
        
        try:
            response = await self.chat_completion(
                messages=messages,
                temperature=0.3,
                max_tokens=1000
            )
            
            import json
            return json.loads(response["content"])
            
        except Exception as e:
            logger.error(f"Analysis generation failed: {e}")
            return {
                "analysis": "Unable to generate analysis",
                "recommendations": [],
                "confidence": 0.0,
                "risk_level": "unknown",
                "estimated_time": "unknown"
            }
    
    async def health_check(self) -> Dict[str, Any]:
        """Check LLM service health."""
        try:
            response = await self.chat_completion(
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=10
            )
            return {
                "status": "healthy",
                "model": self.model,
                "provider": self.provider
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "model": self.model,
                "provider": self.provider
            }


# Global LLM client instance
llm_client = LLMClient()
