"""RAG MCP server - tools for search, ask, indexing."""

from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.core.logging import logger
from app.servers.base import BaseMCPServer


class RAGMCPServer(BaseMCPServer):
    """MCP server exposing RAG tools."""

    def __init__(self):
        super().__init__(
            name="rag-server",
            version="0.1.0",
            description="RAG tools for document search, Q&A, and knowledge retrieval",
        )
        self._http_client: Optional[httpx.AsyncClient] = None

    async def initialize(self) -> None:
        """Initialize and register RAG tools."""
        self._http_client = httpx.AsyncClient(timeout=60.0)

        # Search tool
        self.register_tool(
            name="rag_search",
            description="Search documents using hybrid vector + BM25 retrieval",
            handler=self._rag_search,
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "top_k": {"type": "integer", "description": "Number of results", "default": 10},
                    "use_hybrid": {"type": "boolean", "description": "Use hybrid search", "default": True},
                    "use_reranker": {"type": "boolean", "description": "Use reranker", "default": True},
                    "filters": {"type": "object", "description": "Metadata filters"},
                },
                "required": ["query"],
            },
        )

        # Ask tool
        self.register_tool(
            name="rag_ask",
            description="Ask a question and get an answer with citations from the knowledge base",
            handler=self._rag_ask,
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Question to ask"},
                    "top_k": {"type": "integer", "description": "Number of context docs", "default": 10},
                    "include_sources": {"type": "boolean", "description": "Include source citations", "default": True},
                },
                "required": ["query"],
            },
        )

        # Reindex tool
        self.register_tool(
            name="rag_reindex",
            description="Trigger document reindexing from Google Drive",
            handler=self._rag_reindex,
            input_schema={
                "type": "object",
                "properties": {
                    "job_type": {"type": "string", "enum": ["full", "incremental"], "default": "incremental"},
                    "folder_id": {"type": "string", "description": "Specific folder to index"},
                },
            },
        )

        # Stats tool
        self.register_tool(
            name="rag_stats",
            description="Get RAG system statistics",
            handler=self._rag_stats,
            input_schema={
                "type": "object",
                "properties": {},
            },
        )

        # Register resources
        self.register_resource(
            uri="rag://stats",
            name="RAG Statistics",
            handler=self._get_rag_stats_resource,
            description="Current RAG system statistics",
            mime_type="application/json",
        )

        # Register prompts
        self.register_prompt(
            name="rag_qa_prompt",
            handler=self._get_qa_prompt,
            description="Q&A prompt template for RAG",
            arguments=[
                {"name": "context", "description": "Retrieved context", "required": True},
                {"name": "question", "description": "User question", "required": True},
            ],
        )

        logger.info("RAG MCP server initialized")

    async def _rag_search(
        self,
        query: str,
        top_k: int = 10,
        use_hybrid: bool = True,
        use_reranker: bool = True,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Search documents via RAG service."""
        try:
            response = await self._http_client.post(
                f"{settings.RAG_SERVICE_URL}/search",
                json={
                    "query": query,
                    "top_k": top_k,
                    "use_hybrid": use_hybrid,
                    "use_reranker": use_reranker,
                    "filters": filters or {},
                },
            )
            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [])
                formatted = "\n\n".join([
                    f"**{i+1}. {r.get('title', 'Untitled')}** (score: {r.get('score', 0):.3f})\n{r.get('content', '')[:500]}..."
                    for i, r in enumerate(results[:5])
                ])
                return {"type": "text", "text": formatted or "No results found"}
            return {"type": "text", "text": f"Search error: {response.status_code}"}
        except Exception as e:
            return {"type": "text", "text": f"RAG service unavailable: {str(e)}"}

    async def _rag_ask(
        self,
        query: str,
        top_k: int = 10,
        include_sources: bool = True,
    ) -> Dict[str, Any]:
        """Ask a question via RAG service."""
        try:
            response = await self._http_client.post(
                f"{settings.RAG_SERVICE_URL}/ask",
                json={
                    "query": query,
                    "top_k": top_k,
                },
            )
            if response.status_code == 200:
                data = response.json()
                answer = data.get("answer", "No answer generated")
                sources = data.get("sources", [])

                result = f"**Answer:**\n{answer}"
                if include_sources and sources:
                    result += "\n\n**Sources:**\n"
                    for i, src in enumerate(sources[:3]):
                        result += f"- {src.get('title', 'Unknown')}\n"

                return {"type": "text", "text": result}
            return {"type": "text", "text": f"Ask error: {response.status_code}"}
        except Exception as e:
            return {"type": "text", "text": f"RAG service unavailable: {str(e)}"}

    async def _rag_reindex(
        self,
        job_type: str = "incremental",
        folder_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Trigger reindexing."""
        try:
            response = await self._http_client.post(
                f"{settings.RAG_SERVICE_URL}/reindex",
                json={
                    "job_type": job_type,
                    "folder_id": folder_id,
                },
            )
            if response.status_code == 200:
                data = response.json()
                return {"type": "text", "text": f"Reindex job started: {data.get('job_id', 'unknown')}"}
            return {"type": "text", "text": f"Reindex error: {response.status_code}"}
        except Exception as e:
            return {"type": "text", "text": f"RAG service unavailable: {str(e)}"}

    async def _rag_stats(self) -> Dict[str, Any]:
        """Get RAG statistics."""
        try:
            response = await self._http_client.get(f"{settings.RAG_SERVICE_URL}/stats")
            if response.status_code == 200:
                data = response.json()
                return {"type": "text", "text": str(data)}
            return {"type": "text", "text": f"Stats error: {response.status_code}"}
        except Exception as e:
            return {"type": "text", "text": f"RAG service unavailable: {str(e)}"}

    async def _get_rag_stats_resource(self) -> str:
        """Get RAG stats as resource."""
        try:
            response = await self._http_client.get(f"{settings.RAG_SERVICE_URL}/stats")
            if response.status_code == 200:
                return response.text
            return '{"error": "unavailable"}'
        except Exception:
            return '{"error": "unavailable"}'

    async def _get_qa_prompt(
        self,
        context: str,
        question: str,
    ) -> List[Dict[str, Any]]:
        """Generate Q&A prompt."""
        return [
            {
                "role": "system",
                "content": {
                    "type": "text",
                    "text": "You are a helpful assistant. Answer questions based on the provided context. If the answer is not in the context, say so.",
                },
            },
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": f"Context:\n{context}\n\nQuestion: {question}",
                },
            },
        ]

    async def cleanup(self) -> None:
        """Cleanup resources."""
        if self._http_client:
            await self._http_client.aclose()
