"""API router for search and retrieval endpoints."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
import time

from app.core.database import get_db
from app.core.config import settings
from app.services.haystack_query import query_pipeline
from app.models.schemas import SearchRequest, SearchResponse, SearchResult

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    session: AsyncSession = Depends(get_db)
):
    """Search for relevant documents using Haystack."""
    start_time = time.time()
    
    try:
        # Use retrieval-only method (no LLM generation)
        documents = await query_pipeline.retrieve_only(
            query=request.query,
            top_k=request.top_k or settings.rag_top_k,
            filters=request.filters
        )
        
        retrieval_time = (time.time() - start_time) * 1000
        
        # Convert to response schema
        results = [
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
                retrieval_method="haystack_vector",
                metadata=doc["metadata"]
            )
            for doc in documents
        ]
        
        return SearchResponse(
            query=request.query,
            results=results,
            total_results=len(results),
            retrieval_time_ms=retrieval_time
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {str(e)}"
        )
