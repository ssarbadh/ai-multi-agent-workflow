"""Metrics collector service - collects metrics from all AegisOps services."""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import httpx
from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, push_to_gateway

from app.core.config import settings
from app.models.schemas import (
    MetricEvent, MetricCategory, ServiceHealth, SystemHealth,
    TimeSeries, TimeSeriesPoint
)

logger = logging.getLogger(__name__)


class MetricsCollector:
    """
    Collects metrics from all AegisOps services.
    
    Responsibilities:
    - Poll service health endpoints
    - Collect Prometheus metrics
    - Aggregate and store metrics
    - Push to Prometheus Pushgateway if configured
    """
    
    def __init__(self):
        self.registry = CollectorRegistry()
        self._setup_metrics()
        self._http_client: Optional[httpx.AsyncClient] = None
    
    def _setup_metrics(self):
        """Setup Prometheus metrics for this service."""
        # Service health
        self.service_health_gauge = Gauge(
            "aegisops_service_health",
            "Service health status (1=healthy, 0=unhealthy)",
            ["service"],
            registry=self.registry
        )
        
        # Collection metrics
        self.collection_duration = Histogram(
            "aegisops_metrics_collection_duration_seconds",
            "Time to collect metrics from services",
            ["service"],
            registry=self.registry
        )
        
        self.collection_errors = Counter(
            "aegisops_metrics_collection_errors_total",
            "Metric collection errors",
            ["service", "error_type"],
            registry=self.registry
        )
    
    async def get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=10.0)
        return self._http_client
    
    async def close(self):
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
    
    async def check_service_health(self, service_name: str, url: str) -> ServiceHealth:
        """Check health of a single service."""
        try:
            client = await self.get_http_client()
            start = datetime.utcnow()
            response = await client.get(f"{url}/health")
            latency = (datetime.utcnow() - start).total_seconds() * 1000
            
            if response.status_code == 200:
                data = response.json()
                status = data.get("status", "healthy")
                self.service_health_gauge.labels(service=service_name).set(1 if status == "healthy" else 0)
                return ServiceHealth(
                    service=service_name,
                    status=status,
                    latency_ms=latency,
                    last_check=datetime.utcnow(),
                    details=data
                )
            else:
                self.service_health_gauge.labels(service=service_name).set(0)
                return ServiceHealth(
                    service=service_name,
                    status="unhealthy",
                    latency_ms=latency,
                    last_check=datetime.utcnow(),
                    details={"error": f"HTTP {response.status_code}"}
                )
        except Exception as e:
            logger.error(f"Health check failed for {service_name}: {e}")
            self.collection_errors.labels(service=service_name, error_type="health_check").inc()
            self.service_health_gauge.labels(service=service_name).set(0)
            return ServiceHealth(
                service=service_name,
                status="unhealthy",
                last_check=datetime.utcnow(),
                details={"error": str(e)}
            )
    
    async def check_all_services(self) -> SystemHealth:
        """Check health of all AegisOps services."""
        services = [
            ("agent-orchestration", settings.AGENT_ORCHESTRATION_URL),
            ("context-management", settings.CONTEXT_MANAGEMENT_URL),
            ("rag", settings.RAG_URL),
        ]
        
        health_results = []
        for name, url in services:
            health = await self.check_service_health(name, url)
            health_results.append(health)
        
        # Determine overall status
        unhealthy_count = sum(1 for h in health_results if h.status == "unhealthy")
        if unhealthy_count == 0:
            overall_status = "healthy"
        elif unhealthy_count < len(health_results):
            overall_status = "degraded"
        else:
            overall_status = "unhealthy"
        
        return SystemHealth(
            status=overall_status,
            services=health_results,
            timestamp=datetime.utcnow()
        )
    
    async def collect_prometheus_metrics(self, service_name: str, url: str) -> List[MetricEvent]:
        """Collect Prometheus metrics from a service."""
        metrics = []
        try:
            client = await self.get_http_client()
            with self.collection_duration.labels(service=service_name).time():
                response = await client.get(f"{url}/metrics")
                
                if response.status_code == 200:
                    # Parse Prometheus text format
                    metrics = self._parse_prometheus_metrics(response.text, service_name)
        except Exception as e:
            logger.error(f"Failed to collect metrics from {service_name}: {e}")
            self.collection_errors.labels(service=service_name, error_type="metrics_collection").inc()
        
        return metrics
    
    def _parse_prometheus_metrics(self, text: str, service: str) -> List[MetricEvent]:
        """Parse Prometheus text format into MetricEvents."""
        metrics = []
        timestamp = datetime.utcnow()
        
        for line in text.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            
            try:
                # Simple parsing - metric_name{labels} value
                if "{" in line:
                    name_part, rest = line.split("{", 1)
                    labels_part, value_part = rest.rsplit("}", 1)
                    name = name_part.strip()
                    value = float(value_part.strip())
                    labels = self._parse_labels(labels_part)
                else:
                    parts = line.split()
                    if len(parts) >= 2:
                        name = parts[0]
                        value = float(parts[1])
                        labels = {}
                    else:
                        continue
                
                labels["source_service"] = service
                category = self._categorize_metric(name)
                
                metrics.append(MetricEvent(
                    name=name,
                    value=value,
                    timestamp=timestamp,
                    labels=labels,
                    category=category
                ))
            except Exception:
                continue
        
        return metrics
    
    def _parse_labels(self, labels_str: str) -> Dict[str, str]:
        """Parse Prometheus label string."""
        labels = {}
        for part in labels_str.split(","):
            if "=" in part:
                key, value = part.split("=", 1)
                labels[key.strip()] = value.strip().strip('"')
        return labels
    
    def _categorize_metric(self, name: str) -> MetricCategory:
        """Categorize metric by name."""
        if any(x in name for x in ["agent", "run", "node", "approval"]):
            return MetricCategory.AGENT
        elif any(x in name for x in ["rag", "retrieval", "embedding", "chunk"]):
            return MetricCategory.RAG
        elif any(x in name for x in ["tool", "mcp", "vm"]):
            return MetricCategory.TOOL
        elif any(x in name for x in ["http", "request", "response", "sse"]):
            return MetricCategory.API
        else:
            return MetricCategory.SYSTEM
    
    async def push_to_gateway(self):
        """Push metrics to Prometheus Pushgateway."""
        if settings.PROMETHEUS_PUSHGATEWAY_URL:
            try:
                push_to_gateway(
                    settings.PROMETHEUS_PUSHGATEWAY_URL,
                    job=settings.SERVICE_NAME,
                    registry=self.registry
                )
                logger.debug("Pushed metrics to Pushgateway")
            except Exception as e:
                logger.error(f"Failed to push to Pushgateway: {e}")


# Global instance
metrics_collector = MetricsCollector()
