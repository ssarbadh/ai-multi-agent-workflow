"""LLM generation service using OpenRouter."""
import logging
from typing import List, Dict, Any, Optional, AsyncIterator
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMService:
    """Service for generating answers using LLM via OpenRouter."""
    
    def __init__(self):
        self.api_key = settings.openrouter_api_key
        self.base_url = settings.openrouter_base_url
        self.model = settings.rag_llm_model
        self.temperature = settings.rag_llm_temperature
        self.max_tokens = settings.rag_llm_max_tokens
        self.site_url = settings.openrouter_site_url
        self.site_name = settings.openrouter_site_name
        
    def _build_headers(self) -> Dict[str, str]:
        """Build request headers."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.site_url,
            "X-Title": self.site_name,
        }
    
    def _build_prompt(
        self,
        query: str,
        context_docs: List[Dict[str, Any]],
        system_prompt: str = None
    ) -> List[Dict[str, str]]:
        """Build prompt with context."""
        # Default system prompt
        if not system_prompt:
            system_prompt = (
                "You are a helpful AI assistant that answers questions based on the provided context. "
                "Always cite sources when providing information. "
                "If you cannot answer based on the context, say so clearly."
            )
        
        # Build context from documents
        context_parts = []
        for i, doc in enumerate(context_docs, 1):
            title = doc.get("title", "Untitled")
            content = doc.get("content", "")
            source = doc.get("source", "")
            
            context_parts.append(
                f"[{i}] Title: {title}\n"
                f"Source: {source}\n"
                f"Content: {content}\n"
            )
        
        context_text = "\n\n".join(context_parts)
        
        # Build messages
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"Context:\n{context_text}\n\n"
                    f"Question: {query}\n\n"
                    f"Please answer the question based on the context above. "
                    f"Include citations using [1], [2], etc."
                )
            }
        ]
        
        return messages
    
    async def generate(
        self,
        query: str,
        context_docs: List[Dict[str, Any]],
        system_prompt: str = None,
        stream: bool = False
    ) -> Dict[str, Any]:
        """Generate answer using LLM."""
        messages = self._build_prompt(query, context_docs, system_prompt)
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._build_headers(),
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": self.temperature,
                        "max_tokens": self.max_tokens,
                        "stream": stream,
                    }
                )
                
                response.raise_for_status()
                result = response.json()
                
                # Extract answer
                answer = result["choices"][0]["message"]["content"]
                
                # Extract citations from answer
                citations = self._extract_citations(answer, context_docs)
                
                return {
                    "answer": answer,
                    "citations": citations,
                    "model": self.model,
                    "usage": result.get("usage", {}),
                }
                
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            raise
    
    async def generate_stream(
        self,
        query: str,
        context_docs: List[Dict[str, Any]],
        system_prompt: str = None
    ) -> AsyncIterator[str]:
        """Generate answer with streaming."""
        messages = self._build_prompt(query, context_docs, system_prompt)
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self._build_headers(),
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": self.temperature,
                        "max_tokens": self.max_tokens,
                        "stream": True,
                    }
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
                                if chunk["choices"][0].get("delta", {}).get("content"):
                                    yield chunk["choices"][0]["delta"]["content"]
                            except json.JSONDecodeError:
                                continue
                                
        except Exception as e:
            logger.error(f"Streaming generation failed: {e}")
            raise
    
    def _extract_citations(
        self,
        answer: str,
        context_docs: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Extract citation references from answer."""
        import re
        
        # Find citation markers like [1], [2], etc.
        citation_pattern = r'\[(\d+)\]'
        matches = re.findall(citation_pattern, answer)
        
        citations = []
        seen = set()
        
        for match in matches:
            idx = int(match) - 1  # Convert to 0-indexed
            if idx < len(context_docs) and idx not in seen:
                doc = context_docs[idx]
                citations.append({
                    "index": int(match),
                    "title": doc.get("title", ""),
                    "source": doc.get("source", ""),
                    "file_id": doc.get("file_id", ""),
                    "file_path": doc.get("file_path", ""),
                })
                seen.add(idx)
        
        return citations
    
    async def evaluate_faithfulness(
        self,
        answer: str,
        context_docs: List[Dict[str, Any]]
    ) -> float:
        """Evaluate if answer is faithful to context (0-1 score)."""
        # Build evaluation prompt
        context_text = "\n\n".join([doc.get("content", "") for doc in context_docs])
        
        eval_prompt = (
            f"Context:\n{context_text}\n\n"
            f"Answer:\n{answer}\n\n"
            f"Is the answer fully supported by the context? "
            f"Reply with only a number between 0 and 1, where 0 means not supported at all "
            f"and 1 means completely supported."
        )
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._build_headers(),
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": eval_prompt}],
                        "temperature": 0.0,
                        "max_tokens": 10,
                    }
                )
                
                response.raise_for_status()
                result = response.json()
                score_text = result["choices"][0]["message"]["content"].strip()
                
                # Extract number
                import re
                match = re.search(r'(\d+\.?\d*)', score_text)
                if match:
                    return float(match.group(1))
                return 0.5  # Default if parsing fails
                
        except Exception as e:
            logger.error(f"Faithfulness evaluation failed: {e}")
            return 0.5


# Global LLM service instance
llm_service = LLMService()
