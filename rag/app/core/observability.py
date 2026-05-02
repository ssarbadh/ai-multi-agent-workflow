"""OpenTelemetry observability configuration."""
import logging
from typing import Optional

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import start_http_server, Counter, Histogram, Gauge, Info, REGISTRY
import platform

logger = logging.getLogger(__name__)


class RAGMetrics:
    """Custom Prometheus metrics for RAG system."""
    
    _instance = None
    _initialized = False
    
    def __new__(cls, service_name: str = "rag-service"):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, service_name: str = "rag-service"):
        """Initialize all custom metrics."""
        if self._initialized:
            return
        
        # System info
        self.service_info = Info("rag_service", "RAG service information")
        self.service_info.info({
            "name": service_name,
            "version": "0.1.0",
            "environment": "production"
        })
        
        # Request metrics
        self.http_requests_total = Counter(
            "http_requests_total",
            "Total HTTP requests",
            ["method", "endpoint", "status"]
        )
        
        self.http_request_duration = Histogram(
            "http_request_duration_seconds",
            "HTTP request duration in seconds",
            ["method", "endpoint"],
            buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0]
        )
        
        # RAG pipeline metrics
        self.rag_queries_total = Counter(
            "rag_queries_total",
            "Total RAG queries processed",
            ["status"]
        )
        
        self.rag_query_duration = Histogram(
            "rag_query_duration_seconds",
            "RAG query duration in seconds",
            ["stage"],
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0]
        )
        
        self.rag_documents_retrieved = Histogram(
            "rag_documents_retrieved",
            "Number of documents retrieved per query",
            buckets=[0, 1, 5, 10, 20, 50, 100]
        )
        
        # Embedding metrics
        self.embeddings_generated_total = Counter(
            "embeddings_generated_total",
            "Total embeddings generated"
        )
        
        self.embedding_duration = Histogram(
            "embedding_duration_seconds",
            "Embedding generation duration",
            buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0]
        )
        
        # Vector search metrics
        self.vector_search_total = Counter(
            "vector_search_total",
            "Total vector searches",
            ["index_type"]
        )
        
        self.vector_search_duration = Histogram(
            "vector_search_duration_seconds",
            "Vector search duration",
            ["index_type"],
            buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0]
        )
        
        # LLM metrics
        self.llm_requests_total = Counter(
            "llm_requests_total",
            "Total LLM requests",
            ["model", "status"]
        )
        
        self.llm_request_duration = Histogram(
            "llm_request_duration_seconds",
            "LLM request duration",
            ["model"],
            buckets=[1.0, 5.0, 10.0, 20.0, 30.0, 60.0]
        )
        
        self.llm_tokens_used_total = Counter(
            "llm_tokens_used_total",
            "Total tokens used",
            ["model", "type"]  # type: prompt or completion
        )
        
        # Advanced RAG Evaluation Metrics
        self.rag_evaluation_score = Gauge(
            "rag_evaluation_score",
            "Current RAG evaluation score",
            ["metric_type"]  # recall, precision, faithfulness, etc.
        )
        
        self.rag_query_satisfaction = Histogram(
            "rag_query_satisfaction",
            "User satisfaction scores for RAG queries",
            ["query_type"],
            buckets=[1.0, 2.0, 3.0, 4.0, 5.0]
        )
        
        self.rag_cost_per_query = Histogram(
            "rag_cost_per_query_usd",
            "Cost per RAG query in USD",
            ["model"],
            buckets=[0.001, 0.01, 0.1, 1.0, 10.0]
        )
        
        self.rag_context_relevance = Histogram(
            "rag_context_relevance_score",
            "Relevance score of retrieved context",
            buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        )
        
        self.rag_answer_completeness = Histogram(
            "rag_answer_completeness_score", 
            "Completeness score of generated answers",
            buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        )
        
        # Real-time Performance Metrics
        self.rag_pipeline_bottleneck = Gauge(
            "rag_pipeline_bottleneck_seconds",
            "Time spent in slowest pipeline stage",
            ["stage"]  # embedding, retrieval, reranking, generation
        )
        
        self.rag_concurrent_queries = Gauge(
            "rag_concurrent_queries",
            "Number of concurrent RAG queries being processed"
        )
        
        # A/B Testing Metrics
        self.rag_ab_test_results = Counter(
            "rag_ab_test_results_total",
            "A/B test results for different configurations",
            ["variant", "metric", "outcome"]
        )
        
        # User Behavior Metrics
        self.rag_query_patterns = Counter(
            "rag_query_patterns_total",
            "Common query patterns and categories",
            ["category", "complexity"]
        )
        
        self.rag_followup_queries = Counter(
            "rag_followup_queries_total",
            "Follow-up queries after initial response",
            ["initial_category"]
        )
        
        # Cache metrics
        self.cache_hits_total = Counter(
            "cache_hits_total",
            "Total cache hits",
            ["cache_type"]
        )
        
        self.cache_misses_total = Counter(
            "cache_misses_total",
            "Total cache misses",
            ["cache_type"]
        )
        
        # Document processing metrics
        self.documents_indexed_total = Counter(
            "documents_indexed_total",
            "Total documents indexed",
            ["source"]
        )
        
        self.document_processing_duration = Histogram(
            "document_processing_duration_seconds",
            "Document processing duration",
            ["stage"],
            buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0]
        )
        
        self.chunks_created_total = Counter(
            "chunks_created_total",
            "Total chunks created from documents"
        )
        
        # Database metrics
        self.db_queries_total = Counter(
            "db_queries_total",
            "Total database queries",
            ["operation"]
        )
        
        self.db_query_duration = Histogram(
            "db_query_duration_seconds",
            "Database query duration",
            ["operation"],
            buckets=[0.001, 0.01, 0.05, 0.1, 0.5, 1.0, 2.0]
        )
        
        self.db_connections_active = Gauge(
            "db_connections_active",
            "Active database connections"
        )
        
        # Celery worker metrics
        self.celery_tasks_total = Counter(
            "celery_tasks_total",
            "Total Celery tasks",
            ["task", "status"]
        )
        
        self.celery_task_duration = Histogram(
            "celery_task_duration_seconds",
            "Celery task duration",
            ["task"],
            buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 600.0]
        )
        
        # System health metrics
        self.system_health_status = Gauge(
            "system_health_status",
            "System health status (1=healthy, 0=unhealthy)",
            ["component"]
        )
        
        # Error metrics
        self.errors_total = Counter(
            "errors_total",
            "Total errors",
            ["component", "error_type"]
        )
        
        self._initialized = True
        logger.info("RAG metrics initialized")


class ObservabilityManager:
    """Manages OpenTelemetry tracing and metrics."""
    
    def __init__(
        self,
        service_name: str = "rag-service",
        service_version: str = "0.1.0",
        environment: str = "production",
        enable_prometheus: bool = True,
        prometheus_port: int = 8001,
        enable_otlp: bool = False,
        otlp_endpoint: Optional[str] = None,
    ):
        """Initialize observability stack."""
        self.service_name = service_name
        self.service_version = service_version
        self.environment = environment
        self.enable_prometheus = enable_prometheus
        self.prometheus_port = prometheus_port
        self.enable_otlp = enable_otlp
        self.otlp_endpoint = otlp_endpoint
        
        # Initialize custom metrics
        self.metrics = RAGMetrics(service_name)
        
        # Setup OpenTelemetry
        self._setup_telemetry()
        
        logger.info(
            f"Observability initialized for {service_name} v{service_version} "
            f"(env={environment}, prometheus={enable_prometheus}, otlp={enable_otlp})"
        )
    
    def _setup_telemetry(self):
        """Setup OpenTelemetry tracing and metrics."""
        # Create resource
        resource = Resource.create({
            SERVICE_NAME: self.service_name,
            SERVICE_VERSION: self.service_version,
            "environment": self.environment,
        })
        
        # Setup tracing
        self._setup_tracing(resource)
        
        # Setup metrics
        self._setup_metrics(resource)
    
    def _setup_tracing(self, resource: Resource):
        """Setup distributed tracing."""
        tracer_provider = TracerProvider(resource=resource)
        
        # Add OTLP exporter if enabled
        if self.enable_otlp and self.otlp_endpoint:
            otlp_exporter = OTLPSpanExporter(endpoint=self.otlp_endpoint)
            tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
            logger.info(f"OTLP trace exporter configured: {self.otlp_endpoint}")
        
        trace.set_tracer_provider(tracer_provider)
        
        # Get tracer
        self.tracer = trace.get_tracer(__name__)
        
        logger.info("Distributed tracing configured")
    
    def _setup_metrics(self, resource: Resource):
        """Setup metrics collection."""
        readers = []
        
        # Add Prometheus exporter if enabled
        if self.enable_prometheus:
            prometheus_reader = PrometheusMetricReader()
            readers.append(prometheus_reader)
            
            # Start Prometheus HTTP server
            # Note: prometheus_client automatically includes process collectors on supported platforms
            try:
                start_http_server(port=self.prometheus_port, addr="0.0.0.0")
                logger.info(f"Prometheus metrics server started on port {self.prometheus_port}")
                logger.info(f"Process metrics enabled (Platform: {platform.system()})")
            except OSError as e:
                logger.warning(f"Could not start Prometheus server: {e}")
        
        # Add OTLP exporter if enabled
        if self.enable_otlp and self.otlp_endpoint:
            otlp_exporter = OTLPMetricExporter(endpoint=self.otlp_endpoint)
            otlp_reader = PeriodicExportingMetricReader(otlp_exporter, export_interval_millis=60000)
            readers.append(otlp_reader)
            logger.info(f"OTLP metric exporter configured: {self.otlp_endpoint}")
        
        # Setup meter provider
        if readers:
            meter_provider = MeterProvider(resource=resource, metric_readers=readers)
            metrics.set_meter_provider(meter_provider)
            self.meter = metrics.get_meter(__name__)
            logger.info("Metrics collection configured")
    
    def instrument_app(self, app):
        """Instrument FastAPI application."""
        FastAPIInstrumentor.instrument_app(app)
        logger.info("FastAPI instrumented")
    
    def instrument_sqlalchemy(self, engine):
        """Instrument SQLAlchemy engine."""
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
        logger.info("SQLAlchemy instrumented")
    
    def instrument_redis(self):
        """Instrument Redis client."""
        RedisInstrumentor().instrument()
        logger.info("Redis instrumented")
    
    def instrument_httpx(self):
        """Instrument HTTPX client."""
        HTTPXClientInstrumentor().instrument()
        logger.info("HTTPX instrumented")
    
    def get_tracer(self):
        """Get OpenTelemetry tracer."""
        return self.tracer
    
    def get_meter(self):
        """Get OpenTelemetry meter."""
        return self.meter
    
    def get_metrics(self) -> RAGMetrics:
        """Get custom Prometheus metrics."""
        return self.metrics


# Global observability manager instance
_observability_manager: Optional[ObservabilityManager] = None


def init_observability(
    service_name: str = "rag-service",
    service_version: str = "0.1.0",
    environment: str = "production",
    enable_prometheus: bool = True,
    prometheus_port: int = 8011,
    enable_otlp: bool = False,
    otlp_endpoint: Optional[str] = None,
) -> ObservabilityManager:
    """Initialize observability stack."""
    global _observability_manager
    
    if _observability_manager is None:
        _observability_manager = ObservabilityManager(
            service_name=service_name,
            service_version=service_version,
            environment=environment,
            enable_prometheus=enable_prometheus,
            prometheus_port=prometheus_port,
            enable_otlp=enable_otlp,
            otlp_endpoint=otlp_endpoint,
        )
    
    return _observability_manager


def get_observability() -> ObservabilityManager:
    """Get observability manager instance."""
    if _observability_manager is None:
        raise RuntimeError("Observability not initialized. Call init_observability() first.")
    return _observability_manager


def get_tracer():
    """Get OpenTelemetry tracer."""
    return get_observability().get_tracer()


def get_meter():
    """Get OpenTelemetry meter."""
    return get_observability().get_meter()


def get_metrics() -> RAGMetrics:
    """Get custom Prometheus metrics."""
    return get_observability().get_metrics()
