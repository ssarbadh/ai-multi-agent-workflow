"""Haystack query pipeline for RAG retrieval and generation."""
import logging
import time
from typing import List, Dict, Any, Optional

from haystack import Pipeline
from haystack.utils import Secret
from haystack_integrations.components.retrievers.pgvector import PgvectorEmbeddingRetriever
from haystack.components.builders import PromptBuilder
from haystack.components.generators import OpenAIGenerator

# Import fixed reranker instead of the buggy one
from app.services.custom_reranker import FixedSentenceTransformersSimilarityRanker

# Try to import Google Gemini generator
try:
    from haystack_integrations.components.generators.google_ai import GoogleAIGeminiGenerator
    HAS_GOOGLE_GEMINI = True
except ImportError:
    HAS_GOOGLE_GEMINI = False

from app.core.config import settings
from app.core.observability import get_metrics
from app.services.haystack_store import get_document_store
from app.services.embeddings import embedding_service
from app.core.database import AsyncSessionLocal
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Get metrics instance
try:
    metrics = get_metrics()
except:
    metrics = None


class QueryPipeline:
    """Haystack query pipeline for hybrid retrieval + reranking + generation."""
    
    def __init__(self):
        """Initialize query pipeline."""
        self.document_store = get_document_store()
        self.pipeline = self._build_pipeline()
        self._schema_checked = False
        logger.info("Query pipeline initialized")
    
    def _build_pipeline(self) -> Pipeline:
        """Build Haystack query pipeline with vector retrieval and optional reranking."""
        pipeline = Pipeline()
        
        # Add pgvector embedding retriever
        pipeline.add_component(
            "vector_retriever",
            PgvectorEmbeddingRetriever(document_store=self.document_store)
        )
        
        # Note: Hybrid search with BM25 requires in-memory document store
        # For production, vector search + reranker provides excellent results
        # Configuration flags are preserved for future implementation
        
        # Reranker (optional)
        if settings.rag_use_reranker:
            pipeline.add_component(
                "reranker",
                FixedSentenceTransformersSimilarityRanker(
                    model=settings.rag_reranker_model,
                    top_k=settings.rag_rerank_top_k
                )
            )
            pipeline.connect("vector_retriever.documents", "reranker.documents")
        
        # Prompt builder
        prompt_template = """
        Answer the following question based on the provided context. 
        Include citations using [1], [2], etc. format.
        
        Context:
        {% for doc in documents %}
        [{{ loop.index }}] {{ doc.content }}
        {% endfor %}
        
        Question: {{ query }}
        
        Answer:
        """
        
        pipeline.add_component(
            "prompt_builder",
            PromptBuilder(
                template=prompt_template,
                required_variables=["documents", "query"]
            )
        )
        
        # LLM Generator - use Google Gemini if available and configured, else OpenRouter
        if settings.rag_llm_provider == "google" and HAS_GOOGLE_GEMINI and settings.google_api_key:
            pipeline.add_component(
                "llm",
                GoogleAIGeminiGenerator(
                    api_key=Secret.from_token(settings.google_api_key),
                    model=settings.rag_llm_model,
                    generation_config={
                        "max_output_tokens": settings.rag_llm_max_tokens,
                        "temperature": settings.rag_llm_temperature
                    }
                )
            )
            logger.info(f"Using Google Gemini LLM: {settings.rag_llm_model}")
        else:
            # Fallback to OpenRouter
            pipeline.add_component(
                "llm",
                OpenAIGenerator(
                    api_key=Secret.from_token(settings.openrouter_api_key),
                    api_base_url="https://openrouter.ai/api/v1",
                    model=settings.rag_llm_model,
                    generation_kwargs={
                        "max_tokens": settings.rag_llm_max_tokens,
                        "temperature": settings.rag_llm_temperature
                    }
                )
            )
            logger.info(f"Using OpenRouter LLM: {settings.rag_llm_model}")
        
        # Connect to prompt builder and LLM
        if settings.rag_use_reranker:
            pipeline.connect("reranker.documents", "prompt_builder.documents")
        else:
            pipeline.connect("vector_retriever.documents", "prompt_builder.documents")
        
        pipeline.connect("prompt_builder", "llm")
        
        return pipeline
    
    async def run_async(
        self,
        query: str,
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Run query pipeline asynchronously.
        
        Args:
            query: User query
            top_k: Number of documents to retrieve
            filters: Metadata filters
            
        Returns:
            Query result with answer and citations
        """
        try:
            await self._ensure_haystack_compatibility()

            # Track vector search
            search_start = time.time()
            
            # Generate query embedding for vector search
            query_embedding = await embedding_service.embed_text(query)
            
            # Track embedding generation time
            if metrics:
                metrics.embedding_duration.observe(time.time() - search_start)
                metrics.embeddings_generated_total.inc()
            
            # Run pipeline with embedding-based retrieval
            pipeline_start = time.time()
            pipeline_inputs = {
                "vector_retriever": {
                    "query_embedding": query_embedding,
                    "top_k": top_k,
                    "filters": filters
                },
                "prompt_builder": {
                    "query": query
                }
            }
            
            # Add reranker query if enabled
            if settings.rag_use_reranker:
                pipeline_inputs["reranker"] = {"query": query}
            
            result = self.pipeline.run(pipeline_inputs)
            
            # Track vector search time
            if metrics:
                search_time = time.time() - search_start
                # Use "vector+reranker" label when reranker is enabled
                search_method = "vector+reranker" if settings.rag_use_reranker else "vector"
                metrics.vector_search_duration.labels(index_type=search_method).observe(search_time)
                metrics.vector_search_total.labels(index_type=search_method).inc()
            
            # Extract results
            answer = result.get("llm", {}).get("replies", [""])[0]
            
            # Get documents from appropriate stage
            if settings.rag_use_reranker:
                documents = result.get("reranker", {}).get("documents", [])
            else:
                documents = result.get("vector_retriever", {}).get("documents", [])
            
            # Track LLM request
            if metrics:
                llm_time = time.time() - pipeline_start
                metrics.llm_request_duration.labels(model=settings.rag_llm_model).observe(llm_time)
                metrics.llm_requests_total.labels(model=settings.rag_llm_model, status="success").inc()
            
            # Format response
            return {
                "answer": answer,
                "documents": [
                    {
                        "id": doc.id,
                        "content": doc.content,
                        "score": doc.score if hasattr(doc, "score") else 0.0,
                        "metadata": doc.meta
                    }
                    for doc in documents
                ],
                "model": settings.rag_llm_model
            }
            
        except Exception as e:
            logger.error(f"Query pipeline failed: {e}")
            raise
    
    async def retrieve_only(
        self,
        query: str,
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve documents without LLM generation (for search endpoint).
        
        Args:
            query: User query
            top_k: Number of documents to retrieve
            filters: Metadata filters
            
        Returns:
            List of retrieved documents
        """
        try:
            await self._ensure_haystack_compatibility()

            # Generate query embedding
            query_embedding = await embedding_service.embed_text(query)
            
            # Import retriever
            from haystack_integrations.components.retrievers.pgvector import PgvectorEmbeddingRetriever
            
            # Create retriever
            retriever = PgvectorEmbeddingRetriever(document_store=self.document_store)
            
            # Retrieve documents
            result = retriever.run(query_embedding=query_embedding, top_k=top_k, filters=filters)
            
            documents = result.get("documents", [])
            
            # Apply reranker if enabled
            if settings.rag_use_reranker and documents:
                from app.services.custom_reranker import FixedSentenceTransformersSimilarityRanker
                reranker = FixedSentenceTransformersSimilarityRanker(
                    model=settings.rag_reranker_model,
                    top_k=settings.rag_rerank_top_k
                )
                rerank_result = reranker.run(query=query, documents=documents)
                documents = rerank_result.get("documents", [])
            
            # Format documents
            return [
                {
                    "id": doc.id,
                    "content": doc.content,
                    "score": doc.score if hasattr(doc, "score") else 0.0,
                    "metadata": doc.meta
                }
                for doc in documents
            ]
            
        except Exception as e:
            logger.error(f"Retrieval failed: {e}")
            raise

    async def _ensure_haystack_compatibility(self) -> None:
        """
        Keep Haystack table schema compatible with PgvectorDocumentStore.

        Extra physical columns (like document_type) on haystack_rag_documents can
        break document deserialization. Persist classification in meta JSON instead.
        """
        if self._schema_checked:
            return

        async with AsyncSessionLocal() as session:
            # If a legacy document_type column exists, preserve values into meta first.
            await session.execute(
                text(
                    """
                    UPDATE haystack_rag_documents
                    SET meta = COALESCE(meta, '{}'::jsonb) || jsonb_build_object('document_type', document_type)
                    WHERE document_type IS NOT NULL
                      AND (meta->>'document_type') IS NULL;
                    """
                )
            )
            await session.execute(text("DROP INDEX IF EXISTS ix_haystack_rag_documents_document_type;"))
            await session.execute(text("ALTER TABLE haystack_rag_documents DROP COLUMN IF EXISTS document_type;"))
            await session.commit()

        self._schema_checked = True


# Singleton instance
query_pipeline = QueryPipeline()
