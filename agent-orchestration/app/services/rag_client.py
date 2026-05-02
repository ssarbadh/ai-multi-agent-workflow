"""Client for RAG service integration."""

import logging
from typing import Dict, Any, List, Optional
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class RAGClient:
    """
    Client for RAG (Retrieval-Augmented Generation) service.
    
    Integrates with RAG for:
    - Knowledge base search
    - Decision matrix retrieval
    - Document retrieval
    - Incident history search
    """
    
    def __init__(self):
        self.base_url = settings.RAG_SERVICE_URL
        self.timeout = settings.RAG_SERVICE_TIMEOUT
    
    async def search_knowledge_base(
        self,
        query: str,
        top_k: int = 10,
        use_hybrid: bool = True,
        filters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Search knowledge base for relevant documents.
        
        Args:
            query: Search query
            top_k: Number of results to return
            use_hybrid: Use hybrid search (vector + BM25)
            filters: Optional metadata filters
            
        Returns:
            Search results with documents and scores
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/search",
                    json={
                        "query": query,
                        "top_k": top_k,
                        "use_hybrid": use_hybrid,
                        "filters": filters or {}
                    }
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to search knowledge base: {e}")
            return {"results": [], "sources": []}
    
    async def get_decision_matrix(
        self,
        incident_type: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Get decision matrix for incident resolution.
        
        Args:
            incident_type: Type of incident
            context: Incident context
            
        Returns:
            Decision matrix with recommended actions
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/decision-matrix",
                    json={
                        "incident_type": incident_type,
                        "context": context
                    }
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to get decision matrix: {e}")
            return {"actions": [], "confidence": 0.0}
    
    async def search_similar_incidents(
        self,
        description: str,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Search for similar past incidents.
        
        Args:
            description: Incident description
            top_k: Number of similar incidents to return
            
        Returns:
            List of similar incidents with resolutions
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/search",
                    json={
                        "query": description,
                        "top_k": top_k,
                        "filters": {
                            "operator": "AND",
                            "conditions": [
                                {
                                    "field": "meta.document_type",
                                    "operator": "==",
                                    "value": "incident"
                                }
                            ]
                        }
                    }
                )
                response.raise_for_status()
                data = response.json()
                return data.get("results", [])
        except Exception as e:
            logger.error(f"Failed to search similar incidents: {e}")
            return []
    
    async def get_documentation(
        self,
        topic: str,
        doc_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Retrieve documentation for a specific topic.
        
        Args:
            topic: Documentation topic
            doc_type: Optional document type filter (runbook, procedure, etc.)
            
        Returns:
            Documentation content and metadata
        """
        try:
            filters = None
            if doc_type:
                filters = {
                    "operator": "AND",
                    "conditions": [
                        {"field": "document_type", "operator": "==", "value": doc_type}
                    ]
                }
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/search",
                    json={
                        "query": topic,
                        "top_k": 3,
                        "filters": filters
                    }
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to get documentation: {e}")
            return {"results": [], "sources": []}
    
    async def ask_question(
        self,
        question: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Ask a question and get RAG-generated answer.
        
        Args:
            question: Question to ask
            context: Optional context for the question
            
        Returns:
            Answer with citations
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/ask",
                    json={
                        "question": question,
                        "context": context or {}
                    }
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to ask question: {e}")
            return {"answer": "", "sources": [], "confidence": 0.0}
    
    async def health_check(self) -> bool:
        """Check if RAG service is healthy."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/health")
                return response.status_code == 200
        except Exception as e:
            logger.error(f"RAG service health check failed: {e}")
            return False


# Global instance
rag_client = RAGClient()

