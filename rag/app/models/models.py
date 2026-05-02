"""Database models for RAG system."""
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, String, Integer, DateTime, Float, Text, JSON, Index, Boolean
)
from sqlalchemy.ext.declarative import declarative_base
from pgvector.sqlalchemy import Vector

Base = declarative_base()


class Document(Base):
    """Document model with vector embeddings."""
    
    __tablename__ = "rag_documents"
    
    # Primary key
    id = Column(String(255), primary_key=True)
    
    # Content
    content = Column(Text, nullable=False)
    
    # Metadata
    title = Column(String(500))
    source = Column(String(500))
    file_id = Column(String(255))
    file_path = Column(String(1000))
    mime_type = Column(String(100))
    
    # Chunking info
    chunk_index = Column(Integer, default=0)
    total_chunks = Column(Integer, default=1)
    
    # Confidentiality
    confidentiality_level = Column(String(50), default="medium")
    
    # Vector embedding (768 dimensions for BGE-base)
    embedding = Column(Vector(768))
    
    # Additional metadata as JSON (renamed to avoid SQLAlchemy conflict)
    meta_data = Column(JSON, default={})
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    modified_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    indexed_at = Column(DateTime, default=datetime.utcnow)
    
    # File info
    file_size = Column(Integer)
    file_modified_time = Column(DateTime)
    
    # Tracking
    embedding_model = Column(String(100))
    embedding_dim = Column(Integer, default=768)
    
    # Soft delete
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime, nullable=True)
    
    # Indexes
    __table_args__ = (
        Index("ix_rag_documents_file_id", "file_id"),
        Index("ix_rag_documents_source", "source"),
        Index("ix_rag_documents_confidentiality", "confidentiality_level"),
        Index("ix_rag_documents_created_at", "created_at"),
        Index("ix_rag_documents_is_deleted", "is_deleted"),
        # HNSW index for vector similarity search
        Index(
            "ix_rag_documents_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"}
        ),
    )


class IndexingJob(Base):
    """Track indexing jobs."""
    
    __tablename__ = "rag_indexing_jobs"
    
    id = Column(String(255), primary_key=True)
    job_type = Column(String(50))  # full, incremental, single_file
    status = Column(String(50))  # pending, running, completed, failed
    
    # Stats
    total_files = Column(Integer, default=0)
    processed_files = Column(Integer, default=0)
    failed_files = Column(Integer, default=0)
    total_chunks = Column(Integer, default=0)
    
    # Timing
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    duration_seconds = Column(Float)
    
    # Details
    error_message = Column(Text)
    job_metadata = Column(JSON, default={})
    
    created_at = Column(DateTime, default=datetime.utcnow)


class QueryLog(Base):
    """Log RAG queries for analysis and evaluation."""
    
    __tablename__ = "rag_query_logs"
    
    id = Column(String(255), primary_key=True)
    query = Column(Text, nullable=False)
    
    # Retrieval
    num_candidates = Column(Integer)
    num_results = Column(Integer)
    retrieval_method = Column(String(50))  # vector, bm25, hybrid
    
    # Results
    top_scores = Column(JSON)
    result_ids = Column(JSON)
    
    # Performance
    retrieval_time_ms = Column(Float)
    rerank_time_ms = Column(Float)
    generation_time_ms = Column(Float)
    total_time_ms = Column(Float)
    
    # Metadata
    user_id = Column(String(255))
    session_id = Column(String(255))
    query_metadata = Column(JSON, default={})
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index("ix_rag_query_logs_user_id", "user_id"),
        Index("ix_rag_query_logs_session_id", "session_id"),
        Index("ix_rag_query_logs_created_at", "created_at"),
    )


class EvaluationResult(Base):
    """Store evaluation results."""
    
    __tablename__ = "rag_evaluation_results"
    
    id = Column(String(255), primary_key=True)
    eval_type = Column(String(50))  # retrieval, generation, end_to_end
    
    # Metrics
    recall_at_k = Column(Float)
    precision_at_k = Column(Float)
    mrr = Column(Float)
    ndcg = Column(Float)
    faithfulness = Column(Float)
    hallucination_rate = Column(Float)
    
    # Additional metrics
    metrics = Column(JSON, default={})
    
    # Context
    dataset_name = Column(String(255))
    num_queries = Column(Integer)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index("ix_rag_eval_results_eval_type", "eval_type"),
        Index("ix_rag_eval_results_created_at", "created_at"),
    )
