"""
Master test file for Observability service.

Tests all components:
- API endpoints (health, metrics, alerts, dashboards, logs, traces)
- Services (metrics collector, agent evaluator, RAG evaluator, alerting, dashboards)
- Models and schemas
- Logging
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.core.logging import (
    ObservabilityLogger, hash_params, hash_ip, setup_logging
)
from app.models.schemas import (
    AgentEvaluationMetrics, RAGEvaluationMetrics,
    Alert, AlertRule, AlertSeverity, AlertStatus,
    Dashboard, MetricEvent, MetricCategory, LogEntry
)
from app.services.metrics_collector import MetricsCollector
from app.services.agent_evaluator import AgentEvaluator
from app.services.rag_evaluator import RAGEvaluator
from app.services.alerting import AlertingService, DEFAULT_ALERT_RULES
from app.services.dashboards import DashboardService


# ============== Fixtures ==============

@pytest.fixture
def client():
    """Test client for FastAPI app."""
    return TestClient(app)


@pytest.fixture
def metrics_collector():
    """Metrics collector instance."""
    return MetricsCollector()


@pytest.fixture
def agent_evaluator():
    """Agent evaluator instance."""
    return AgentEvaluator()


@pytest.fixture
def rag_evaluator():
    """RAG evaluator instance."""
    return RAGEvaluator()


@pytest.fixture
def alerting_service():
    """Alerting service instance."""
    return AlertingService()


@pytest.fixture
def dashboard_service():
    """Dashboard service instance."""
    return DashboardService()


# ============== API Tests ==============

class TestHealthAPI:
    """Tests for health endpoints."""
    
    def test_health_check(self, client):
        """Test basic health check."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "observability"
    
    def test_readiness_check(self, client):
        """Test readiness endpoint."""
        response = client.get("/ready")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"
    
    def test_liveness_check(self, client):
        """Test liveness endpoint."""
        response = client.get("/live")
        assert response.status_code == 200
        assert response.json()["status"] == "live"
    
    def test_root_endpoint(self, client):
        """Test root endpoint."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "service" in data
        assert "version" in data


class TestMetricsAPI:
    """Tests for metrics endpoints."""
    
    def test_get_agent_evaluation_metrics(self, client):
        """Test agent evaluation metrics endpoint."""
        response = client.get("/metrics/agent/evaluation")
        assert response.status_code == 200
        data = response.json()
        assert "task_outcome" in data
        assert "interaction_safety" in data
        assert "efficiency" in data
    
    def test_get_agent_evaluation_with_period(self, client):
        """Test agent evaluation with custom period."""
        response = client.get("/metrics/agent/evaluation?period_hours=48")
        assert response.status_code == 200
        data = response.json()
        assert data["period_hours"] == 48
    
    def test_get_rag_evaluation_metrics(self, client):
        """Test RAG evaluation metrics endpoint."""
        response = client.get("/metrics/rag/evaluation")
        assert response.status_code == 200
        data = response.json()
        assert "retrieval_quality" in data
        assert "generation_quality" in data
        assert "performance" in data
    
    def test_ingest_metrics(self, client):
        """Test metrics ingestion endpoint."""
        metrics = [
            {
                "name": "test_metric",
                "value": 42.0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "labels": {"env": "test"},
                "category": "system"
            }
        ]
        response = client.post("/metrics/ingest", json=metrics)
        assert response.status_code == 200
        assert response.json()["status"] == "accepted"


class TestAlertsAPI:
    """Tests for alerts endpoints."""
    
    def test_get_active_alerts(self, client):
        """Test get active alerts."""
        response = client.get("/alerts/")
        assert response.status_code == 200
        assert isinstance(response.json(), list)
    
    def test_get_alert_rules(self, client):
        """Test get alert rules."""
        response = client.get("/alerts/rules")
        assert response.status_code == 200
        rules = response.json()
        assert isinstance(rules, list)
        assert len(rules) > 0  # Default rules exist
    
    def test_create_alert_rule(self, client):
        """Test create alert rule."""
        rule = {
            "id": "test_rule",
            "name": "Test Rule",
            "description": "Test alert rule",
            "severity": "warning",
            "condition": "test_metric > threshold",
            "threshold": 100.0,
            "duration_minutes": 5,
            "labels": {},
            "annotations": {}
        }
        response = client.post("/alerts/rules", json=rule)
        assert response.status_code == 200
        assert response.json()["id"] == "test_rule"
    
    def test_silence_alert_rule(self, client):
        """Test silence alert rule."""
        # Use existing rule
        response = client.post("/alerts/rules/llm_latency_high/silence?duration_minutes=30")
        assert response.status_code == 200
        assert response.json()["status"] == "silenced"


class TestDashboardsAPI:
    """Tests for dashboards endpoints."""
    
    def test_list_dashboards(self, client):
        """Test list dashboards."""
        response = client.get("/dashboards/")
        assert response.status_code == 200
        dashboards = response.json()
        assert isinstance(dashboards, list)
        # Check HLD-required dashboards exist
        dashboard_ids = [d["id"] for d in dashboards]
        assert "executive" in dashboard_ids
        assert "rag" in dashboard_ids
        assert "serving" in dashboard_ids
        assert "graph" in dashboard_ids
        assert "pipelines" in dashboard_ids
        assert "infra" in dashboard_ids
    
    def test_get_executive_dashboard(self, client):
        """Test get executive dashboard."""
        response = client.get("/dashboards/executive")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "executive"
        assert len(data["panels"]) > 0
    
    def test_get_rag_dashboard(self, client):
        """Test get RAG dashboard."""
        response = client.get("/dashboards/rag")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "rag"
    
    def test_get_nonexistent_dashboard(self, client):
        """Test get nonexistent dashboard."""
        response = client.get("/dashboards/nonexistent")
        assert response.status_code == 404


class TestLogsAPI:
    """Tests for logs endpoints."""
    
    def test_ingest_logs(self, client):
        """Test log ingestion."""
        logs = [
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "level": "INFO",
                "service": "test",
                "env": "test",
                "message": "Test log message"
            }
        ]
        response = client.post("/logs/ingest", json=logs)
        assert response.status_code == 200
        assert response.json()["status"] == "accepted"
    
    def test_search_logs(self, client):
        """Test log search."""
        response = client.get("/logs/search?service=test&level=INFO")
        assert response.status_code == 200
        data = response.json()
        assert "logs" in data
        assert "filters" in data
    
    def test_get_run_logs(self, client):
        """Test get logs by run ID."""
        response = client.get("/logs/run/test-run-123")
        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == "test-run-123"


class TestTracesAPI:
    """Tests for traces endpoints."""
    
    def test_list_traces(self, client):
        """Test list traces."""
        response = client.get("/traces/")
        assert response.status_code == 200
        data = response.json()
        assert "traces" in data
    
    def test_get_traces_by_run(self, client):
        """Test get traces by run ID."""
        response = client.get("/traces/run/test-run-123")
        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == "test-run-123"


# ============== Service Tests ==============

class TestAgentEvaluator:
    """Tests for agent evaluator service."""
    
    @pytest.mark.asyncio
    async def test_calculate_metrics(self, agent_evaluator):
        """Test metrics calculation."""
        metrics = await agent_evaluator.calculate_metrics(period_hours=24)
        
        assert metrics.period_hours == 24
        assert metrics.task_outcome is not None
        assert metrics.interaction_safety is not None
        assert metrics.efficiency is not None
    
    @pytest.mark.asyncio
    async def test_task_outcome_metrics_structure(self, agent_evaluator):
        """Test task outcome metrics structure."""
        metrics = await agent_evaluator.calculate_metrics(period_hours=24)
        
        task = metrics.task_outcome
        assert hasattr(task, "resolution_rate")
        assert hasattr(task, "time_to_resolution_p50")
        assert hasattr(task, "time_to_resolution_p95")
        assert hasattr(task, "first_action_success_rate")
        assert hasattr(task, "rollback_rate")
        assert hasattr(task, "escalation_rate")
        assert hasattr(task, "approval_compliance")
    
    @pytest.mark.asyncio
    async def test_efficiency_metrics_structure(self, agent_evaluator):
        """Test efficiency metrics structure."""
        metrics = await agent_evaluator.calculate_metrics(period_hours=24)
        
        eff = metrics.efficiency
        assert hasattr(eff, "steps_per_resolution_mean")
        assert hasattr(eff, "tool_success_rate")
        assert hasattr(eff, "human_wait_time_p50")
        assert hasattr(eff, "human_wait_time_p95")


class TestRAGEvaluator:
    """Tests for RAG evaluator service."""
    
    @pytest.mark.asyncio
    async def test_calculate_metrics(self, rag_evaluator):
        """Test RAG metrics calculation."""
        metrics = await rag_evaluator.calculate_metrics(period_hours=24)
        
        assert metrics.period_hours == 24
        assert metrics.retrieval_quality is not None
        assert metrics.generation_quality is not None
        assert metrics.performance is not None
    
    @pytest.mark.asyncio
    async def test_retrieval_quality_structure(self, rag_evaluator):
        """Test retrieval quality metrics structure."""
        metrics = await rag_evaluator.calculate_metrics(period_hours=24)
        
        rq = metrics.retrieval_quality
        assert hasattr(rq, "recall_at_k")
        assert hasattr(rq, "precision_at_k")
        assert hasattr(rq, "mrr")
        assert hasattr(rq, "ndcg_at_k")
        assert hasattr(rq, "context_precision")
        assert hasattr(rq, "context_recall")
    
    @pytest.mark.asyncio
    async def test_generation_quality_structure(self, rag_evaluator):
        """Test generation quality metrics structure."""
        metrics = await rag_evaluator.calculate_metrics(period_hours=24)
        
        gq = metrics.generation_quality
        assert hasattr(gq, "faithfulness")
        assert hasattr(gq, "hallucination_rate")
        assert hasattr(gq, "answer_relevance")
        assert hasattr(gq, "citation_correctness")
    
    def test_recall_calculation(self, rag_evaluator):
        """Test recall@k calculation."""
        eval_item = {
            "relevant_ids": ["a", "b", "c"],
            "retrieved_ids": ["a", "d", "b", "e", "f"]
        }
        recall = rag_evaluator._calculate_recall(eval_item, k=5)
        assert recall == 2/3  # 2 relevant found out of 3
    
    def test_mrr_calculation(self, rag_evaluator):
        """Test MRR calculation."""
        eval_item = {
            "relevant_ids": ["b"],
            "retrieved_ids": ["a", "b", "c"]
        }
        mrr = rag_evaluator._calculate_mrr(eval_item)
        assert mrr == 0.5  # First relevant at position 2


class TestAlertingService:
    """Tests for alerting service."""
    
    def test_default_rules_loaded(self, alerting_service):
        """Test default alert rules are loaded."""
        rules = alerting_service.get_rules()
        assert len(rules) > 0
        
        # Check HLD-required rules exist
        rule_ids = [r.id for r in rules]
        assert "llm_latency_high" in rule_ids
        assert "tool_error_rate_high" in rule_ids
        assert "rag_freshness_stale" in rule_ids
        assert "cache_hit_low" in rule_ids
    
    def test_add_rule(self, alerting_service):
        """Test adding a new rule."""
        rule = AlertRule(
            id="test_rule",
            name="Test Rule",
            description="Test",
            severity=AlertSeverity.WARNING,
            condition="test > threshold",
            threshold=100.0
        )
        alerting_service.add_rule(rule)
        assert "test_rule" in alerting_service.rules
    
    def test_remove_rule(self, alerting_service):
        """Test removing a rule."""
        alerting_service.add_rule(AlertRule(
            id="to_remove",
            name="To Remove",
            description="Test",
            severity=AlertSeverity.INFO,
            condition="test > 0",
            threshold=0.0
        ))
        assert alerting_service.remove_rule("to_remove")
        assert "to_remove" not in alerting_service.rules
    
    def test_silence_rule(self, alerting_service):
        """Test silencing a rule."""
        assert alerting_service.silence_rule("llm_latency_high", 60)
        assert alerting_service.is_silenced("llm_latency_high")
    
    @pytest.mark.asyncio
    async def test_evaluate_rule_firing(self, alerting_service):
        """Test rule evaluation when condition is met."""
        rule = alerting_service.rules["llm_latency_high"]
        alert = await alerting_service.evaluate_rule(rule, current_value=5.0)  # Above 3s threshold
        
        assert alert is not None
        assert alert.status == AlertStatus.FIRING
        assert alert.value == 5.0
    
    @pytest.mark.asyncio
    async def test_evaluate_rule_not_firing(self, alerting_service):
        """Test rule evaluation when condition is not met."""
        rule = alerting_service.rules["llm_latency_high"]
        alert = await alerting_service.evaluate_rule(rule, current_value=1.0)  # Below 3s threshold
        
        assert alert is None


class TestDashboardService:
    """Tests for dashboard service."""
    
    def test_list_dashboards(self, dashboard_service):
        """Test listing dashboards."""
        dashboards = dashboard_service.list_dashboards()
        assert len(dashboards) == 6  # HLD requires 6 dashboards
    
    def test_get_dashboard(self, dashboard_service):
        """Test getting a specific dashboard."""
        dashboard = dashboard_service.get_dashboard("executive")
        assert dashboard is not None
        assert dashboard.id == "executive"
    
    def test_dashboard_panels(self, dashboard_service):
        """Test dashboard has required panels."""
        executive = dashboard_service.get_dashboard("executive")
        panel_ids = [p.id for p in executive.panels]
        
        # HLD-required panels for executive dashboard
        assert "resolution_rate" in panel_ids
        assert "time_to_resolution" in panel_ids
        assert "escalations" in panel_ids
        assert "csat" in panel_ids
        assert "safety_incidents" in panel_ids
    
    @pytest.mark.asyncio
    async def test_get_dashboard_data(self, dashboard_service):
        """Test getting dashboard with populated data."""
        dashboard = await dashboard_service.get_dashboard_data("executive", time_range_hours=24)
        
        assert dashboard is not None
        for panel in dashboard.panels:
            assert panel.data is not None


# ============== Logging Tests ==============

class TestLogging:
    """Tests for structured logging."""
    
    def test_hash_params(self):
        """Test parameter hashing."""
        params = {"key": "value", "secret": "hidden"}
        hash1 = hash_params(params)
        hash2 = hash_params(params)
        
        assert hash1 == hash2
        assert len(hash1) == 16
    
    def test_hash_ip(self):
        """Test IP hashing."""
        ip = "192.168.1.1"
        hashed = hash_ip(ip)
        
        assert len(hashed) == 16
        assert hashed != ip
    
    def test_observability_logger(self):
        """Test observability logger."""
        logger = ObservabilityLogger("test")
        logger.set_context(run_id="test-123", session_id="session-456")
        
        # Should not raise
        logger.info("Test message")
        logger.warning("Warning message")
        logger.error("Error message")
    
    def test_logger_api_request(self):
        """Test API request logging."""
        logger = ObservabilityLogger("test")
        
        # Should not raise
        logger.log_api_request(
            route="/test",
            method="GET",
            status=200,
            latency_ms=50.0
        )
    
    def test_logger_tool_call(self):
        """Test tool call logging."""
        logger = ObservabilityLogger("test")
        
        # Should not raise
        logger.log_tool_call(
            tool_id="test_tool",
            params_hash="abc123",
            latency_ms=100.0,
            outcome="ok"
        )


# ============== Schema Tests ==============

class TestSchemas:
    """Tests for Pydantic schemas."""
    
    def test_metric_event_schema(self):
        """Test MetricEvent schema."""
        event = MetricEvent(
            name="test_metric",
            value=42.0,
            timestamp=datetime.now(timezone.utc),
            labels={"env": "test"},
            category=MetricCategory.SYSTEM
        )
        assert event.name == "test_metric"
        assert event.value == 42.0
    
    def test_alert_schema(self):
        """Test Alert schema."""
        alert = Alert(
            id="alert-123",
            rule_id="test_rule",
            name="Test Alert",
            severity=AlertSeverity.WARNING,
            status=AlertStatus.FIRING,
            message="Test message",
            value=100.0,
            threshold=50.0,
            started_at=datetime.now(timezone.utc)
        )
        assert alert.severity == AlertSeverity.WARNING
        assert alert.status == AlertStatus.FIRING
    
    def test_log_entry_schema(self):
        """Test LogEntry schema."""
        entry = LogEntry(
            ts=datetime.now(timezone.utc),
            level="INFO",
            service="test",
            env="development",
            message="Test log"
        )
        assert entry.level == "INFO"


# ============== Integration Tests ==============

class TestIntegration:
    """Integration tests."""
    
    def test_full_metrics_flow(self, client):
        """Test full metrics ingestion and retrieval flow."""
        # Ingest metrics
        metrics = [
            {
                "name": "integration_test_metric",
                "value": 100.0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "labels": {"test": "true"},
                "category": "system"
            }
        ]
        response = client.post("/metrics/ingest", json=metrics)
        assert response.status_code == 200
        
        # Get evaluation metrics
        response = client.get("/metrics/agent/evaluation")
        assert response.status_code == 200
    
    def test_full_alert_flow(self, client):
        """Test full alert creation and management flow."""
        # Create rule
        rule = {
            "id": "integration_test_rule",
            "name": "Integration Test Rule",
            "description": "Test",
            "severity": "warning",
            "condition": "test > threshold",
            "threshold": 50.0,
            "duration_minutes": 1,
            "labels": {},
            "annotations": {}
        }
        response = client.post("/alerts/rules", json=rule)
        assert response.status_code == 200
        
        # Get rules
        response = client.get("/alerts/rules")
        assert response.status_code == 200
        rules = response.json()
        assert any(r["id"] == "integration_test_rule" for r in rules)
        
        # Silence rule
        response = client.post("/alerts/rules/integration_test_rule/silence?duration_minutes=10")
        assert response.status_code == 200
        
        # Delete rule
        response = client.delete("/alerts/rules/integration_test_rule")
        assert response.status_code == 200
    
    def test_dashboard_data_flow(self, client):
        """Test dashboard data retrieval flow."""
        # List dashboards
        response = client.get("/dashboards/")
        assert response.status_code == 200
        dashboards = response.json()
        
        # Get each dashboard with data
        for dashboard in dashboards:
            response = client.get(f"/dashboards/{dashboard['id']}")
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == dashboard["id"]
            assert len(data["panels"]) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
