"""Prometheus metrics processor - fetches metrics and detects anomalies.

Supports real Prometheus API or simulated input for testing.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.core.logging import logger


class PrometheusProcessor:
    """Fetches Prometheus metrics and detects anomalies (latency/error rate spikes)."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: int = 30,
        bearer_token: Optional[str] = None,
    ) -> None:
        promo_url = base_url or getattr(settings, "GRAPH_ENRICHMENT_PROMETHEUS_URL", "") or getattr(settings, "PROMETHEUS_MCP_URL", "")
        self._base_url = (promo_url or "").rstrip("/")
        self._timeout = timeout
        self._token = bearer_token or getattr(settings, "PROMETHEUS_MCP_BEARER_TOKEN", "") or None
        self._client: Optional[httpx.Client] = None

    def _ensure_client(self) -> Optional[httpx.Client]:
        if self._client is None and self._base_url:
            headers = {}
            if self._token:
                headers["Authorization"] = f"Bearer {self._token}"
            self._client = httpx.Client(timeout=self._timeout, headers=headers)
        return self._client

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

    def fetch_metric_range(
        self,
        query: str,
        start: Optional[int] = None,
        end: Optional[int] = None,
        step: str = "60s",
    ) -> List[Dict[str, Any]]:
        """
        Execute Prometheus range query. Returns list of time series data points.
        """
        client = self._ensure_client()
        if not client:
            return []
        end = end or int(time.time())
        start = start or (end - 3600)
        try:
            resp = client.get(
                f"{self._base_url}/api/v1/query_range",
                params={"query": query, "start": start, "end": end, "step": step},
            )
            resp.raise_for_status()
            data = resp.json()
            result = data.get("data", {}).get("result", [])
            points: List[Dict[str, Any]] = []
            for r in result:
                metric = r.get("metric", {})
                values = r.get("values", [])
                for ts, val in values:
                    try:
                        v = float(val)
                    except (TypeError, ValueError):
                        v = 0.0
                    points.append({
                        "metric": metric,
                        "timestamp": ts,
                        "value": v,
                        "labels": dict(metric),
                    })
            return points
        except Exception as exc:
            logger.warning("Prometheus range query failed", query=query[:80], exc=str(exc))
            return []

    def detect_anomalies_from_points(
        self,
        points: List[Dict[str, Any]],
        anomaly_type: str = "latency_spike",
        threshold_multiplier: float = 2.0,
        baseline_percentile: float = 50.0,
    ) -> List[Dict[str, Any]]:
        """
        Detect anomalies from metric points (e.g. latency or error rate spike).
        Uses simple threshold: value > baseline * multiplier.
        """
        if not points:
            return []
        values = [p.get("value", 0) for p in points if isinstance(p.get("value"), (int, float))]
        if not values:
            return []
        sorted_vals = sorted(values)
        idx = int(len(sorted_vals) * baseline_percentile / 100) or 0
        baseline = sorted_vals[min(idx, len(sorted_vals) - 1)] or 0.001
        threshold = baseline * threshold_multiplier
        anomalies: List[Dict[str, Any]] = []
        for p in points:
            v = p.get("value", 0)
            if isinstance(v, (int, float)) and v > threshold:
                anomalies.append({
                    "type": anomaly_type,
                    "value": v,
                    "timestamp": p.get("timestamp"),
                    "baseline": baseline,
                    "labels": p.get("labels", {}),
                })
        return anomalies[:50]

    def get_service_metrics_simulated(self, service_name: str) -> List[Dict[str, Any]]:
        """Simulate metric data for a service (for testing when Prometheus unavailable)."""
        now = int(time.time())
        points = []
        for i in range(10):
            ts = now - (10 - i) * 60
            base = 100.0 + (i % 3) * 20
            spike = 350.0 if i == 7 else base
            points.append({
                "metric": {"service": service_name, "job": "simulated"},
                "timestamp": ts,
                "value": spike,
                "labels": {"service": service_name},
            })
        return points

    def get_database_metrics_simulated(
        self,
        database_name: str,
        database_type: str = "RDS",
    ) -> List[Dict[str, Any]]:
        """Simulate metric data for databases (RDS, Redis, Mongo) for testing."""
        now = int(time.time())
        points = []
        # Simulate CPU/connection spikes for databases
        for i in range(10):
            ts = now - (10 - i) * 60
            base = 20.0 + (i % 4) * 5
            spike = 85.0 if i == 6 else base
            points.append({
                "metric": {"database": database_name, "type": database_type},
                "timestamp": ts,
                "value": spike,
                "labels": {"database": database_name, "type": database_type},
            })
        return points

    def process_database(
        self,
        database_name: str,
        database_type: str = "RDS",
        use_simulated: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Process metrics for a database (RDS, Redis, Mongo), detect anomalies.
        Returns list of anomaly dicts.
        """
        if use_simulated or not self._base_url:
            points = self.get_database_metrics_simulated(database_name, database_type)
            return self.detect_anomalies_from_points(
                points, anomaly_type="database_cpu_spike", threshold_multiplier=2.0
            )
        # Real Prometheus - use typical DB metrics
        queries = {
            "RDS": f"aws_rds_cpu_total{{dbinstance_identifier=~'.*{database_name}.*'}}",
            "Redis": f"redis_memory_used_bytes{{instance=~'.*{database_name}.*'}}",
            "Mongo": f"mongodb_connections{{state=~'.*{database_name}.*'}}",
        }
        q = queries.get(database_type, queries["RDS"])
        points = self.fetch_metric_range(q)
        return self.detect_anomalies_from_points(
            points, anomaly_type="database_metric_spike", threshold_multiplier=2.0
        )

    def process_service(
        self,
        service_name: str,
        latency_query: Optional[str] = None,
        error_rate_query: Optional[str] = None,
        use_simulated: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Process metrics for a service, detect anomalies.
        Returns list of anomaly dicts.
        """
        anomalies: List[Dict[str, Any]] = []
        if use_simulated or not self._base_url:
            points = self.get_service_metrics_simulated(service_name)
            anomalies = self.detect_anomalies_from_points(
                points, anomaly_type="latency_spike", threshold_multiplier=2.0
            )
            return anomalies

        # Real Prometheus
        if latency_query:
            points = self.fetch_metric_range(latency_query)
            anomalies.extend(
                self.detect_anomalies_from_points(
                    points, anomaly_type="latency_spike", threshold_multiplier=2.0
                )
            )
        if error_rate_query:
            points = self.fetch_metric_range(error_rate_query)
            anomalies.extend(
                self.detect_anomalies_from_points(
                    points, anomaly_type="error_rate_spike", threshold_multiplier=2.0
                )
            )
        if not latency_query and not error_rate_query:
            # Default: try common patterns
            q = f'histogram_quantile(0.99, rate(http_request_duration_seconds_bucket{{job=~".*{service_name}.*"}}[5m]))'
            points = self.fetch_metric_range(q)
            if not points:
                q2 = f"rate(http_requests_total{{job=~'.*{service_name}.*'}}[5m])"
                points = self.fetch_metric_range(q2)
            anomalies = self.detect_anomalies_from_points(
                points, anomaly_type="latency_spike", threshold_multiplier=2.0
            )
        return anomalies
