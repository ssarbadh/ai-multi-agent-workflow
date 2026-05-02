"""
ServiceNow Pydantic Schemas.

Industry-grade schema definitions for ServiceNow entities following
the HLD requirements for SR/CR/Incident management.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, ConfigDict


# =============================================================================
# ENUMS - State and Type Definitions
# =============================================================================

class IncidentState(str, Enum):
    """Incident lifecycle states."""
    NEW = "1"
    IN_PROGRESS = "2"
    ON_HOLD = "3"
    RESOLVED = "6"
    CLOSED = "7"
    CANCELLED = "8"


class ChangeState(str, Enum):
    """Change Request lifecycle states."""
    NEW = "1"
    ASSESS = "2"
    AUTHORIZE = "3"
    SCHEDULED = "4"
    IMPLEMENT = "5"
    REVIEW = "6"
    CLOSED = "7"
    CANCELLED = "8"


class ChangeType(str, Enum):
    """Change Request types."""
    NORMAL = "normal"
    STANDARD = "standard"
    EMERGENCY = "emergency"


class RequestState(str, Enum):
    """Service Request states."""
    PENDING_APPROVAL = "1"
    APPROVED = "2"
    REJECTED = "3"
    CLOSED_COMPLETE = "4"
    CLOSED_INCOMPLETE = "5"
    CLOSED_CANCELLED = "6"


class RequestItemState(str, Enum):
    """Requested Item (RITM) states."""
    OPEN = "1"
    WORK_IN_PROGRESS = "2"
    CLOSED_COMPLETE = "3"
    CLOSED_INCOMPLETE = "4"
    CLOSED_CANCELLED = "7"


class TaskState(str, Enum):
    """Task states."""
    OPEN = "1"
    WORK_IN_PROGRESS = "2"
    CLOSED_COMPLETE = "3"
    CLOSED_INCOMPLETE = "4"
    CLOSED_SKIPPED = "7"


class ApprovalState(str, Enum):
    """Approval states."""
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class Priority(str, Enum):
    """Priority levels."""
    CRITICAL = "1"
    HIGH = "2"
    MEDIUM = "3"
    LOW = "4"
    PLANNING = "5"


class Impact(str, Enum):
    """Impact levels."""
    HIGH = "1"
    MEDIUM = "2"
    LOW = "3"


class Urgency(str, Enum):
    """Urgency levels."""
    HIGH = "1"
    MEDIUM = "2"
    LOW = "3"


# =============================================================================
# BASE MODELS
# =============================================================================

class SNOWBaseModel(BaseModel):
    """Base model for all ServiceNow entities."""
    model_config = ConfigDict(
        populate_by_name=True,
        use_enum_values=True,
        extra="allow"
    )


class SNOWRecord(SNOWBaseModel):
    """Base record with common SNOW fields."""
    sys_id: Optional[str] = Field(None, description="ServiceNow system ID")
    number: Optional[str] = Field(None, description="Record number (e.g., INC0010001)")
    sys_created_on: Optional[str] = Field(None, description="Creation timestamp")
    sys_updated_on: Optional[str] = Field(None, description="Last update timestamp")
    sys_created_by: Optional[str] = Field(None, description="Created by user")
    sys_updated_by: Optional[str] = Field(None, description="Updated by user")


# =============================================================================
# INCIDENT MODELS
# =============================================================================

class IncidentCreate(SNOWBaseModel):
    """Schema for creating an incident."""
    short_description: str = Field(..., min_length=1, max_length=160)
    description: Optional[str] = Field(None, max_length=4000)
    urgency: Urgency = Field(default=Urgency.MEDIUM)
    impact: Impact = Field(default=Impact.MEDIUM)
    category: Optional[str] = None
    subcategory: Optional[str] = None
    assignment_group: Optional[str] = None
    assigned_to: Optional[str] = None
    caller_id: Optional[str] = None
    cmdb_ci: Optional[str] = Field(None, description="Configuration Item sys_id")
    business_service: Optional[str] = None
    work_notes: Optional[str] = None
    additional_comments: Optional[str] = None


class IncidentUpdate(SNOWBaseModel):
    """Schema for updating an incident."""
    short_description: Optional[str] = Field(None, max_length=160)
    description: Optional[str] = Field(None, max_length=4000)
    state: Optional[IncidentState] = None
    urgency: Optional[Urgency] = None
    impact: Optional[Impact] = None
    assignment_group: Optional[str] = None
    assigned_to: Optional[str] = None
    work_notes: Optional[str] = None
    additional_comments: Optional[str] = None
    close_code: Optional[str] = None
    close_notes: Optional[str] = None
    resolution_code: Optional[str] = None
    resolution_notes: Optional[str] = None


class Incident(SNOWRecord):
    """Full incident record."""
    short_description: Optional[str] = None
    description: Optional[str] = None
    state: Optional[str] = None
    urgency: Optional[str] = None
    impact: Optional[str] = None
    priority: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    assignment_group: Optional[str] = None
    assigned_to: Optional[str] = None
    caller_id: Optional[str] = None
    cmdb_ci: Optional[str] = None
    business_service: Optional[str] = None
    opened_at: Optional[str] = None
    resolved_at: Optional[str] = None
    closed_at: Optional[str] = None
    close_code: Optional[str] = None
    close_notes: Optional[str] = None


# =============================================================================
# CHANGE REQUEST MODELS
# =============================================================================

class ChangeRequestCreate(SNOWBaseModel):
    """Schema for creating a change request."""
    short_description: str = Field(..., min_length=1, max_length=160)
    description: Optional[str] = Field(None, max_length=4000)
    type: ChangeType = Field(default=ChangeType.NORMAL)
    risk: Optional[str] = Field(default="3", description="Risk level 1-5")
    impact: Impact = Field(default=Impact.MEDIUM)
    priority: Priority = Field(default=Priority.MEDIUM)
    category: Optional[str] = None
    assignment_group: Optional[str] = None
    assigned_to: Optional[str] = None
    cmdb_ci: Optional[str] = None
    start_date: Optional[str] = Field(None, description="Planned start (YYYY-MM-DD HH:MM:SS)")
    end_date: Optional[str] = Field(None, description="Planned end (YYYY-MM-DD HH:MM:SS)")
    justification: Optional[str] = None
    implementation_plan: Optional[str] = None
    backout_plan: Optional[str] = None
    test_plan: Optional[str] = None
    work_notes: Optional[str] = None


class ChangeRequestUpdate(SNOWBaseModel):
    """Schema for updating a change request."""
    short_description: Optional[str] = Field(None, max_length=160)
    description: Optional[str] = Field(None, max_length=4000)
    state: Optional[ChangeState] = None
    risk: Optional[str] = None
    impact: Optional[Impact] = None
    assignment_group: Optional[str] = None
    assigned_to: Optional[str] = None
    cmdb_ci: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    work_notes: Optional[str] = None
    close_code: Optional[str] = None
    close_notes: Optional[str] = None


class ChangeRequest(SNOWRecord):
    """Full change request record."""
    short_description: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    state: Optional[str] = None
    risk: Optional[str] = None
    impact: Optional[str] = None
    priority: Optional[str] = None
    category: Optional[str] = None
    assignment_group: Optional[str] = None
    assigned_to: Optional[str] = None
    cmdb_ci: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    opened_at: Optional[str] = None
    closed_at: Optional[str] = None


# =============================================================================
# SERVICE REQUEST MODELS
# =============================================================================

class ServiceRequestCreate(SNOWBaseModel):
    """Schema for creating a service request via catalog."""
    catalog_item_id: str = Field(..., description="Catalog item sys_id")
    quantity: int = Field(default=1, ge=1)
    variables: Dict[str, Any] = Field(default_factory=dict)
    requested_for: Optional[str] = Field(None, description="User sys_id")
    description: Optional[str] = None


class ServiceRequest(SNOWRecord):
    """Full service request record."""
    requested_for: Optional[str] = None
    request_state: Optional[str] = None
    stage: Optional[str] = None
    opened_at: Optional[str] = None
    closed_at: Optional[str] = None
    price: Optional[str] = None


class RequestedItem(SNOWRecord):
    """Requested Item (RITM) record."""
    request: Optional[str] = Field(None, description="Parent request sys_id")
    cat_item: Optional[str] = Field(None, description="Catalog item sys_id")
    short_description: Optional[str] = None
    state: Optional[str] = None
    stage: Optional[str] = None
    assigned_to: Optional[str] = None
    assignment_group: Optional[str] = None
    opened_at: Optional[str] = None
    closed_at: Optional[str] = None


class ServiceTask(SNOWRecord):
    """Service catalog task record."""
    request_item: Optional[str] = Field(None, description="Parent RITM sys_id")
    short_description: Optional[str] = None
    state: Optional[str] = None
    assigned_to: Optional[str] = None
    assignment_group: Optional[str] = None
    opened_at: Optional[str] = None
    closed_at: Optional[str] = None


# =============================================================================
# APPROVAL MODELS
# =============================================================================

class Approval(SNOWBaseModel):
    """Approval record from sysapproval_approver."""
    sys_id: Optional[str] = None
    sysapproval: Optional[str] = Field(None, description="Parent record sys_id")
    approver: Optional[str] = Field(None, description="Approver user sys_id")
    state: Optional[ApprovalState] = None
    comments: Optional[str] = None
    sys_created_on: Optional[str] = None
    sys_updated_on: Optional[str] = None


class ApprovalAction(SNOWBaseModel):
    """Schema for approval action."""
    state: ApprovalState
    comments: Optional[str] = None


# =============================================================================
# CMDB MODELS
# =============================================================================

class ConfigurationItem(SNOWRecord):
    """CMDB Configuration Item."""
    name: Optional[str] = None
    sys_class_name: Optional[str] = None
    operational_status: Optional[str] = None
    install_status: Optional[str] = None
    ip_address: Optional[str] = None
    dns_domain: Optional[str] = None
    os: Optional[str] = None
    os_version: Optional[str] = None
    environment: Optional[str] = None
    location: Optional[str] = None
    department: Optional[str] = None
    assigned_to: Optional[str] = None
    support_group: Optional[str] = None


# =============================================================================
# RESPONSE MODELS
# =============================================================================

class SNOWResponse(SNOWBaseModel):
    """Standard SNOW API response wrapper."""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    ticket_number: Optional[str] = None
    ticket_url: Optional[str] = None


class SNOWListResponse(SNOWBaseModel):
    """Paginated list response."""
    success: bool
    data: List[Dict[str, Any]] = Field(default_factory=list)
    total_count: int = 0
    offset: int = 0
    limit: int = 100
    error: Optional[str] = None


class TicketSummary(SNOWBaseModel):
    """Summary of a ticket for API responses."""
    sys_id: str
    number: str
    short_description: str
    state: str
    state_label: str
    priority: Optional[str] = None
    assigned_to: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    ticket_url: str


# =============================================================================
# WORKFLOW MODELS (for Agent Integration)
# =============================================================================

class WorkflowContext(SNOWBaseModel):
    """Context passed through agent workflow."""
    run_id: str
    session_id: str
    ticket_type: str
    ticket_sys_id: Optional[str] = None
    ticket_number: Optional[str] = None
    current_state: Optional[str] = None
    pending_approvals: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class StateTransition(SNOWBaseModel):
    """Record of a state transition."""
    from_state: str
    to_state: str
    timestamp: datetime
    actor: str
    reason: Optional[str] = None
