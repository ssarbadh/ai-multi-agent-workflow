"""Dashboard service per HLD dashboard requirements."""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

from app.models.schemas import Dashboard, DashboardPanel, TimeSeries, TimeSeriesPoint

logger = logging.getLogger(__name__)


class DashboardService:
    """
    Dashboard data service per HLD requirements.
    
    Dashboards to visualize:
    - Executive: resolution rate, time-to-resolution, escalations, CSAT, safety incidents
    - RAG: Recall@k, faithfulness, latency, freshness by corpus, index size growth
    - Serving: LLM tokens/s, p95, GPU VRAM/util, batch size, cache hit
    - Graph: runs by status, node latency heatmap, interrupts & wait times
    - Pipelines: ingest backlog, embedding throughput, failures
    - Infra: API p95, DB p95, Redis hit/evictions, error budgets
    """
    
    def __init__(self):
        self.dashboards = self._create_default_dashboards()
    
    def _create_default_dashboards(self) -> Dict[str, Dashboard]:
        """Create default dashboard definitions per HLD."""
        return {
            "executive": Dashboard(
                id="executive",
                name="Executive Dashboard",
                description="High-level metrics for leadership",
                panels=[
                    DashboardPanel(id="resolution_rate", title="Resolution Rate", type="gauge", data={}),
                    DashboardPanel(id="time_to_resolution", title="Time to Resolution (P50/P95)", type="stat", data={}),
                    DashboardPanel(id="escalations", title="Escalation Rate", type="graph", data={}),
                    DashboardPanel(id="csat", title="User Satisfaction", type="gauge", data={}),
                    DashboardPanel(id="safety_incidents", title="Safety Incidents", type="stat", data={}),
                ],
                refresh_interval_seconds=60
            ),
            "rag": Dashboard(
                id="rag",
                name="RAG Dashboard",
                description="RAG system performance and quality",
                panels=[
                    DashboardPanel(id="recall_at_k", title="Recall@k", type="graph", data={}),
                    DashboardPanel(id="faithfulness", title="Faithfulness Score", type="gauge", data={}),
                    DashboardPanel(id="retrieval_latency", title="Retrieval Latency", type="graph", data={}),
                    DashboardPanel(id="index_freshness", title="Index Freshness", type="stat", data={}),
                    DashboardPanel(id="index_size", title="Index Size Growth", type="graph", data={}),
                ],
                refresh_interval_seconds=30
            ),
            "serving": Dashboard(
                id="serving",
                name="LLM Serving Dashboard",
                description="LLM inference performance",
                panels=[
                    DashboardPanel(id="tokens_per_second", title="Tokens/Second", type="graph", data={}),
                    DashboardPanel(id="latency_p95", title="Latency P95", type="graph", data={}),
                    DashboardPanel(id="gpu_utilization", title="GPU Utilization", type="gauge", data={}),
                    DashboardPanel(id="batch_size", title="Batch Size", type="stat", data={}),
                    DashboardPanel(id="cache_hit_rate", title="Cache Hit Rate", type="gauge", data={}),
                ],
                refresh_interval_seconds=15
            ),
            "graph": Dashboard(
                id="graph",
                name="Agent Graph Dashboard",
                description="LangGraph agent execution metrics",
                panels=[
                    DashboardPanel(id="runs_by_status", title="Runs by Status", type="graph", data={}),
                    DashboardPanel(id="node_latency_heatmap", title="Node Latency Heatmap", type="heatmap", data={}),
                    DashboardPanel(id="interrupts", title="Interrupts & Wait Times", type="graph", data={}),
                    DashboardPanel(id="active_runs", title="Active Runs", type="stat", data={}),
                ],
                refresh_interval_seconds=15
            ),
            "pipelines": Dashboard(
                id="pipelines",
                name="Pipeline Dashboard",
                description="Data pipeline metrics",
                panels=[
                    DashboardPanel(id="ingest_backlog", title="Ingest Backlog", type="graph", data={}),
                    DashboardPanel(id="embedding_throughput", title="Embedding Throughput", type="graph", data={}),
                    DashboardPanel(id="pipeline_failures", title="Pipeline Failures", type="graph", data={}),
                    DashboardPanel(id="documents_processed", title="Documents Processed", type="stat", data={}),
                ],
                refresh_interval_seconds=30
            ),
            "infra": Dashboard(
                id="infra",
                name="Infrastructure Dashboard",
                description="System infrastructure metrics",
                panels=[
                    DashboardPanel(id="api_latency_p95", title="API Latency P95", type="graph", data={}),
                    DashboardPanel(id="db_latency_p95", title="Database Latency P95", type="graph", data={}),
                    DashboardPanel(id="redis_hit_rate", title="Redis Hit Rate", type="gauge", data={}),
                    DashboardPanel(id="redis_evictions", title="Redis Evictions", type="graph", data={}),
                    DashboardPanel(id="error_budget", title="Error Budget Remaining", type="gauge", data={}),
                ],
                refresh_interval_seconds=15
            ),
        }
    
    def get_dashboard(self, dashboard_id: str) -> Optional[Dashboard]:
        """Get dashboard definition by ID."""
        return self.dashboards.get(dashboard_id)
    
    def list_dashboards(self) -> List[Dashboard]:
        """List all available dashboards."""
        return list(self.dashboards.values())
    
    async def get_dashboard_data(
        self,
        dashboard_id: str,
        time_range_hours: int = 24
    ) -> Optional[Dashboard]:
        """Get dashboard with populated panel data."""
        dashboard = self.get_dashboard(dashboard_id)
        if not dashboard:
            return None
        
        # Populate panel data based on dashboard type
        if dashboard_id == "executive":
            return await self._populate_executive_dashboard(dashboard, time_range_hours)
        elif dashboard_id == "rag":
            return await self._populate_rag_dashboard(dashboard, time_range_hours)
        elif dashboard_id == "serving":
            return await self._populate_serving_dashboard(dashboard, time_range_hours)
        elif dashboard_id == "graph":
            return await self._populate_graph_dashboard(dashboard, time_range_hours)
        elif dashboard_id == "pipelines":
            return await self._populate_pipelines_dashboard(dashboard, time_range_hours)
        elif dashboard_id == "infra":
            return await self._populate_infra_dashboard(dashboard, time_range_hours)
        
        return dashboard
    
    async def _populate_executive_dashboard(
        self,
        dashboard: Dashboard,
        time_range_hours: int
    ) -> Dashboard:
        """Populate executive dashboard with data."""
        # In production, query actual metrics
        for panel in dashboard.panels:
            if panel.id == "resolution_rate":
                panel.data = {"value": 0.85, "target": 0.90}
            elif panel.id == "time_to_resolution":
                panel.data = {"p50": 12.5, "p95": 45.2, "unit": "minutes"}
            elif panel.id == "escalations":
                panel.data = await self._get_time_series("escalation_rate", time_range_hours)
            elif panel.id == "csat":
                panel.data = {"value": 4.2, "max": 5.0}
            elif panel.id == "safety_incidents":
                panel.data = {"value": 0, "period": f"{time_range_hours}h"}
        return dashboard
    
    async def _populate_rag_dashboard(
        self,
        dashboard: Dashboard,
        time_range_hours: int
    ) -> Dashboard:
        """Populate RAG dashboard with data."""
        for panel in dashboard.panels:
            if panel.id == "recall_at_k":
                panel.data = {"k5": 0.75, "k10": 0.85, "k20": 0.92}
            elif panel.id == "faithfulness":
                panel.data = {"value": 0.91, "target": 0.90}
            elif panel.id == "retrieval_latency":
                panel.data = await self._get_time_series("rag_retrieval_latency_ms", time_range_hours)
            elif panel.id == "index_freshness":
                panel.data = {"value": 15, "unit": "minutes", "threshold": 30}
            elif panel.id == "index_size":
                panel.data = await self._get_time_series("rag_index_size_docs", time_range_hours)
        return dashboard
    
    async def _populate_serving_dashboard(
        self,
        dashboard: Dashboard,
        time_range_hours: int
    ) -> Dashboard:
        """Populate LLM serving dashboard with data."""
        for panel in dashboard.panels:
            if panel.id == "tokens_per_second":
                panel.data = await self._get_time_series("llm_tokens_per_second", time_range_hours)
            elif panel.id == "latency_p95":
                panel.data = await self._get_time_series("llm_latency_p95_ms", time_range_hours)
            elif panel.id == "gpu_utilization":
                panel.data = {"value": 0.0, "available": False}  # No GPU in dev
            elif panel.id == "batch_size":
                panel.data = {"value": 1, "max": 8}
            elif panel.id == "cache_hit_rate":
                panel.data = {"value": 0.65, "target": 0.60}
        return dashboard
    
    async def _populate_graph_dashboard(
        self,
        dashboard: Dashboard,
        time_range_hours: int
    ) -> Dashboard:
        """Populate agent graph dashboard with data."""
        for panel in dashboard.panels:
            if panel.id == "runs_by_status":
                panel.data = {
                    "completed": 45,
                    "failed": 3,
                    "in_progress": 2,
                    "escalated": 5
                }
            elif panel.id == "node_latency_heatmap":
                panel.data = {
                    "nodes": ["router", "sr_cr", "provisioner", "snow", "notification"],
                    "latencies": [[100, 250, 500, 150, 80]]
                }
            elif panel.id == "interrupts":
                panel.data = await self._get_time_series("agent_interrupt_count", time_range_hours)
            elif panel.id == "active_runs":
                panel.data = {"value": 2}
        return dashboard
    
    async def _populate_pipelines_dashboard(
        self,
        dashboard: Dashboard,
        time_range_hours: int
    ) -> Dashboard:
        """Populate pipelines dashboard with data."""
        for panel in dashboard.panels:
            if panel.id == "ingest_backlog":
                panel.data = await self._get_time_series("pipeline_ingest_backlog", time_range_hours)
            elif panel.id == "embedding_throughput":
                panel.data = await self._get_time_series("pipeline_embedding_throughput", time_range_hours)
            elif panel.id == "pipeline_failures":
                panel.data = await self._get_time_series("pipeline_failures", time_range_hours)
            elif panel.id == "documents_processed":
                panel.data = {"value": 1250, "period": f"{time_range_hours}h"}
        return dashboard
    
    async def _populate_infra_dashboard(
        self,
        dashboard: Dashboard,
        time_range_hours: int
    ) -> Dashboard:
        """Populate infrastructure dashboard with data."""
        for panel in dashboard.panels:
            if panel.id == "api_latency_p95":
                panel.data = await self._get_time_series("http_request_duration_p95_ms", time_range_hours)
            elif panel.id == "db_latency_p95":
                panel.data = await self._get_time_series("db_query_duration_p95_ms", time_range_hours)
            elif panel.id == "redis_hit_rate":
                panel.data = {"value": 0.82, "target": 0.80}
            elif panel.id == "redis_evictions":
                panel.data = await self._get_time_series("redis_evictions", time_range_hours)
            elif panel.id == "error_budget":
                panel.data = {"value": 0.95, "consumed": 0.05, "period": "month"}
        return dashboard
    
    async def _get_time_series(
        self,
        metric_name: str,
        time_range_hours: int
    ) -> Dict[str, Any]:
        """Get time series data for a metric."""
        # In production, query Prometheus or database
        # Return placeholder structure
        now = datetime.now(timezone.utc)
        points = []
        for i in range(time_range_hours):
            points.append({
                "timestamp": (now - timedelta(hours=time_range_hours - i)).isoformat(),
                "value": 0.0
            })
        return {
            "metric": metric_name,
            "points": points
        }


# Global instance
dashboard_service = DashboardService()
