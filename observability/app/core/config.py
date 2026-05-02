"""Configuration settings for Observability service."""

from typing import Optional, List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore"  # Ignore extra env vars
    )
    
    # Service
    SERVICE_NAME: str = "aegisops-observability"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    VERSION: str = "0.1.0"
    
    # API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8003
    CORS_ORIGINS: str = '["http://localhost:3000"]'
    
    # PostgreSQL (Neon)
    DATABASE_URL: str = "postgresql+asyncpg://neondb_owner:npg_A53UTNzjXWLG@ep-withered-voice-a12b4zjr-pooler.ap-southeast-1.aws.neon.tech/neondb?ssl=require"
    MIGRATION_DATABASE_URL: Optional[str] = None
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 5
    
    # Redis (Upstash)
    REDIS_URL: str = "rediss://default:ATtNAAIncDE2Y2JlNzk4OWU2YTA0ZjNiYTBlZTQxZDk4YTkxNzk2YXAxMTUxODE@cheerful-mudfish-15181.upstash.io:6379"
    REDIS_HOST: str = "cheerful-mudfish-15181.upstash.io"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 3
    REDIS_PASSWORD: Optional[str] = None
    
    # Prometheus
    PROMETHEUS_URL: str = "http://localhost:9090"
    PROMETHEUS_PUSHGATEWAY_URL: Optional[str] = None
    PROMETHEUS_PORT: int = 9103
    PROMETHEUS_ENABLED: bool = True
    
    # Grafana
    GRAFANA_URL: str = "http://localhost:3001"
    GRAFANA_API_KEY: Optional[str] = None
    GRAFANA_ADMIN_USER: str = "admin"
    GRAFANA_ADMIN_PASSWORD: str = "aegisops123"
    
    # OpenTelemetry
    OTEL_ENABLED: bool = True
    OTEL_COLLECTOR_ENDPOINT: Optional[str] = "http://localhost:4317"
    OTEL_EXPORTER_OTLP_ENDPOINT: Optional[str] = None
    OTEL_EXPORTER_OTLP_PROTOCOL: str = "grpc"
    OTEL_SERVICE_NAME: str = "aegisops-observability"
    
    # Alertmanager
    ALERTMANAGER_URL: Optional[str] = "http://localhost:9093"
    
    # Sentry
    SENTRY_DSN: Optional[str] = None
    
    # Service endpoints
    AGENT_ORCHESTRATION_URL: str = "http://localhost:8002"
    CONTEXT_MANAGEMENT_URL: str = "http://localhost:8000"
    RAG_URL: str = "http://localhost:8001"
    USER_INTERFACE_URL: str = "http://localhost:3000"
    
    # Retention
    METRICS_RETENTION_DAYS: int = 30
    RAW_METRICS_RETENTION_HOURS: int = 24
    
    # Alerting (optional)
    SLACK_WEBHOOK_URL: Optional[str] = None
    ALERT_EMAIL_RECIPIENTS: Optional[str] = None
    
    # SMTP (for email alerts)
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    ALERT_FROM_EMAIL: str = "alerts@aegisops.local"
    
    # LLM (for RAG evaluation)
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    LLM_MODEL: str = "meta-llama/llama-3.2-3b-instruct:free"
    
    # Security
    SECRET_KEY: str = "change-me-in-production"


settings = Settings()
