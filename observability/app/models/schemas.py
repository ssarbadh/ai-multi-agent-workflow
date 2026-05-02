"""Pydantic schemas for observability metrics and events."""

from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum
from pydantic import BaseModel, Field


# ============== Enums ==============

class MetricCategory(str, Enum):
    AGENT = "agent"
    RAG = "rag"
    TOOL = "tool"
    API = "api"
    SYSTEM = "system"


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertStatus(str, Enum):
    FIRING = "firing"
    RESOLVED = "resolved"
    SILENCED = "silenced"


# ============== Agent Evaluation Metrics (HLD) ==============

class TaskOutcomeMetrics(BaseModel):
    """Task/Outcome metrics per HLD."""
    resolution_rate: float = Field(..., description="% runs resolved")
    time_to_resolution_p50: float = Field(..., description="P50 minutes")
    time_to_resolution_p95: float = Field(..., description="P95 minutes")
    first_action_success_rate: float = Field(..., description="No human correction rate")
    rollback_rate: float = Field(..., description="Remediation reverted rate")
    escalation_rate: float = Field(..., description="Escalation to human rate")
    approval_compliance: float = Field(..., description="Actions with proper approval")


class InteractionSafetyMetrics(BaseModel):
    """Interaction & Safety metrics per HLD."""
    user_satisfaction_avg: float = Field(..., description="Avg thumbs up/down score")
    csat_score: Optional[float] = Field(None, description="CSAT survey 1-5")
    feedback_utilization: float = Field(..., description="% sessions with preference changes")
    confidentiality_accuracy: float = Field(..., description="Label agreement rate")
    safety_incidents: int = Field(..., description="Policy violations prevented")


class EfficiencyMetrics(BaseModel):
    """Efficiency metrics per HLD."""
    steps_per_resolution_mean: float
    steps_per_resolution_median: float
    tool_success_rate: float = Field(..., description="Non-5xx and valid results")
    reattempts_per_tool_call: float
    human_wait_time_p50: float = Field(..., description="Approval wait seconds P50")
    human_wait_time_p95: float = Field(..., description="Approval wait seconds P95")


class AgentEvaluationMetrics(BaseModel):
    """Combined agent evaluation metrics."""
    timestamp: datetime
    period_hours: int = 24
    task_outcome: TaskOutcomeMetrics
    interaction_safety: InteractionSafetyMetrics
    efficiency: EfficiencyMetrics


# ============== RAG Evaluation Metrics (HLD) ==============

class RetrievalQualityMetrics(BaseModel):
    """Retrieval quality metrics per HLD."""
    recall_at_k: Dict[int, float] = Field(..., description="Recall@k for k=5,10,20")
    precision_at_k: Dict[int, float] = Field(..., description="Precision@k")
    mrr: float = Field(..., description="Mean Reciprocal Rank")
    ndcg_at_k: Dict[int, float] = Field(..., description="nDCG@k")
    context_precision: float = Field(..., description="Relevant facts included")
    context_recall: float = Field(..., description="Relevant facts not missed")
    coverage_diversity: float = Field(..., description="Distinct sources in top-k")


class GenerationQualityMetrics(BaseModel):
    """Generation quality metrics per HLD."""
    faithfulness: float = Field(..., description="Groundedness score")
    hallucination_rate: float = Field(..., description="Unsupported claims rate")
    answer_relevance: float = Field(..., description="Relevance to query")
    citation_correctness: float = Field(..., description="Citations support claims")
    conciseness_score: float = Field(..., description="Readability score")


class RAGPerformanceMetrics(BaseModel):
    """RAG performance metrics per HLD."""
    retrieval_latency_bm25_ms: float
    retrieval_latency_vector_ms: float
    retrieval_latency_hybrid_ms: float
    retrieval_latency_rerank_ms: float
    end_to_end_latency_ms: float
    index_freshness_minutes: float = Field(..., description="Time from modification to searchable")


class RAGEvaluationMetrics(BaseModel):
    """Combined RAG evaluation metrics."""
    timestamp: datetime
    period_hours: int = 24
    retrieval_quality: RetrievalQualityMetrics
    generation_quality: GenerationQualityMetrics
    performance: RAGPerformanceMetrics


# ============== Alerts (HLD SLO Hints) ==============

class AlertRule(BaseModel):
    """Alert rule definition per HLD."""
    id: str
    name: str
    description: str
    severity: AlertSeverity
    condition: str
    threshold: float
    duration_minutes: int = 5
    labels: Dict[str, str] = {}
    annotations: Dict[str, str] = {}


class Alert(BaseModel):
    """Active alert instance."""
    id: str
    rule_id: str
    name: str
    severity: AlertSeverity
    status: AlertStatus
    message: str
    value: float
    threshold: float
    started_at: datetime
    resolved_at: Optional[datetime] = None
    labels: Dict[str, str] = {}
    annotations: Dict[str, str] = {}


# ============== Dashboard Data ==============

class TimeSeriesPoint(BaseModel):
    """Single time series data point."""
    timestamp: datetime
    value: float
    labels: Dict[str, str] = {}


class TimeSeries(BaseModel):
    """Time series data."""
    metric_name: str
    points: List[TimeSeriesPoint]
    labels: Dict[str, str] = {}


class DashboardPanel(BaseModel):
    """Dashboard panel data."""
    id: str
    title: str
    type: str  # gauge, graph, table, stat
    data: Any


class Dashboard(BaseModel):
    """Dashboard definition per HLD."""
    id: str
    name: str
    description: str
    panels: List[DashboardPanel]
    refresh_interval_seconds: int = 30


# ============== Service Health ==============

class ServiceHealth(BaseModel):
    """Service health status."""
    service: str
    status: str  # healthy, degraded, unhealthy
    latency_ms: Optional[float] = None
    last_check: datetime
    details: Dict[str, Any] = {}


class SystemHealth(BaseModel):
    """Overall system health."""
    status: str
    services: List[ServiceHealth]
    timestamp: datetime


# ============== Log Ingestion ==============

class LogEntry(BaseModel):
    """Structured log entry per HLD envelope."""
    ts: datetime
    level: str
    service: str
    env: str
    message: str
    request_id: Optional[str] = None
    session_id: Optional[str] = None
    run_id: Optional[str] = None
    user_id: Optional[str] = None
    role: Optional[str] = None
    ip_hash: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class MetricEvent(BaseModel):
    """Metric event for ingestion."""
    name: str
    value: float
    timestamp: datetime
    labels: Dict[str, str] = {}
    category: MetricCategory = MetricCategory.SYSTEM


# ============== Trace Data ==============

class SpanContext(BaseModel):
    """OpenTelemetry span context."""
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None


class Span(BaseModel):
    """Trace span per HLD taxonomy."""
    context: SpanContext
    name: str
    service: str
    start_time: datetime
    end_time: datetime
    duration_ms: float
    status: str
    attributes: Dict[str, Any] = {}
    events: List[Dict[str, Any]] = []


class Trace(BaseModel):
    """Complete trace."""
    trace_id: str
    root_span: Span
    spans: List[Span]
    duration_ms: float
