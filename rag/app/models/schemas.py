"""Pydantic schemas for API requests and responses."""
from datetime import datetime
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """Search request schema."""
    query: str = Field(..., description="Search query")
    top_k: Optional[int] = Field(None, description="Number of results to return")
    filters: Optional[Dict[str, Any]] = Field(None, description="Metadata filters")
    use_hybrid: Optional[bool] = Field(None, description="Use hybrid search")
    use_reranker: Optional[bool] = Field(None, description="Use reranker")


class SearchResult(BaseModel):
    """Search result schema."""
    id: str
    content: str
    title: Optional[str]
    source: Optional[str]
    file_id: Optional[str]
    file_path: Optional[str]
    chunk_index: int
    total_chunks: int
    confidentiality_level: str
    score: float
    retrieval_method: str
    metadata: Dict[str, Any] = {}


class SearchResponse(BaseModel):
    """Search response schema."""
    query: str
    results: List[SearchResult]
    total_results: int
    retrieval_time_ms: float


class AskRequest(BaseModel):
    """Ask question request schema."""
    query: str = Field(..., description="Question to ask")
    top_k: Optional[int] = Field(None, description="Number of context documents")
    filters: Optional[Dict[str, Any]] = Field(None, description="Metadata filters")
    stream: Optional[bool] = Field(False, description="Stream response")
    system_prompt: Optional[str] = Field(None, description="Custom system prompt")


class Citation(BaseModel):
    """Citation schema."""
    index: int
    title: str
    source: str
    file_id: Optional[str] = None
    file_path: Optional[str] = None


class AskResponse(BaseModel):
    """Ask response schema."""
    query: str
    answer: str
    citations: List[Citation]
    context_documents: List[SearchResult]
    model: str
    retrieval_time_ms: float
    generation_time_ms: float
    total_time_ms: float


class ReindexRequest(BaseModel):
    """Reindex request schema."""
    job_type: str = Field("full", description="Job type: full or incremental")


class ReindexResponse(BaseModel):
    """Reindex response schema."""
    job_id: str
    job_type: str
    status: str
    message: str


class JobStatus(BaseModel):
    """Job status schema."""
    job_id: str
    job_type: str
    status: str
    total_files: int
    processed_files: int
    failed_files: int
    total_chunks: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    duration_seconds: Optional[float]
    error_message: Optional[str]


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    environment: str
    database: bool
    redis: bool
    embedding_model: str
    llm_model: str


class StatsResponse(BaseModel):
    """Statistics response."""
    total_documents: int
    total_files: int
    total_chunks: int
    embedding_model: str
    embedding_dim: int
    cache_stats: Dict[str, Any]


class EvalMetrics(BaseModel):
    """Evaluation metrics schema."""
    recall_at_k: Optional[float] = None
    precision_at_k: Optional[float] = None
    mrr: Optional[float] = None
    ndcg: Optional[float] = None
    faithfulness: Optional[float] = None
    hallucination_rate: Optional[float] = None


class EvalResponse(BaseModel):
    """Evaluation response schema."""
    eval_id: str
    eval_type: str
    metrics: EvalMetrics
    num_queries: int
    dataset_name: str
    created_at: datetime
