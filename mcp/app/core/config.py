"""Configuration settings for MCP service."""

import json
from typing import Any, Dict, List, Optional

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    # Service
    SERVICE_NAME: str = "aegisops-mcp"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    VERSION: str = "0.1.0"

    # API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8005
    CORS_ORIGINS: List[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> List[str]:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [v]
        return v

    # Database
    DATABASE_URL: str = ""
    MIGRATION_DATABASE_URL: str = ""
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 5

    # Redis
    REDIS_URL: str = ""
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 5
    REDIS_PASSWORD: Optional[str] = None

    # MCP Server
    MCP_SERVER_NAME: str = "aegisops-mcp-server"
    MCP_SERVER_VERSION: str = "0.1.0"
    MCP_TRANSPORT: str = "sse"
    MCP_SSE_PATH: str = "/sse"
    MCP_STDIO_ENABLED: bool = True

    # MCP Gateway
    MCP_GATEWAY_ENABLED: bool = True
    MCP_GATEWAY_HOST: str = "0.0.0.0"
    MCP_GATEWAY_PORT: int = 8006
    MCP_SESSION_TTL: int = 3600
    MCP_MAX_SESSIONS: int = 1000
    MCP_HEALTH_CHECK_INTERVAL: int = 30

    # OpenAPI Bridge
    OPENAPI_BRIDGE_ENABLED: bool = True
    OPENAPI_SPECS_PATH: str = "./specs"
    OPENAPI_CACHE_TTL: int = 3600

    # Service Endpoints
    AGENT_ORCHESTRATION_URL: str = "http://localhost:8002"
    CONTEXT_MANAGEMENT_URL: str = "http://localhost:8000"
    RAG_SERVICE_URL: str = "http://localhost:8001"
    OBSERVABILITY_URL: str = "http://localhost:8003"
    USER_MANAGEMENT_URL: str = "http://localhost:8004"
    PROMETHEUS_MCP_ENABLED: bool = False
    PROMETHEUS_MCP_URL: str = "http://localhost:8080"
    PROMETHEUS_MCP_TIMEOUT_SECONDS: int = 30
    PROMETHEUS_MCP_BEARER_TOKEN: str = ""
    NEWRELIC_MCP_ENABLED: bool = False
    NEWRELIC_MCP_URL: str = "https://mcp.newrelic.com"
    NEWRELIC_MCP_TIMEOUT_SECONDS: int = 30
    NEWRELIC_MCP_BEARER_TOKEN: str = ""
    ALERTMANAGER_MCP_ENABLED: bool = False
    ALERTMANAGER_MCP_URL: str = "http://localhost:8008"
    ALERTMANAGER_MCP_TIMEOUT_SECONDS: int = 30
    ALERTMANAGER_MCP_BEARER_TOKEN: str = ""
    ALERTMANAGER_MCP_USERNAME: str = ""
    ALERTMANAGER_MCP_PASSWORD: str = ""
    QUICKWIT_ENABLED: bool = False
    QUICKWIT_DEV_URL: str = ""
    QUICKWIT_PROD_URL: str = ""
    QUICKWIT_TIMEOUT_SECONDS: int = 30
    QUICKWIT_MAX_HITS: int = 50
    ELASTICSEARCH_MCP_ENABLED: bool = False
    ELASTICSEARCH_MCP_URL: str = "http://localhost:9200"
    ELASTICSEARCH_MCP_TIMEOUT_SECONDS: int = 30
    ELASTICSEARCH_MCP_VERIFY_TLS: bool = False
    ELASTICSEARCH_MCP_USERNAME: str = ""
    ELASTICSEARCH_MCP_PASSWORD: str = ""
    ELASTICSEARCH_MCP_API_KEY: str = ""
    ELASTICSEARCH_MCP_MAX_HITS: int = 50
    ISTIO_MCP_ENABLED: bool = False
    ISTIO_MCP_KUBECONFIG_PATH: str = ""
    ISTIO_MCP_CONTEXT: str = ""
    ISTIO_MCP_IN_CLUSTER: bool = False
    KUBERNETES_MCP_ENABLED: bool = False
    # flux = Flux159/mcp-server-kubernetes (kubectl); containers = ghcr.io/containers/kubernetes-mcp-server (Go API)
    KUBERNETES_MCP_BACKEND: str = "flux"
    KUBERNETES_MCP_URL: str = "http://localhost:8087"
    KUBERNETES_MCP_TIMEOUT_SECONDS: int = 30
    KUBERNETES_MCP_BEARER_TOKEN: str = ""
    # Register gateway tools from upstream tools/list (prefix kubernetes_flux_* or kubernetes_native_*)
    KUBERNETES_MCP_EXPOSE_UPSTREAM_TOOLS: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "KUBERNETES_MCP_EXPOSE_UPSTREAM_TOOLS",
            "KUBERNETES_MCP_EXPOSE_FLUX_TOOLS",
        ),
    )
    # If false, omit destructive upstream tools (delete, uninstall, etc.)
    KUBERNETES_MCP_UPSTREAM_INCLUDE_DESTRUCTIVE: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "KUBERNETES_MCP_UPSTREAM_INCLUDE_DESTRUCTIVE",
            "KUBERNETES_MCP_FLUX_TOOLS_INCLUDE_DESTRUCTIVE",
        ),
    )
    # In-process Kubernetes client for write/debug tools (exec, rollout restart).
    # Uses same kubeconfig as Istio when LOCAL_KUBECONFIG_PATH is empty.
    KUBERNETES_MCP_LOCAL_WRITE_ENABLED: bool = False
    KUBERNETES_MCP_LOCAL_KUBECONFIG_PATH: str = ""
    KUBERNETES_MCP_LOCAL_CONTEXT: str = ""
    KUBERNETES_MCP_LOCAL_IN_CLUSTER: bool = False
    AWS_MCP_ENABLED: bool = False
    AWS_MCP_URL: str = "http://localhost:8088"
    AWS_MCP_TIMEOUT_SECONDS: int = 30
    AWS_MCP_BEARER_TOKEN: str = ""
    GRAPH_MCP_ENABLED: bool = False
    GRAPH_MCP_NEO4J_URI: str = ""
    GRAPH_MCP_NEO4J_USER: str = "neo4j"
    GRAPH_MCP_NEO4J_PASSWORD: str = ""
    GRAPH_MCP_NEO4J_DATABASE: str = "neo4j"
    # Enrichment: use Prometheus API for metrics (defaults to PROMETHEUS_MCP_URL)
    GRAPH_ENRICHMENT_PROMETHEUS_URL: str = ""
    # MCP base URL for ingestion to call Istio/other tools (e.g. http://localhost:8005 when in-container)
    GRAPH_ENRICHMENT_MCP_URL: str = ""
    # Istio VirtualService listing: one namespace or comma/semicolon-separated (e.g. flights,activity)
    GRAPH_ENRICHMENT_ISTIO_NAMESPACE: str = "default"
    # If true, list VirtualServices cluster-wide (needs cluster RBAC; ignores namespace except for docs)
    GRAPH_ENRICHMENT_ISTIO_CLUSTER_WIDE: bool = False
    # Optional: explicit API key for HTTP self-calls when not using in-process gateway (CLI / scripts)
    GRAPH_ENRICHMENT_MCP_API_KEY: str = ""
    SERVICENOW_MCP_ENABLED: bool = False
    SERVICENOW_MCP_TIMEOUT_SECONDS: int = 30
    SNOW_INSTANCE_URL: str = ""
    SNOW_USERNAME: str = ""
    SNOW_PASSWORD: str = ""

    # Security
    SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_MINUTES: int = 60
    RBAC_ENABLED: bool = True
    API_KEY_HEADER: str = "X-API-Key"
    API_KEYS: List[str] = Field(default_factory=list)

    @field_validator("API_KEYS", mode="before")
    @classmethod
    def parse_api_keys(cls, v: Any) -> List[str]:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [v] if v else []
        return v

    # Tool Permissions
    TOOL_PERMISSIONS: Dict[str, str] = Field(default_factory=dict)

    @field_validator("TOOL_PERMISSIONS", mode="before")
    @classmethod
    def parse_tool_permissions(cls, v: Any) -> Dict[str, str]:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return {}
        return v

    # Observability
    OTEL_ENABLED: bool = True
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"
    OTEL_SERVICE_NAME: str = "aegisops-mcp"
    PROMETHEUS_ENABLED: bool = True
    PROMETHEUS_PORT: int = 9005
    SENTRY_DSN: Optional[str] = None

    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_WINDOW: int = 60

    # Audit
    AUDIT_ENABLED: bool = True
    AUDIT_LOG_TOOL_CALLS: bool = True
    AUDIT_LOG_SESSIONS: bool = True


settings = Settings()
