"""Configuration management for RAG system."""
import os
from pathlib import Path
from typing import List, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Application
    version: str = "0.1.0"
    environment: str = "production"
    debug: bool = False

    # Database (PostgreSQL with pgvector)
    postgres_connection_string: str = Field(..., alias="POSTGRES_CONNECTION_STRING")
    database_url: str = Field(..., alias="DATABASE_URL")
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    sql_echo: bool = False

    # Redis
    redis_url: str = Field(..., alias="REDIS_URL")
    redis_rest_url: str = Field(default="", alias="REDIS_REST_URL")
    redis_rest_token: str = Field(default="", alias="REDIS_REST_TOKEN")

    # Cache TTLs
    context_cache_ttl: int = 604800
    embedding_cache_ttl: int = 2592000  # 30 days

    # Security
    secret_key: str = Field(..., alias="SECRET_KEY")
    rate_limit_requests: int = 100
    rate_limit_window: int = 60

    # Frontend
    frontend_url: str = "http://localhost:3000"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @field_validator("cors_origins")
    @classmethod
    def parse_cors_origins(cls, v: str) -> List[str]:
        return [origin.strip() for origin in v.split(",")]

    # OpenRouter Configuration (Backup)
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: str = "http://localhost:3000"
    openrouter_site_name: str = "RAG Service"

    # Google Vertex AI / Gemini Configuration (Primary)
    google_api_key: str = Field(..., alias="GOOGLE_API_KEY")

    # Google Drive
    google_service_account_json: str = "google-service-account.json"
    google_drive_folder_id: str = Field(..., alias="GOOGLE_DRIVE_FOLDER_ID")

    # RAG Embedding
    rag_embedding_model: str = "BAAI/bge-base-en-v1.5"
    rag_embedding_device: Literal["cpu", "cuda"] = "cpu"
    rag_embedding_dim: int = 768
    rag_batch_size: int = 32
    rag_max_seq_length: int = 512

    # RAG LLM (OpenRouter)
    rag_llm_provider: str = "openrouter"
    rag_llm_model: str = "nvidia/nemotron-3-nano-30b-a3b:free"
    rag_llm_temperature: float = 0.7
    rag_llm_max_tokens: int = 8000

    # Context LLM
    context_llm_provider: str = "openrouter"
    context_llm_model: str = "nvidia/nemotron-3-nano-30b-a3b:free"

    # Vector Store
    rag_index_type: str = "hnsw"
    rag_index_m: int = 16
    rag_index_ef_construction: int = 64
    rag_index_ef_search: int = 40
    rag_recreate_table: bool = False
    rag_table_name: str = "rag_documents"
    rag_vector_column: str = "embedding"

    # Retrieval
    rag_top_k: int = 20
    rag_rerank_top_k: int = 5
    rag_similarity_threshold: float = 0.7
    rag_use_hybrid_search: bool = True
    rag_bm25_weight: float = 0.3
    rag_vector_weight: float = 0.7

    # Reranker
    rag_use_reranker: bool = True
    rag_reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    rag_reranker_device: Literal["cpu", "cuda"] = "cpu"

    # Chunking
    rag_chunk_size: int = 512
    rag_chunk_overlap: int = 50
    rag_min_chunk_size: int = 100
    rag_max_chunk_size: int = 1000

    # Document Processing
    rag_supported_mimetypes: str = "application/pdf,text/plain,application/vnd.google-apps.document,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/markdown"
    rag_max_file_size_mb: int = 50

    @field_validator("rag_supported_mimetypes")
    @classmethod
    def parse_mimetypes(cls, v: str) -> List[str]:
        return [mt.strip() for mt in v.split(",")]

    # Indexing & Refresh
    rag_incremental_refresh: bool = True
    rag_refresh_interval_minutes: int = 30
    rag_batch_indexing: bool = True
    rag_index_batch_size: int = 100

    # Privacy & Confidentiality
    rag_enable_confidentiality_filter: bool = True
    rag_confidentiality_levels: str = "low,medium,high"
    rag_default_confidentiality: str = "medium"
    rag_redact_patterns: str = "password,api_key,secret,token,credential"

    @field_validator("rag_confidentiality_levels", "rag_redact_patterns")
    @classmethod
    def parse_comma_list(cls, v: str) -> List[str]:
        return [item.strip() for item in v.split(",")]

    # Evaluation
    rag_eval_enabled: bool = True
    rag_eval_dataset_path: str = "./eval/eval_dataset.json"
    rag_eval_metrics: str = "recall,precision,mrr,ndcg,faithfulness,hallucination_rate"
    rag_target_recall_at_20: float = 0.85
    rag_target_faithfulness: float = 0.9
    rag_max_hallucination_rate: float = 0.05

    @field_validator("rag_eval_metrics")
    @classmethod
    def parse_eval_metrics(cls, v: str) -> List[str]:
        return [metric.strip() for metric in v.split(",")]

    # Performance
    rag_cache_embeddings: bool = True
    rag_cache_results: bool = True
    rag_query_timeout_seconds: int = 30
    rag_index_timeout_seconds: int = 300
    rag_worker_concurrency: int = 4

    # OpenTelemetry
    otel_service_name: str = "rag-service"
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_exporter_otlp_protocol: str = "grpc"

    # Prometheus
    prometheus_enabled: bool = True
    prometheus_port: int = 8002

    # OpenSearch (optional)
    opensearch_enabled: bool = False
    opensearch_host: str = "localhost"
    opensearch_port: int = 9200
    opensearch_user: str = "admin"
    opensearch_password: str = "admin"
    opensearch_index_prefix: str = "rag-logs"
    opensearch_use_ssl: bool = False

    # Feature Flags
    enable_audit_log: bool = True
    rag_enable_streaming: bool = True
    rag_enable_citations: bool = True
    rag_enable_metadata_filters: bool = True

    # Token Budget
    token_budget: int = 4000
    rag_candidates: int = 10

    # Ranking Weights
    cosine_weight: float = 0.4
    recency_weight: float = 0.2
    preference_weight: float = 0.2
    route_weight: float = 0.2
    dup_penalty: float = 0.1

    # FastAPI Server
    rag_api_host: str = "0.0.0.0"
    rag_api_port: int = 8000
    rag_api_workers: int = 4
    rag_api_reload: bool = False


# Global settings instance
settings = Settings()

# Create necessary directories
Path("./logs").mkdir(exist_ok=True)
Path("./eval").mkdir(exist_ok=True)
Path("./data").mkdir(exist_ok=True)
