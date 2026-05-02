"""Pydantic schemas for MCP service."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    """Return current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


# ============== MCP Protocol Schemas ==============

class MCPTransport(str, Enum):
    """MCP transport types."""
    STDIO = "stdio"
    SSE = "sse"
    HTTP = "http"


class ToolInputSchema(BaseModel):
    """JSON Schema for tool input."""
    type: str = "object"
    properties: Dict[str, Any] = Field(default_factory=dict)
    required: List[str] = Field(default_factory=list)


class ToolDefinition(BaseModel):
    """MCP tool definition."""
    name: str
    description: str
    inputSchema: ToolInputSchema
    server_id: Optional[str] = None


class ResourceDefinition(BaseModel):
    """MCP resource definition."""
    uri: str
    name: str
    description: Optional[str] = None
    mimeType: Optional[str] = None


class PromptDefinition(BaseModel):
    """MCP prompt definition."""
    name: str
    description: Optional[str] = None
    arguments: List[Dict[str, Any]] = Field(default_factory=list)


class ToolCallRequest(BaseModel):
    """Request to call a tool."""
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class ToolCallResponse(BaseModel):
    """Response from a tool call."""
    content: List[Dict[str, Any]]
    isError: bool = False


class ResourceReadRequest(BaseModel):
    """Request to read a resource."""
    uri: str


class ResourceReadResponse(BaseModel):
    """Response from reading a resource."""
    contents: List[Dict[str, Any]]


class PromptGetRequest(BaseModel):
    """Request to get a prompt."""
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class PromptGetResponse(BaseModel):
    """Response from getting a prompt."""
    description: Optional[str] = None
    messages: List[Dict[str, Any]]


# ============== Server Schemas ==============

class ServerInfo(BaseModel):
    """MCP server information."""
    name: str
    version: str
    protocol_version: str = "2024-11-05"
    capabilities: Dict[str, Any] = Field(default_factory=dict)


class ServerStatus(str, Enum):
    """Server status."""
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    STARTING = "starting"


class ServerRegistration(BaseModel):
    """Server registration request."""
    server_id: str
    name: str
    description: Optional[str] = None
    transport: MCPTransport = MCPTransport.SSE
    endpoint: Optional[str] = None
    tools: List[ToolDefinition] = Field(default_factory=list)
    resources: List[ResourceDefinition] = Field(default_factory=list)
    prompts: List[PromptDefinition] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RegisteredServer(BaseModel):
    """Registered MCP server."""
    server_id: str
    name: str
    description: Optional[str] = None
    transport: MCPTransport
    endpoint: Optional[str] = None
    status: ServerStatus = ServerStatus.STOPPED
    tools: List[ToolDefinition] = Field(default_factory=list)
    resources: List[ResourceDefinition] = Field(default_factory=list)
    prompts: List[PromptDefinition] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    registered_at: datetime = Field(default_factory=utc_now)
    last_health_check: Optional[datetime] = None


# ============== Session Schemas ==============

class SessionCreate(BaseModel):
    """Create a new session."""
    server_id: str
    client_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Session(BaseModel):
    """MCP session."""
    session_id: str
    server_id: str
    client_id: Optional[str] = None
    tenant_id: Optional[str] = None
    status: str = "active"
    created_at: datetime = Field(default_factory=utc_now)
    last_activity: datetime = Field(default_factory=utc_now)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SessionList(BaseModel):
    """List of sessions."""
    sessions: List[Session]
    total: int


# ============== Gateway Schemas ==============

class GatewayRoute(BaseModel):
    """Gateway routing rule."""
    path_prefix: str
    server_id: str
    strip_prefix: bool = True
    timeout_seconds: int = 30
    retry_count: int = 3


class GatewayConfig(BaseModel):
    """Gateway configuration."""
    routes: List[GatewayRoute] = Field(default_factory=list)
    default_timeout: int = 30
    max_sessions_per_server: int = 100


# ============== OpenAPI Bridge Schemas ==============

class OpenAPISpec(BaseModel):
    """OpenAPI specification reference."""
    spec_id: str
    name: str
    version: str
    url: Optional[str] = None
    file_path: Optional[str] = None
    server_id: Optional[str] = None
    tools_generated: int = 0
    last_synced: Optional[datetime] = None


class OpenAPIConversionRequest(BaseModel):
    """Request to convert OpenAPI spec to MCP tools."""
    spec_url: Optional[str] = None
    spec_content: Optional[Dict[str, Any]] = None
    server_id: str
    include_paths: List[str] = Field(default_factory=list)
    exclude_paths: List[str] = Field(default_factory=list)


class OpenAPIConversionResult(BaseModel):
    """Result of OpenAPI to MCP conversion."""
    server_id: str
    tools_created: int
    tools: List[ToolDefinition]
    errors: List[str] = Field(default_factory=list)


# ============== Audit Schemas ==============

class AuditLogEntry(BaseModel):
    """Audit log entry."""
    timestamp: datetime = Field(default_factory=utc_now)
    tenant_id: Optional[str] = None
    server_id: str
    tool_id: Optional[str] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    action: str
    request_hash: Optional[str] = None
    outcome: str
    latency_ms: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ============== Health Schemas ==============

class HealthStatus(BaseModel):
    """Health check response."""
    status: str
    service: str
    version: str
    timestamp: datetime = Field(default_factory=utc_now)
    checks: Dict[str, Any] = Field(default_factory=dict)


class ServerHealthCheck(BaseModel):
    """Server health check result."""
    server_id: str
    status: ServerStatus
    latency_ms: Optional[float] = None
    last_check: datetime = Field(default_factory=utc_now)
    error: Optional[str] = None
