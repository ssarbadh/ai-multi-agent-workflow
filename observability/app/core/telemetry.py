"""
OpenTelemetry instrumentation for AegisOps Observability service.

Provides distributed tracing, metrics, and logging via OTEL.
"""

import logging
from typing import Optional

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.b3 import B3MultiFormat

from app.core.config import settings

logger = logging.getLogger(__name__)

# Global tracer and meter
_tracer: Optional[trace.Tracer] = None
_meter: Optional[metrics.Meter] = None


def get_resource() -> Resource:
    """Create OTEL resource with service information."""
    return Resource.create({
        SERVICE_NAME: settings.SERVICE_NAME,
        SERVICE_VERSION: settings.VERSION,
        "deployment.environment": settings.ENVIRONMENT,
        "service.namespace": "aegisops",
    })


def setup_tracing() -> None:
    """Initialize OpenTelemetry tracing."""
    global _tracer
    
    if not settings.OTEL_ENABLED:
        logger.info("OpenTelemetry tracing disabled")
        return
    
    try:
        resource = get_resource()
        
        # Create tracer provider
        provider = TracerProvider(resource=resource)
        
        # Configure OTLP exporter
        otlp_exporter = OTLPSpanExporter(
            endpoint=settings.OTEL_COLLECTOR_ENDPOINT,
            insecure=True
        )
        
        # Add batch processor for efficient export
        provider.add_span_processor(
            BatchSpanProcessor(otlp_exporter)
        )
        
        # Set global tracer provider
        trace.set_tracer_provider(provider)
        
        # Set B3 propagator for cross-service tracing
        set_global_textmap(B3MultiFormat())
        
        # Get tracer instance
        _tracer = trace.get_tracer(
            settings.SERVICE_NAME,
            settings.VERSION
        )
        
        logger.info(
            f"OpenTelemetry tracing initialized, "
            f"exporting to {settings.OTEL_COLLECTOR_ENDPOINT}"
        )
        
    except Exception as e:
        logger.warning(f"Failed to initialize OTEL tracing: {e}")


def setup_metrics() -> None:
    """Initialize OpenTelemetry metrics."""
    global _meter
    
    if not settings.OTEL_ENABLED:
        logger.info("OpenTelemetry metrics disabled")
        return
    
    try:
        resource = get_resource()
        
        # Configure OTLP metric exporter
        otlp_exporter = OTLPMetricExporter(
            endpoint=settings.OTEL_COLLECTOR_ENDPOINT,
            insecure=True
        )
        
        # Create metric reader with periodic export
        reader = PeriodicExportingMetricReader(
            otlp_exporter,
            export_interval_millis=60000  # Export every 60 seconds
        )
        
        # Create meter provider
        provider = MeterProvider(
            resource=resource,
            metric_readers=[reader]
        )
        
        # Set global meter provider
        metrics.set_meter_provider(provider)
        
        # Get meter instance
        _meter = metrics.get_meter(
            settings.SERVICE_NAME,
            settings.VERSION
        )
        
        logger.info("OpenTelemetry metrics initialized")
        
    except Exception as e:
        logger.warning(f"Failed to initialize OTEL metrics: {e}")


def instrument_fastapi(app) -> None:
    """Instrument FastAPI application with OTEL."""
    if not settings.OTEL_ENABLED:
        return
    
    try:
        FastAPIInstrumentor.instrument_app(
            app,
            excluded_urls="health,ready,live,metrics"
        )
        logger.info("FastAPI instrumented with OpenTelemetry")
    except Exception as e:
        logger.warning(f"Failed to instrument FastAPI: {e}")


def instrument_httpx() -> None:
    """Instrument HTTPX client for outgoing requests."""
    if not settings.OTEL_ENABLED:
        return
    
    try:
        HTTPXClientInstrumentor().instrument()
        logger.info("HTTPX instrumented with OpenTelemetry")
    except Exception as e:
        logger.warning(f"Failed to instrument HTTPX: {e}")


def setup_telemetry(app=None) -> None:
    """Initialize all OpenTelemetry components."""
    setup_tracing()
    setup_metrics()
    instrument_httpx()
    
    if app:
        instrument_fastapi(app)


def get_tracer() -> Optional[trace.Tracer]:
    """Get the global tracer instance."""
    global _tracer
    if _tracer is None and settings.OTEL_ENABLED:
        _tracer = trace.get_tracer(
            settings.SERVICE_NAME,
            settings.VERSION
        )
    return _tracer


def get_meter() -> Optional[metrics.Meter]:
    """Get the global meter instance."""
    global _meter
    if _meter is None and settings.OTEL_ENABLED:
        _meter = metrics.get_meter(
            settings.SERVICE_NAME,
            settings.VERSION
        )
    return _meter


# Custom span decorators for common operations
def trace_operation(name: str, attributes: dict = None):
    """Decorator to trace a function as a span."""
    def decorator(func):
        async def async_wrapper(*args, **kwargs):
            tracer = get_tracer()
            if tracer:
                with tracer.start_as_current_span(name, attributes=attributes or {}):
                    return await func(*args, **kwargs)
            return await func(*args, **kwargs)
        
        def sync_wrapper(*args, **kwargs):
            tracer = get_tracer()
            if tracer:
                with tracer.start_as_current_span(name, attributes=attributes or {}):
                    return func(*args, **kwargs)
            return func(*args, **kwargs)
        
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    return decorator


# OTEL metric helpers
class OTELMetrics:
    """Helper class for creating OTEL metrics."""
    
    _counters = {}
    _histograms = {}
    _gauges = {}
    
    @classmethod
    def counter(cls, name: str, description: str = "", unit: str = "1"):
        """Get or create a counter metric."""
        if name not in cls._counters:
            meter = get_meter()
            if meter:
                cls._counters[name] = meter.create_counter(
                    name, description=description, unit=unit
                )
        return cls._counters.get(name)
    
    @classmethod
    def histogram(cls, name: str, description: str = "", unit: str = "ms"):
        """Get or create a histogram metric."""
        if name not in cls._histograms:
            meter = get_meter()
            if meter:
                cls._histograms[name] = meter.create_histogram(
                    name, description=description, unit=unit
                )
        return cls._histograms.get(name)
    
    @classmethod
    def gauge(cls, name: str, description: str = "", unit: str = "1"):
        """Get or create an observable gauge metric."""
        # Note: Observable gauges require callbacks, simplified here
        if name not in cls._gauges:
            meter = get_meter()
            if meter:
                cls._gauges[name] = meter.create_up_down_counter(
                    name, description=description, unit=unit
                )
        return cls._gauges.get(name)
