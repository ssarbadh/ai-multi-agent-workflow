"""Pydantic schemas for API request/response validation."""

from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, ConfigDict

from app.models.models import RunStatus, RequestType, ApprovalStatus


# Request schemas
class OrchestrationRequest(BaseModel):
    """Request to start agent orchestration."""
    
    session_id: str = Field(..., description="Session ID")
    user_id: str = Field(..., description="User ID")
    message: str = Field(..., description="User message/request")
    priority: str = Field(default="medium", description="Priority: low, medium, high, critical")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional metadata")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "session_id": "sess_123",
            "user_id": "user_456",
            "message": "Create a new VM with 4 CPUs and 8GB RAM in production",
            "priority": "medium",
            "metadata": {"department": "engineering"}
        }
    })


class ApprovalResponse(BaseModel):
    """Response to an approval request."""
    
    approval_id: str = Field(..., description="Approval ID")
    approved: bool = Field(..., description="Whether approved")
    response: Optional[str] = Field(default=None, description="Response text (for password/input)")
    comment: Optional[str] = Field(default=None, description="Optional comment")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "approval_id": "appr_789",
            "approved": True,
            "response": None,
            "comment": "Approved for production deployment"
        }
    })


class VMCommandRequest(BaseModel):
    """Request to execute VM command."""
    
    run_id: str = Field(..., description="Run ID")
    command: str = Field(..., description="Command to execute")
    working_directory: Optional[str] = Field(default=None, description="Working directory")
    environment: Optional[Dict[str, str]] = Field(default=None, description="Environment variables")
    timeout_seconds: int = Field(default=300, description="Timeout in seconds")


# Response schemas
class RunResponse(BaseModel):
    """Agent run response."""
    
    id: str
    session_id: str
    user_id: str
    request_type: RequestType
    status: RunStatus
    title: str
    description: Optional[str] = None
    priority: str
    routed_to: Optional[str] = None
    routing_confidence: Optional[float] = None
    snow_ticket_id: Optional[str] = None
    snow_ticket_number: Optional[str] = None
    snow_ticket_url: Optional[str] = None
    current_node: Optional[str] = None
    confidentiality_score: Optional[float] = None
    confidentiality_level: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    tokens_used: int = 0
    created_at: datetime
    updated_at: datetime
    metadata: Optional[Dict[str, Any]] = None
    
    model_config = ConfigDict(from_attributes=True)


class ApprovalResponseSchema(BaseModel):
    """Approval response schema."""
    
    id: str
    run_id: str
    approval_type: str
    prompt: str
    context: Optional[Dict[str, Any]] = None
    status: ApprovalStatus
    response: Optional[str] = None
    approved_by: Optional[str] = None
    requested_at: datetime
    responded_at: Optional[datetime] = None
    wait_time_seconds: Optional[float] = None
    timeout_seconds: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None
    
    model_config = ConfigDict(from_attributes=True)


class VMExecutionResponse(BaseModel):
    """VM execution response."""
    
    id: str
    run_id: str
    command: str
    working_directory: Optional[str] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    exit_code: Optional[int] = None
    output_masked: bool = False
    status: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    timeout_seconds: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None
    
    model_config = ConfigDict(from_attributes=True)


class ToolCallResponse(BaseModel):
    """Tool call response."""
    
    id: str
    run_id: str
    tool_name: str
    tool_category: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    outcome: str
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    retries: int = 0
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    idempotency_key: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    
    model_config = ConfigDict(from_attributes=True)


class StreamEvent(BaseModel):
    """SSE stream event."""
    
    event: str = Field(..., description="Event type")
    data: Dict[str, Any] = Field(..., description="Event data")
    run_id: str = Field(..., description="Run ID")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Event timestamp")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "event": "token",
            "data": {"content": "Creating VM..."},
            "run_id": "run_123",
            "timestamp": "2024-01-01T00:00:00Z"
        }
    })


class HealthResponse(BaseModel):
    """Health check response."""
    
    status: str = Field(..., description="Service status")
    version: str = Field(..., description="Service version")
    environment: str = Field(..., description="Environment")
    components: Dict[str, bool] = Field(..., description="Component health status")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Check timestamp")


class StatsResponse(BaseModel):
    """Statistics response."""
    
    total_runs: int
    active_runs: int
    completed_runs: int
    failed_runs: int
    pending_approvals: int
    active_vm_executions: int
    avg_run_duration_seconds: Optional[float] = None
    avg_approval_wait_time_seconds: Optional[float] = None
    tool_call_success_rate: Optional[float] = None
