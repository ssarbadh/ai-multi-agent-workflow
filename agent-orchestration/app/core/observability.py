"""Observability setup with OpenTelemetry, Prometheus, and Sentry."""

import logging
from typing import Optional
from prometheus_client import Counter, Histogram, Gauge, start_http_server
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from app.core.config import settings
from app.core.langsmith_setup import configure_langsmith_from_settings

logger = logging.getLogger(__name__)


class PrometheusMetrics:
    """Prometheus metrics for agent orchestration."""
    
    def __init__(self):
        # HTTP metrics
        self.http_requests_total = Counter(
            "http_requests_total",
            "Total HTTP requests",
            ["method", "endpoint", "status"]
        )
        self.http_request_duration = Histogram(
            "http_request_duration_seconds",
            "HTTP request duration",
            ["method", "endpoint"]
        )
        
        # Agent metrics
        self.agent_runs_total = Counter(
            "agent_runs_total",
            "Total agent runs",
            ["agent_type", "status"]
        )
        self.agent_run_duration = Histogram(
            "agent_run_duration_seconds",
            "Agent run duration",
            ["agent_type"]
        )
        self.agent_node_duration = Histogram(
            "agent_node_duration_seconds",
            "Agent node execution duration",
            ["node_name"]
        )
        
        # Tool metrics
        self.tool_calls_total = Counter(
            "tool_calls_total",
            "Total tool calls",
            ["tool_name", "outcome"]
        )
        self.tool_call_duration = Histogram(
            "tool_call_duration_seconds",
            "Tool call duration",
            ["tool_name"]
        )
        self.tool_error_rate = Gauge(
            "tool_error_rate",
            "Tool error rate",
            ["tool_name"]
        )
        
        # Approval & Gates
        self.approval_wait_time = Histogram(
            "approval_wait_time_seconds",
            "Time waiting for approvals",
            ["approval_type"]
        )
        self.approvals_total = Counter(
            "approvals_total",
            "Total approvals",
            ["approval_type", "outcome"]
        )
        
        # VM Execution
        self.vm_exec_total = Counter(
            "vm_exec_total",
            "Total VM executions",
            ["outcome"]
        )
        self.vm_exec_duration = Histogram(
            "vm_exec_duration_seconds",
            "VM execution duration"
        )
        
        # ServiceNow
        self.snow_operations_total = Counter(
            "snow_operations_total",
            "Total ServiceNow operations",
            ["operation", "status"]
        )
        self.snow_operation_duration = Histogram(
            "snow_operation_duration_seconds",
            "ServiceNow operation duration",
            ["operation"]
        )
        
        # Streaming
        self.sse_connections_active = Gauge(
            "sse_connections_active",
            "Active SSE connections"
        )
        self.sse_events_sent = Counter(
            "sse_events_sent_total",
            "Total SSE events sent",
            ["event_type"]
        )
        self.tokens_streamed = Counter(
            "tokens_streamed_total",
            "Total tokens streamed"
        )
        
        # System health
        self.system_health_status = Gauge(
            "system_health_status",
            "System component health (1=healthy, 0=unhealthy)",
            ["component"]
        )
        
        # Remediation
        self.remediation_success_rate = Gauge(
            "remediation_success_rate",
            "Remediation success rate"
        )
        self.remediation_rollback_rate = Gauge(
            "remediation_rollback_rate",
            "Remediation rollback rate"
        )


# Global metrics instance
_metrics: Optional[PrometheusMetrics] = None


def get_metrics() -> PrometheusMetrics:
    """Get global Prometheus metrics instance."""
    global _metrics
    if _metrics is None:
        _metrics = PrometheusMetrics()
    return _metrics


def setup_observability() -> None:
    """Setup OpenTelemetry, Prometheus, Sentry, and LangSmith env for LangGraph."""
    configure_langsmith_from_settings()

    # Setup Prometheus
    if settings.PROMETHEUS_PORT:
        try:
            start_http_server(settings.PROMETHEUS_PORT)
            logger.info(f"Prometheus metrics server started on port {settings.PROMETHEUS_PORT}")
        except Exception as e:
            logger.warning(f"Failed to start Prometheus server: {e}")
    
    # Setup OpenTelemetry
    if settings.OTEL_ENABLED:
        try:
            # Tracer provider
            tracer_provider = TracerProvider()
            if settings.OTEL_EXPORTER_OTLP_ENDPOINT:
                span_exporter = OTLPSpanExporter(
                    endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
                    insecure=True
                )
                tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
            trace.set_tracer_provider(tracer_provider)
            
            # Meter provider
            if settings.OTEL_EXPORTER_OTLP_ENDPOINT:
                metric_exporter = OTLPMetricExporter(
                    endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
                    insecure=True
                )
                metric_reader = PeriodicExportingMetricReader(metric_exporter)
                meter_provider = MeterProvider(metric_readers=[metric_reader])
                metrics.set_meter_provider(meter_provider)
            
            logger.info("OpenTelemetry initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize OpenTelemetry: {e}")
    
    # Setup Sentry
    if settings.SENTRY_DSN:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.fastapi import FastApiIntegration
            from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
            
            sentry_sdk.init(
                dsn=settings.SENTRY_DSN,
                environment=settings.ENVIRONMENT,
                traces_sample_rate=0.1 if settings.ENVIRONMENT == "production" else 1.0,
                integrations=[
                    FastApiIntegration(),
                    SqlalchemyIntegration(),
                ],
            )
            logger.info("Sentry initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize Sentry: {e}")
    
    # Initialize metrics
    get_metrics()


def shutdown_observability() -> None:
    """Shutdown observability components."""
    logger.info("Shutting down observability")


def instrument_app(app):
    """Instrument FastAPI app with OpenTelemetry."""
    if settings.OTEL_ENABLED:
        FastAPIInstrumentor.instrument_app(app)


def instrument_sqlalchemy(engine):
    """Instrument SQLAlchemy with OpenTelemetry."""
    if settings.OTEL_ENABLED:
        # For async engines, instrument the sync_engine instead
        if hasattr(engine, 'sync_engine'):
            SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
        else:
            SQLAlchemyInstrumentor().instrument(engine=engine)


def instrument_redis():
    """Instrument Redis with OpenTelemetry."""
    if settings.OTEL_ENABLED:
        RedisInstrumentor().instrument()


def instrument_httpx():
    """Instrument HTTPX with OpenTelemetry."""
    if settings.OTEL_ENABLED:
        HTTPXClientInstrumentor().instrument()
