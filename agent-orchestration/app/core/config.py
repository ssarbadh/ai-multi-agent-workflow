"""Application configuration using Pydantic settings."""

import json
from typing import List, Union
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore"
    )
    
    # Service
    SERVICE_NAME: str = "agent-orchestration"
    SERVICE_VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    
    # API
    HOST: str = "0.0.0.0"
    PORT: int = 8002
    CORS_ORIGINS: Union[List[str], str] = Field(
        default_factory=lambda: ["http://34.102.17.210:3000"]
    )
    
    @field_validator('CORS_ORIGINS', mode='before')
    @classmethod
    def parse_cors_origins(cls, v):
        """Parse CORS_ORIGINS from various formats."""
        if isinstance(v, str):
            # If it's "*", return as list with single wildcard
            if v.strip() == "*":
                return ["*"]
            # Try JSON format first
            if v.startswith('['):
                try:
                    return json.loads(v)
                except json.JSONDecodeError:
                    pass
            # Try comma-separated format
            origins = [origin.strip() for origin in v.split(',') if origin.strip()]
            return origins if origins else ["*"]
        return v if v else ["*"]
    
    # Database
    DATABASE_URL: str
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10
    
    # Redis
    REDIS_URL: str
    REDIS_MAX_CONNECTIONS: int = 50
    REDIS_SOCKET_TIMEOUT: int = 30  # Increased from 5 to 30 seconds
    REDIS_SOCKET_CONNECT_TIMEOUT: int = 10  # Increased from 5 to 10 seconds
    
    # Context Management Service
    CONTEXT_MGMT_URL: str = "http://localhost:8000"
    CONTEXT_MGMT_TIMEOUT: int = 30
    
    # RAG Service
    RAG_SERVICE_URL: str = "http://localhost:8001"
    RAG_SERVICE_TIMEOUT: int = 30
    
    # MCP Service
    MCP_SERVICE_URL: str = "http://localhost:8005"
    MCP_SERVICE_TIMEOUT: int = 60
    MCP_API_KEY: str = ""
    MCP_API_KEY_HEADER: str = "X-API-Key"
    
    # Observability Service
    OBSERVABILITY_SERVICE_URL: str = "http://localhost:8003"
    OBSERVABILITY_SERVICE_TIMEOUT: int = 30
    
    # LLM Configuration - Must be set via environment variables
    LLM_PROVIDER: str  # e.g., "google", "openai", "openrouter"
    LLM_MODEL: str  # e.g., "gemini-1.5-flash", "gpt-4", etc.
    LLM_TEMPERATURE: float = 0.7
    LLM_MAX_TOKENS: int = 4096
    LLM_API_KEY: str
    LLM_BASE_URL: str  # Provider-specific base URL
    
    # ServiceNow
    SNOW_INSTANCE_URL: str
    SNOW_USERNAME: str
    SNOW_PASSWORD: str
    SNOW_API_VERSION: str = "v1"
    SNOW_TIMEOUT: int = 30
    
    # Email
    SMTP_HOST: str
    SMTP_PORT: int = 587
    SMTP_USERNAME: str
    SMTP_PASSWORD: str
    SMTP_FROM_EMAIL: str
    SMTP_USE_TLS: bool = True
    
    # VMware
    VMWARE_HOST: str = ""
    VMWARE_USERNAME: str = ""
    VMWARE_PASSWORD: str = ""
    VMWARE_PORT: int = 443
    VMWARE_VERIFY_SSL: bool = False
    
    # AWS
    AWS_REGION: str = "ap-south-1"
    AWS_DEFAULT_REGION: str = "ap-south-1"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_ACCOUNT_ID: str = ""
    
    # AWS S3 Configuration
    AWS_S3_BUCKET: str = "aegisops-artifacts"
    AWS_S3_ARTIFACT_PREFIX: str = "agent-orchestration"
    
    # AWS CloudWatch Configuration
    AWS_CLOUDWATCH_LOG_GROUP: str = "/aegisops/agent-orchestration"
    AWS_CLOUDWATCH_NAMESPACE: str = "AegisOps/AgentOrchestration"
    AWS_CLOUDWATCH_RETENTION_DAYS: int = 30
    
    # AWS SSM Configuration
    AWS_SSM_COMMAND_TIMEOUT: int = 300
    
    # Azure
    AZURE_SUBSCRIPTION_ID: str = ""
    AZURE_TENANT_ID: str = ""
    AZURE_CLIENT_ID: str = ""
    AZURE_CLIENT_SECRET: str = ""
    
    # GCP
    GCP_PROJECT_ID: str = ""
    GCP_CREDENTIALS_PATH: str = "./gcp-credentials.json"
    
    # Kubernetes
    K8S_CONFIG_PATH: str = "~/.kube/config"
    K8S_CONTEXT: str = "default"
    
    # GitHub/DevOps
    GITHUB_TOKEN: str = ""
    GITHUB_USERNAME: str = ""
    GITHUB_ORG: str = ""
    GITHUB_REPO: str = ""
    
    # DockerHub (for CI/CD)
    DOCKERHUB_USERNAME: str = ""
    DOCKERHUB_TOKEN: str = ""
    
    # Kubernetes (base64 encoded kubeconfig)
    KUBECONFIG_BASE64: str = ""
    
    # VM Execution
    VM_EXEC_ENABLED: bool = True
    VM_EXEC_TIMEOUT: int = 300
    VM_EXEC_MAX_OUTPUT_SIZE: int = 10485760
    VM_EXEC_DOCKER_IMAGE: str = "ubuntu:22.04"
    VM_EXEC_K8S_NAMESPACE: str = "agent-exec"
    
    # Security
    VAULT_URL: str = "http://localhost:8200"
    VAULT_TOKEN: str = ""
    SECRET_MASKING_ENABLED: bool = True
    SECRET_PATTERNS: List[str] = Field(
        default_factory=lambda: ["password", "token", "key", "secret", "credential"]
    )
    
    # RBAC
    RBAC_ENABLED: bool = True
    RBAC_DEFAULT_ROLE: str = "viewer"
    RBAC_ADMIN_USERS: List[str] = Field(default_factory=list)
    
    # LangSmith (LangGraph + traceable LLM spans). Set LANGCHAIN_TRACING_V2=true and LANGCHAIN_API_KEY.
    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_API_KEY: str = ""
    LANGCHAIN_PROJECT: str = "aegisops-sre-multi-agent"
    LANGCHAIN_ENDPOINT: str = ""  # e.g. https://api.smith.langchain.com or EU endpoint

    # Observability
    OTEL_ENABLED: bool = True
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"
    OTEL_SERVICE_NAME: str = "agent-orchestration"
    PROMETHEUS_PORT: int = 9002
    SENTRY_DSN: str = ""
    
    # Performance
    MAX_CONCURRENT_RUNS: int = 100
    CHECKPOINT_INTERVAL: int = 5
    IDEMPOTENCY_TTL: int = 3600
    SSE_HEARTBEAT_INTERVAL: int = 30
    SSE_RECONNECT_TIMEOUT: int = 60
    
    # Approval & Gates
    APPROVAL_TIMEOUT: int = 3600
    PASSWORD_PROMPT_TIMEOUT: int = 300
    HUMAN_IN_LOOP_ENABLED: bool = True

    # SRE Multi-Agent
    SRE_MULTI_STATE_TTL_SECONDS: int = 86400
    SRE_CONFIDENCE_WEB_THRESHOLD: float = 0.7
    SRE_WEB_SEARCH_TIMEOUT_SECONDS: int = 10
    # Comma-separated (e.g. kubernetes,istio) — not JSON arrays: dotenv strips quotes and breaks ["a"] for List fields.
    SRE_WEB_SEARCH_DEFAULT_VENDORS: str = "kubernetes"
    SRE_WEB_SEARCH_DEFAULT_CLOUDS: str = "aws"
    SRE_WEB_SEARCH_DEFAULT_REGION: str = "ap-south-1"
    SRE_ALLOWED_ENVIRONMENTS: str = "dev,staging,prod"
    SRE_DEFAULT_INCIDENT_ENVIRONMENT: str = ""
    SRE_DEFAULT_CLOUD_PROVIDERS: str = ""
    SRE_DEFAULT_RESOURCE_TYPES: str = ""
    SRE_DEFAULT_REGIONS: str = ""
    SRE_CLOUD_PROBE_TOP_N: int = 2
    SRE_CAPABILITY_CONTRACTS_PATH: str = "app/prompts/sre_multi_agent/capability_contracts.yaml"
    SRE_PROMPT_CATALOG_PATH: str = "app/prompts/sre_multi_agent/catalog.yaml"
    SRE_USE_MCP_FOR_CONTEXT_AGGREGATION: bool = True
    # Optional comma-separated namespace fallback list for Istio lookups.
    # Example: "hotels,devops,istio-system"
    SRE_ISTIO_VIRTUALSERVICE_NAMESPACES: str = ""
    # When true, query cluster-wide VirtualServices as a final fallback.
    SRE_ISTIO_VIRTUALSERVICE_CLUSTER_WIDE: bool = False
    # Optional: run nslookup/dig from a debug pod via kubernetes_exec_in_pod (requires MCP local write + RBAC).
    SRE_DEBUG_POD_DNS_CHECKS_ENABLED: bool = False
    SRE_DEBUG_POD_NAMESPACE: str = ""
    SRE_DEBUG_POD_NAME: str = ""
    SRE_DEBUG_POD_CONTAINER: str = ""
 
    # Context Graph (Neo4j)
    NEO4J_URI: str = ""
    NEO4J_USERNAME: str = ""
    NEO4J_PASSWORD: str = ""
    NEO4J_DATABASE: str = "neo4j"
    
    # Decision Matrix
    DECISION_MATRIX_ENABLED: bool = True
    DECISION_MATRIX_THRESHOLD: float = 0.7
    
    # Confidentiality
    CONFIDENTIALITY_ENABLED: bool = True
    CONFIDENTIALITY_THRESHOLD_LOW: float = 0.3
    CONFIDENTIALITY_THRESHOLD_MEDIUM: float = 0.6
    CONFIDENTIALITY_THRESHOLD_HIGH: float = 0.8


settings = Settings()
