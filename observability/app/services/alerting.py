"""Alerting service per HLD SLO hints and alert requirements."""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
import uuid
import httpx

from app.core.config import settings
from app.models.schemas import Alert, AlertRule, AlertSeverity, AlertStatus

logger = logging.getLogger(__name__)


# Default alert rules per HLD SLO hints
DEFAULT_ALERT_RULES: List[AlertRule] = [
    AlertRule(
        id="llm_latency_high",
        name="LLM P95 Latency High",
        description="LLM p95 latency > SLO for 5 min",
        severity=AlertSeverity.WARNING,
        condition="llm_request_duration_seconds_p95 > threshold",
        threshold=3.0,  # 3 seconds
        duration_minutes=5,
        labels={"component": "llm", "category": "performance"}
    ),
    AlertRule(
        id="tool_error_rate_high",
        name="Tool Error Rate High",
        description="Tool error rate > 5% over 10 min",
        severity=AlertSeverity.WARNING,
        condition="tool_error_rate > threshold",
        threshold=0.05,
        duration_minutes=10,
        labels={"component": "tools", "category": "reliability"}
    ),
    AlertRule(
        id="approval_wait_high",
        name="Approval Wait Time High",
        description="Approval wait p95 > threshold",
        severity=AlertSeverity.WARNING,
        condition="approval_wait_time_p95 > threshold",
        threshold=300.0,  # 5 minutes
        duration_minutes=5,
        labels={"component": "approvals", "category": "efficiency"}
    ),
    AlertRule(
        id="rag_freshness_stale",
        name="RAG Index Stale",
        description="RAG freshness > 6 hrs for critical corpora",
        severity=AlertSeverity.WARNING,
        condition="rag_index_freshness_hours > threshold",
        threshold=6.0,
        duration_minutes=30,
        labels={"component": "rag", "category": "freshness"}
    ),
    AlertRule(
        id="cache_hit_low",
        name="Cache Hit Ratio Low",
        description="Cache hit ratio < 50% sustained",
        severity=AlertSeverity.WARNING,
        condition="cache_hit_ratio < threshold",
        threshold=0.5,
        duration_minutes=15,
        labels={"component": "cache", "category": "performance"}
    ),
    AlertRule(
        id="remediation_rollback_high",
        name="Remediation Rollback Rate High",
        description="Incident remediation rollback rate > 10% day-over-day",
        severity=AlertSeverity.CRITICAL,
        condition="remediation_rollback_rate > threshold",
        threshold=0.1,
        duration_minutes=60,
        labels={"component": "remediation", "category": "reliability"}
    ),
    AlertRule(
        id="sse_reconnects_spike",
        name="SSE Reconnects Spike",
        description="SSE reconnects spike > baseline + 3σ",
        severity=AlertSeverity.WARNING,
        condition="sse_reconnects_rate > baseline_3sigma",
        threshold=0.0,  # Dynamic threshold
        duration_minutes=5,
        labels={"component": "streaming", "category": "reliability"}
    ),
    AlertRule(
        id="service_unhealthy",
        name="Service Unhealthy",
        description="Service health check failing",
        severity=AlertSeverity.CRITICAL,
        condition="service_health == 0",
        threshold=0.0,
        duration_minutes=2,
        labels={"component": "infrastructure", "category": "availability"}
    ),
]


class AlertingService:
    """
    Alerting service for monitoring SLOs and sending notifications.
    
    Responsibilities:
    - Evaluate alert rules against current metrics
    - Track alert state (firing, resolved)
    - Send notifications (Slack, email, Alertmanager)
    - Manage alert silencing
    """
    
    def __init__(self):
        self.rules: Dict[str, AlertRule] = {r.id: r for r in DEFAULT_ALERT_RULES}
        self.active_alerts: Dict[str, Alert] = {}
        self.silenced_rules: Dict[str, datetime] = {}  # rule_id -> silence_until
        self._http_client: Optional[httpx.AsyncClient] = None
    
    async def get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=10.0)
        return self._http_client
    
    async def close(self):
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
    
    def add_rule(self, rule: AlertRule) -> None:
        """Add or update an alert rule."""
        self.rules[rule.id] = rule
        logger.info(f"Added alert rule: {rule.id}")
    
    def remove_rule(self, rule_id: str) -> bool:
        """Remove an alert rule."""
        if rule_id in self.rules:
            del self.rules[rule_id]
            logger.info(f"Removed alert rule: {rule_id}")
            return True
        return False
    
    def silence_rule(self, rule_id: str, duration_minutes: int) -> bool:
        """Silence an alert rule for a duration."""
        if rule_id in self.rules:
            self.silenced_rules[rule_id] = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)
            logger.info(f"Silenced alert rule {rule_id} for {duration_minutes} minutes")
            return True
        return False
    
    def is_silenced(self, rule_id: str) -> bool:
        """Check if a rule is currently silenced."""
        if rule_id in self.silenced_rules:
            if datetime.now(timezone.utc) < self.silenced_rules[rule_id]:
                return True
            else:
                del self.silenced_rules[rule_id]
        return False
    
    async def evaluate_rule(
        self,
        rule: AlertRule,
        current_value: float
    ) -> Optional[Alert]:
        """Evaluate a single alert rule against current value."""
        
        if self.is_silenced(rule.id):
            return None
        
        # Check if condition is met
        is_firing = self._check_condition(rule.condition, current_value, rule.threshold)
        
        alert_id = f"{rule.id}_{datetime.now(timezone.utc).strftime('%Y%m%d')}"
        
        if is_firing:
            if alert_id not in self.active_alerts:
                # New alert
                alert = Alert(
                    id=alert_id,
                    rule_id=rule.id,
                    name=rule.name,
                    severity=rule.severity,
                    status=AlertStatus.FIRING,
                    message=f"{rule.description}. Current value: {current_value:.2f}, Threshold: {rule.threshold:.2f}",
                    value=current_value,
                    threshold=rule.threshold,
                    started_at=datetime.now(timezone.utc),
                    labels=rule.labels,
                    annotations=rule.annotations
                )
                self.active_alerts[alert_id] = alert
                logger.warning(f"Alert firing: {rule.name}")
                await self._send_notification(alert)
                return alert
            else:
                # Update existing alert
                self.active_alerts[alert_id].value = current_value
                return self.active_alerts[alert_id]
        else:
            if alert_id in self.active_alerts:
                # Resolve alert
                alert = self.active_alerts[alert_id]
                alert.status = AlertStatus.RESOLVED
                alert.resolved_at = datetime.now(timezone.utc)
                logger.info(f"Alert resolved: {rule.name}")
                await self._send_notification(alert)
                del self.active_alerts[alert_id]
                return alert
        
        return None
    
    def _check_condition(self, condition: str, value: float, threshold: float) -> bool:
        """Check if alert condition is met."""
        if ">" in condition:
            return value > threshold
        elif "<" in condition:
            return value < threshold
        elif "==" in condition:
            return value == threshold
        return False
    
    async def _send_notification(self, alert: Alert) -> None:
        """Send alert notification to configured channels."""
        
        # Send to Alertmanager if configured
        if settings.ALERTMANAGER_URL:
            await self._send_to_alertmanager(alert)
        
        # Send to Slack if configured
        if settings.SLACK_WEBHOOK_URL:
            await self._send_to_slack(alert)
    
    async def _send_to_alertmanager(self, alert: Alert) -> None:
        """Send alert to Prometheus Alertmanager."""
        try:
            client = await self.get_http_client()
            payload = [{
                "labels": {
                    "alertname": alert.name,
                    "severity": alert.severity.value,
                    **alert.labels
                },
                "annotations": {
                    "summary": alert.message,
                    **alert.annotations
                },
                "startsAt": alert.started_at.isoformat() + "Z",
            }]
            
            if alert.resolved_at:
                payload[0]["endsAt"] = alert.resolved_at.isoformat() + "Z"
            
            await client.post(
                f"{settings.ALERTMANAGER_URL}/api/v1/alerts",
                json=payload
            )
            logger.debug(f"Sent alert to Alertmanager: {alert.name}")
        except Exception as e:
            logger.error(f"Failed to send to Alertmanager: {e}")
    
    async def _send_to_slack(self, alert: Alert) -> None:
        """Send alert to Slack webhook."""
        try:
            client = await self.get_http_client()
            
            color = {
                AlertSeverity.INFO: "#36a64f",
                AlertSeverity.WARNING: "#ff9800",
                AlertSeverity.CRITICAL: "#f44336"
            }.get(alert.severity, "#808080")
            
            status_emoji = "🔥" if alert.status == AlertStatus.FIRING else "✅"
            
            payload = {
                "attachments": [{
                    "color": color,
                    "title": f"{status_emoji} {alert.name}",
                    "text": alert.message,
                    "fields": [
                        {"title": "Severity", "value": alert.severity.value, "short": True},
                        {"title": "Status", "value": alert.status.value, "short": True},
                        {"title": "Value", "value": f"{alert.value:.2f}", "short": True},
                        {"title": "Threshold", "value": f"{alert.threshold:.2f}", "short": True},
                    ],
                    "footer": "AegisOps Observability",
                    "ts": int(alert.started_at.timestamp())
                }]
            }
            
            await client.post(settings.SLACK_WEBHOOK_URL, json=payload)
            logger.debug(f"Sent alert to Slack: {alert.name}")
        except Exception as e:
            logger.error(f"Failed to send to Slack: {e}")
    
    def get_active_alerts(self) -> List[Alert]:
        """Get all currently active alerts."""
        return list(self.active_alerts.values())
    
    def get_rules(self) -> List[AlertRule]:
        """Get all alert rules."""
        return list(self.rules.values())


# Global instance
alerting_service = AlertingService()
