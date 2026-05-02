"""API router for Q&A endpoints using Haystack."""
import time
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.core.observability import get_metrics
from app.services.haystack_query import query_pipeline
from app.models.models import QueryLog
from app.models.schemas import AskRequest, AskResponse, Citation, SearchResult

router = APIRouter(prefix="/ask", tags=["ask"])
logger = logging.getLogger(__name__)

# Get metrics instance
try:
    metrics = get_metrics()
except:
    metrics = None


@router.post("", response_model=AskResponse)
async def ask(
    request: AskRequest,
    session: AsyncSession = Depends(get_db)
):
    """Ask a question and get an answer with citations using Haystack."""
    if request.stream:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use /ask/stream endpoint for streaming responses"
        )
    
    start_time = time.time()
    
    # Track RAG query
    if metrics:
        metrics.rag_queries_total.labels(status="started").inc()
    
    try:
        # Use Haystack query pipeline (retrieval + rerank + generation)
        retrieval_start = time.time()
        result = await query_pipeline.run_async(
            query=request.query,
            top_k=request.top_k or settings.rag_top_k,
            filters=request.filters
        )
        retrieval_time = (time.time() - retrieval_start) * 1000
        
        # Track query duration
        if metrics:
            metrics.rag_query_duration.labels(stage="total").observe(retrieval_time / 1000)
        
        if not result.get("documents"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No relevant documents found"
            )
        
        # Extract answer and documents from Haystack result
        answer = result["answer"]
        documents = result["documents"]
        
        # Track documents retrieved
        if metrics:
            metrics.rag_documents_retrieved.observe(len(documents))
            metrics.rag_queries_total.labels(status="success").inc()
        
        # Parse citations from answer
        citations = []
        for idx, doc in enumerate(documents, 1):
            if f"[{idx}]" in answer:
                citations.append(Citation(
                    index=idx,
                    title=doc["metadata"].get("title", ""),
                    source=doc["metadata"].get("source", "google_drive"),
                    file_id=doc["metadata"].get("file_id", ""),
                    file_path=doc["metadata"].get("file_path", "")
                ))
        
        generation_time = retrieval_time  # Haystack pipeline includes generation
        total_time = (time.time() - start_time) * 1000
        
        # Log query
        query_log = QueryLog(
            id=str(time.time()),
            query=request.query,
            num_candidates=len(documents),
            num_results=len(citations),
            retrieval_method="haystack_hybrid",
            retrieval_time_ms=retrieval_time,
            generation_time_ms=generation_time,
            total_time_ms=total_time,
            result_ids=[doc["id"] for doc in documents],
            top_scores=[doc["score"] for doc in documents]
        )
        session.add(query_log)
        await session.commit()
        
        # Convert documents to SearchResult
        context_documents = [
            SearchResult(
                id=doc["id"],
                content=doc["content"],
                title=doc["metadata"].get("title"),
                source=doc["metadata"].get("source", "google_drive"),
                file_id=doc["metadata"].get("file_id"),
                file_path=doc["metadata"].get("file_path"),
                chunk_index=doc["metadata"].get("chunk_index", 0),
                total_chunks=doc["metadata"].get("total_chunks", 1),
                confidentiality_level=doc["metadata"].get("confidentiality_level", "low"),
                score=doc["score"],
                retrieval_method="haystack_hybrid",
                metadata=doc["metadata"]
            )
            for doc in documents
        ]
        
        return AskResponse(
            query=request.query,
            answer=answer,
            citations=citations,
            context_documents=context_documents,
            model=result["model"],
            retrieval_time_ms=retrieval_time,
            generation_time_ms=generation_time,
            total_time_ms=total_time
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ask failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Question answering failed: {str(e)}"
        )


@router.post("/stream")
async def ask_stream(
    request: AskRequest,
    session: AsyncSession = Depends(get_db)
):
    """Ask a question with streaming response (not yet implemented for Haystack)."""
    
    async def generate_stream() -> AsyncIterator[str]:
        try:
            yield "data: Haystack streaming not yet implemented. Use non-streaming endpoint.\n\n"
            yield "data: [DONE]\n\n"
            
        except Exception as e:
            logger.error(f"Streaming failed: {e}")
            yield f"data: Error: {str(e)}\n\n"
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream"
    )
