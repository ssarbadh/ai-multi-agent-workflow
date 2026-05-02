"""SQLAlchemy models for metrics persistence."""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, JSON, Text, Index, Enum as SQLEnum
from sqlalchemy.ext.declarative import declarative_base
import enum

Base = declarative_base()


class MetricCategory(enum.Enum):
    AGENT = "agent"
    RAG = "rag"
    TOOL = "tool"
    API = "api"
    SYSTEM = "system"


class AlertSeverity(enum.Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertStatus(enum.Enum):
    FIRING = "firing"
    RESOLVED = "resolved"
    SILENCED = "silenced"


class MetricRecord(Base):
    """Persisted metric record."""
    __tablename__ = "metrics"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, index=True)
    value = Column(Float, nullable=False)
    timestamp = Column(DateTime, nullable=False, index=True)
    category = Column(SQLEnum(MetricCategory), nullable=False, index=True)
    labels = Column(JSON, default={})
    service = Column(String(100), index=True)
    
    __table_args__ = (
        Index("ix_metrics_name_timestamp", "name", "timestamp"),
        Index("ix_metrics_category_timestamp", "category", "timestamp"),
    )


class AgentRunMetric(Base):
    """Agent run metrics for evaluation."""
    __tablename__ = "agent_run_metrics"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(100), nullable=False, unique=True, index=True)
    session_id = Column(String(100), index=True)
    agent_type = Column(String(50), index=True)
    status = Column(String(20), index=True)  # completed, failed, escalated
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime)
    duration_seconds = Column(Float)
    steps_count = Column(Integer, default=0)
    tool_calls_count = Column(Integer, default=0)
    tool_errors_count = Column(Integer, default=0)
    approvals_count = Column(Integer, default=0)
    approval_wait_seconds = Column(Float, default=0)
    was_escalated = Column(Integer, default=0)
    was_rolled_back = Column(Integer, default=0)
    first_action_success = Column(Integer, default=1)
    user_feedback = Column(String(10))  # up, down, null
    snow_ticket_id = Column(String(50))
    metadata = Column(JSON, default={})


class RAGQueryMetric(Base):
    """RAG query metrics for evaluation."""
    __tablename__ = "rag_query_metrics"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    query_id = Column(String(100), nullable=False, unique=True, index=True)
    session_id = Column(String(100), index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    retriever_type = Column(String(20))  # vector, bm25, hybrid
    topk = Column(Integer)
    reranker_used = Column(Integer, default=0)
    retrieval_latency_ms = Column(Float)
    rerank_latency_ms = Column(Float)
    generation_latency_ms = Column(Float)
    total_latency_ms = Column(Float)
    chunks_retrieved = Column(Integer)
    chunks_used = Column(Integer)
    sources_count = Column(Integer)
    faithfulness_score = Column(Float)
    relevance_score = Column(Float)
    metadata = Column(JSON, default={})


class AlertRecord(Base):
    """Alert history."""
    __tablename__ = "alerts"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_id = Column(String(100), nullable=False, index=True)
    rule_id = Column(String(100), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    severity = Column(SQLEnum(AlertSeverity), nullable=False, index=True)
    status = Column(SQLEnum(AlertStatus), nullable=False, index=True)
    message = Column(Text)
    value = Column(Float)
    threshold = Column(Float)
    started_at = Column(DateTime, nullable=False, index=True)
    resolved_at = Column(DateTime)
    acknowledged_at = Column(DateTime)
    acknowledged_by = Column(String(100))
    labels = Column(JSON, default={})
    annotations = Column(JSON, default={})


class LogRecord(Base):
    """Persisted log records for analysis."""
    __tablename__ = "logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    level = Column(String(20), nullable=False, index=True)
    service = Column(String(100), nullable=False, index=True)
    message = Column(Text)
    request_id = Column(String(100), index=True)
    session_id = Column(String(100), index=True)
    run_id = Column(String(100), index=True)
    user_id = Column(String(100), index=True)
    data = Column(JSON, default={})
    
    __table_args__ = (
        Index("ix_logs_service_timestamp", "service", "timestamp"),
        Index("ix_logs_run_id_timestamp", "run_id", "timestamp"),
    )


class EvaluationSnapshot(Base):
    """Periodic evaluation metric snapshots."""
    __tablename__ = "evaluation_snapshots"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_type = Column(String(20), nullable=False, index=True)  # agent, rag
    timestamp = Column(DateTime, nullable=False, index=True)
    period_hours = Column(Integer, default=24)
    metrics = Column(JSON, nullable=False)
    
    __table_args__ = (
        Index("ix_eval_type_timestamp", "snapshot_type", "timestamp"),
    )
