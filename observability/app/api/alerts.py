"""Alerts API endpoints."""

from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Request

from app.models.schemas import Alert, AlertRule, AlertSeverity
from app.services.alerting import alerting_service

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("/", response_model=List[Alert])
async def get_active_alerts(
    severity: Optional[AlertSeverity] = Query(None, description="Filter by severity")
):
    """Get all currently active alerts."""
    alerts = alerting_service.get_active_alerts()
    if severity:
        alerts = [a for a in alerts if a.severity == severity]
    return alerts


@router.get("/rules", response_model=List[AlertRule])
async def get_alert_rules():
    """Get all configured alert rules."""
    return alerting_service.get_rules()


@router.post("/rules", response_model=AlertRule)
async def create_alert_rule(rule: AlertRule):
    """Create or update an alert rule."""
    alerting_service.add_rule(rule)
    return rule


@router.delete("/rules/{rule_id}")
async def delete_alert_rule(rule_id: str):
    """Delete an alert rule."""
    if alerting_service.remove_rule(rule_id):
        return {"status": "deleted", "rule_id": rule_id}
    raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")


@router.post("/rules/{rule_id}/silence")
async def silence_alert_rule(
    rule_id: str,
    duration_minutes: int = Query(60, ge=1, le=1440, description="Silence duration in minutes")
):
    """Silence an alert rule for a specified duration."""
    if alerting_service.silence_rule(rule_id, duration_minutes):
        return {
            "status": "silenced",
            "rule_id": rule_id,
            "duration_minutes": duration_minutes
        }
    raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")


@router.post("/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str,
    acknowledged_by: str = Query(..., description="User acknowledging the alert")
):
    """Acknowledge an active alert."""
    alerts = alerting_service.active_alerts
    if alert_id in alerts:
        # In production, update database
        return {
            "status": "acknowledged",
            "alert_id": alert_id,
            "acknowledged_by": acknowledged_by
        }
    raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")


# Webhook endpoint for Alertmanager
webhook_router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@webhook_router.post("/alerts")
async def alertmanager_webhook(request: Request):
    """
    Webhook endpoint for Alertmanager notifications.
    Receives alerts from Alertmanager and processes them.
    """
    try:
        payload = await request.json()
        
        # Log the alert for now
        # In production, you would process and store these alerts
        alerts = payload.get("alerts", [])
        for alert in alerts:
            alert_name = alert.get("labels", {}).get("alertname", "unknown")
            severity = alert.get("labels", {}).get("severity", "unknown")
            status = alert.get("status", "unknown")
            
            # You can add custom processing here
            # For example: store in database, send notifications, etc.
            pass
        
        return {"status": "ok", "received": len(alerts)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
