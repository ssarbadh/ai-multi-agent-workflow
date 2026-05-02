"""SQLAlchemy ORM models for Agent Orchestration."""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, String, Integer, Float, DateTime, Text, JSON, Boolean, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class RunStatus(str, enum.Enum):
    """Run status enumeration."""
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_PASSWORD = "waiting_password"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RequestType(str, enum.Enum):
    """Request type enumeration."""
    SERVICE_REQUEST = "SERVICE_REQUEST"
    CHANGE_REQUEST = "CHANGE_REQUEST"
    INCIDENT = "INCIDENT"
    PROBLEM = "PROBLEM"
    DEVOPS_AUTOMATION = "DEVOPS_AUTOMATION"
    CONVERSATIONAL = "CONVERSATIONAL"
    CLOUDOPS = "CLOUDOPS"
    SRE = "SRE"


class ApprovalStatus(str, enum.Enum):
    """Approval status enumeration."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"


class Run(Base):
    """Agent orchestration run."""
    
    __tablename__ = "runs"
    
    id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)
    request_type = Column(SQLEnum(RequestType), nullable=False, index=True)
    status = Column(SQLEnum(RunStatus), nullable=False, default=RunStatus.PENDING, index=True)
    
    # Request details
    title = Column(String, nullable=False)
    description = Column(Text)
    priority = Column(String, default="medium")
    
    # Routing
    routed_to = Column(String)  # SR/CR or Incident agent
    routing_confidence = Column(Float)
    
    # ServiceNow integration
    snow_ticket_id = Column(String, index=True)
    snow_ticket_number = Column(String)
    snow_ticket_url = Column(String)
    
    # Execution tracking
    current_node = Column(String)
    graph_state = Column(JSON)
    checkpoint_id = Column(String)
    
    # Metrics
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    duration_seconds = Column(Float)
    tokens_used = Column(Integer, default=0)
    
    # Confidentiality
    confidentiality_score = Column(Float)
    confidentiality_level = Column(String)  # low, medium, high
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    extra_data = Column(JSON)  # renamed from 'metadata' - reserved in SQLAlchemy
    
    # Relationships
    session = relationship("Session", back_populates="runs")
    approvals = relationship("Approval", back_populates="run", cascade="all, delete-orphan")
    vm_executions = relationship("VMExecution", back_populates="run", cascade="all, delete-orphan")
    tool_calls = relationship("ToolCall", back_populates="run", cascade="all, delete-orphan")


class Approval(Base):
    """Human approval/password prompt."""
    
    __tablename__ = "approvals"
    
    id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False, index=True)
    
    # Approval details
    approval_type = Column(String, nullable=False)  # approval, password, input
    prompt = Column(Text, nullable=False)
    context = Column(JSON)
    
    # Response
    status = Column(SQLEnum(ApprovalStatus), nullable=False, default=ApprovalStatus.PENDING)
    response = Column(Text)
    approved_by = Column(String)
    
    # Timing
    requested_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    responded_at = Column(DateTime)
    wait_time_seconds = Column(Float)
    timeout_seconds = Column(Integer)
    
    # Metadata
    extra_data = Column(JSON)  # renamed from 'metadata' - reserved in SQLAlchemy
    
    # Relationships
    run = relationship("Run", back_populates="approvals")


class VMExecution(Base):
    """VM/container command execution."""
    
    __tablename__ = "vm_executions"
    
    id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False, index=True)
    
    # Execution details
    command = Column(Text, nullable=False)
    command_hash = Column(String, index=True)
    working_directory = Column(String)
    environment = Column(JSON)
    
    # Output
    stdout = Column(Text)
    stderr = Column(Text)
    exit_code = Column(Integer)
    output_masked = Column(Boolean, default=False)
    
    # Timing
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime)
    duration_seconds = Column(Float)
    timeout_seconds = Column(Integer)
    
    # Status
    status = Column(String, nullable=False)  # running, completed, failed, timeout
    
    # Extra data
    extra_data = Column(JSON)  # renamed from 'metadata' - reserved in SQLAlchemy
    
    # Relationships
    run = relationship("Run", back_populates="vm_executions")


class ToolCall(Base):
    """Tool/MCP call tracking."""
    
    __tablename__ = "tool_calls"
    
    id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False, index=True)
    
    # Tool details
    tool_name = Column(String, nullable=False, index=True)
    tool_category = Column(String)  # vmware, aws, azure, gcp, k8s, snow, github
    parameters = Column(JSON)
    parameters_hash = Column(String)
    
    # Execution
    outcome = Column(String, nullable=False)  # success, error, timeout
    result = Column(JSON)
    error_message = Column(Text)
    retries = Column(Integer, default=0)
    
    # Timing
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime)
    duration_seconds = Column(Float)
    
    # Idempotency
    idempotency_key = Column(String, index=True)
    
    # Extra data
    extra_data = Column(JSON)  # renamed from 'metadata' - reserved in SQLAlchemy
    
    # Relationships
    run = relationship("Run", back_populates="tool_calls")


class Notification(Base):
    """Notification tracking."""
    
    __tablename__ = "notifications"
    
    id = Column(String, primary_key=True)
    run_id = Column(String, index=True)
    
    # Notification details
    notification_type = Column(String, nullable=False)  # email, chat
    recipient = Column(String, nullable=False)
    subject = Column(String)
    body = Column(Text, nullable=False)
    
    # Status
    status = Column(String, nullable=False)  # pending, sent, failed
    sent_at = Column(DateTime)
    error_message = Column(Text)
    
    # Extra data
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    extra_data = Column(JSON)  # renamed from 'metadata' - reserved in SQLAlchemy


class Session(Base):
    """Chat session."""
    
    __tablename__ = "sessions"
    
    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    status = Column(String, nullable=False, default="active", index=True)  # active, closed
    type = Column(String, nullable=False, index=True)  # service-request, change-request, incident, problem
    snow_ticket_id = Column(String, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    closed_at = Column(DateTime)
    
    # Relationships
    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan")
    runs = relationship("Run", back_populates="session", cascade="all, delete-orphan")


class Message(Base):
    """Chat message."""
    
    __tablename__ = "messages"
    
    id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id = Column(String, index=True)
    role = Column(String, nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    
    # Agent information
    agent_type = Column(String, index=True)  # conversational, devops, cloudops, sre
    
    # Message linkage (for threading user input -> agent response)
    parent_message_id = Column(String, ForeignKey("messages.id", ondelete="SET NULL"), index=True)
    
    # Security classification
    confidentiality_score = Column(Float)
    confidentiality_label = Column(String)  # low, medium, high
    
    # Additional metadata (model, tokens, timing, etc.)
    # Note: Using 'extra_metadata' instead of 'metadata' (reserved word in SQLAlchemy)
    extra_metadata = Column("metadata", JSON)  # Column name in DB is 'metadata', but attribute is 'extra_metadata'
    
    # RAG sources/references
    rag_sources = Column(JSON)  # List of sources used to generate this message
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Relationships
    session = relationship("Session", back_populates="messages")
    
    # Self-referential relationship for parent-child message linking
    parent_message = relationship("Message", remote_side=[id], backref="responses", foreign_keys=[parent_message_id])
