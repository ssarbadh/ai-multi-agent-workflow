"""
Notification service for Slack and Email alerts.

Provides multi-channel notification delivery for AegisOps alerts.
"""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional
from datetime import datetime, timezone

import httpx

from app.core.config import settings
from app.models.schemas import Alert, AlertSeverity, AlertStatus

logger = logging.getLogger(__name__)


class SlackNotifier:
    """Slack webhook notification sender."""
    
    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or settings.SLACK_WEBHOOK_URL
        self._client: Optional[httpx.AsyncClient] = None
    
    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client
    
    async def close(self):
        if self._client:
            await self._client.aclose()
    
    def _get_color(self, severity: AlertSeverity) -> str:
        """Get Slack attachment color based on severity."""
        return {
            AlertSeverity.INFO: "#36a64f",      # Green
            AlertSeverity.WARNING: "#ff9800",   # Orange
            AlertSeverity.CRITICAL: "#f44336",  # Red
        }.get(severity, "#808080")
    
    def _get_emoji(self, alert: Alert) -> str:
        """Get status emoji."""
        if alert.status == AlertStatus.RESOLVED:
            return "✅"
        return {
            AlertSeverity.INFO: "ℹ️",
            AlertSeverity.WARNING: "⚠️",
            AlertSeverity.CRITICAL: "🔥",
        }.get(alert.severity, "📢")
    
    async def send_alert(self, alert: Alert) -> bool:
        """Send alert notification to Slack."""
        if not self.webhook_url:
            logger.debug("Slack webhook URL not configured, skipping")
            return False
        
        try:
            client = await self.get_client()
            emoji = self._get_emoji(alert)
            color = self._get_color(alert.severity)
            
            payload = {
                "username": "AegisOps Alerts",
                "icon_emoji": ":robot_face:",
                "attachments": [{
                    "color": color,
                    "title": f"{emoji} {alert.name}",
                    "title_link": f"{settings.GRAFANA_URL}/alerting/list",
                    "text": alert.message,
                    "fields": [
                        {"title": "Severity", "value": alert.severity.value.upper(), "short": True},
                        {"title": "Status", "value": alert.status.value.upper(), "short": True},
                        {"title": "Current Value", "value": f"{alert.value:.2f}", "short": True},
                        {"title": "Threshold", "value": f"{alert.threshold:.2f}", "short": True},
                    ],
                    "footer": "AegisOps Observability",
                    "footer_icon": "https://platform.slack-edge.com/img/default_application_icon.png",
                    "ts": int(alert.started_at.timestamp())
                }]
            }
            
            # Add resolved time if applicable
            if alert.resolved_at:
                duration = (alert.resolved_at - alert.started_at).total_seconds()
                payload["attachments"][0]["fields"].append({
                    "title": "Duration",
                    "value": f"{duration:.0f}s",
                    "short": True
                })
            
            response = await client.post(self.webhook_url, json=payload)
            response.raise_for_status()
            logger.info(f"Slack notification sent for alert: {alert.name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")
            return False


class EmailNotifier:
    """Email notification sender via SMTP."""
    
    def __init__(
        self,
        smtp_host: Optional[str] = None,
        smtp_port: Optional[int] = None,
        smtp_user: Optional[str] = None,
        smtp_password: Optional[str] = None,
        from_email: Optional[str] = None,
        recipients: Optional[List[str]] = None
    ):
        self.smtp_host = smtp_host or getattr(settings, 'SMTP_HOST', 'localhost')
        self.smtp_port = smtp_port or getattr(settings, 'SMTP_PORT', 587)
        self.smtp_user = smtp_user or getattr(settings, 'SMTP_USER', '')
        self.smtp_password = smtp_password or getattr(settings, 'SMTP_PASSWORD', '')
        self.from_email = from_email or getattr(settings, 'ALERT_FROM_EMAIL', 'alerts@aegisops.local')
        self.recipients = recipients or self._parse_recipients()
    
    def _parse_recipients(self) -> List[str]:
        """Parse recipients from settings."""
        recipients_str = getattr(settings, 'ALERT_EMAIL_RECIPIENTS', '')
        if recipients_str:
            return [r.strip() for r in recipients_str.split(',') if r.strip()]
        return []
    
    def _get_subject(self, alert: Alert) -> str:
        """Generate email subject."""
        status = "RESOLVED" if alert.status == AlertStatus.RESOLVED else "FIRING"
        return f"[AegisOps {alert.severity.value.upper()}] {status}: {alert.name}"
    
    def _get_html_body(self, alert: Alert) -> str:
        """Generate HTML email body."""
        status_color = {
            AlertStatus.FIRING: "#f44336",
            AlertStatus.RESOLVED: "#4caf50",
            AlertStatus.PENDING: "#ff9800",
        }.get(alert.status, "#808080")
        
        severity_color = {
            AlertSeverity.INFO: "#2196f3",
            AlertSeverity.WARNING: "#ff9800",
            AlertSeverity.CRITICAL: "#f44336",
        }.get(alert.severity, "#808080")
        
        resolved_section = ""
        if alert.resolved_at:
            duration = (alert.resolved_at - alert.started_at).total_seconds()
            resolved_section = f"""
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;"><strong>Resolved At</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{alert.resolved_at.strftime('%Y-%m-%d %H:%M:%S UTC')}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;"><strong>Duration</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{duration:.0f} seconds</td>
            </tr>
            """
        
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }}
                .container {{ max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                .header {{ background: {status_color}; color: white; padding: 20px; text-align: center; }}
                .content {{ padding: 20px; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
                th, td {{ text-align: left; padding: 8px; border: 1px solid #ddd; }}
                .footer {{ background: #f5f5f5; padding: 15px; text-align: center; font-size: 12px; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2 style="margin: 0;">{alert.name}</h2>
                    <p style="margin: 10px 0 0 0;">Status: {alert.status.value.upper()}</p>
                </div>
                <div class="content">
                    <p>{alert.message}</p>
                    <table>
                        <tr>
                            <td style="padding: 8px; border: 1px solid #ddd;"><strong>Severity</strong></td>
                            <td style="padding: 8px; border: 1px solid #ddd;">
                                <span style="color: {severity_color}; font-weight: bold;">{alert.severity.value.upper()}</span>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding: 8px; border: 1px solid #ddd;"><strong>Current Value</strong></td>
                            <td style="padding: 8px; border: 1px solid #ddd;">{alert.value:.2f}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px; border: 1px solid #ddd;"><strong>Threshold</strong></td>
                            <td style="padding: 8px; border: 1px solid #ddd;">{alert.threshold:.2f}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px; border: 1px solid #ddd;"><strong>Started At</strong></td>
                            <td style="padding: 8px; border: 1px solid #ddd;">{alert.started_at.strftime('%Y-%m-%d %H:%M:%S UTC')}</td>
                        </tr>
                        {resolved_section}
                    </table>
                </div>
                <div class="footer">
                    <p>AegisOps Observability Service</p>
                    <p><a href="{settings.GRAFANA_URL}/alerting/list">View in Grafana</a></p>
                </div>
            </div>
        </body>
        </html>
        """
    
    async def send_alert(self, alert: Alert) -> bool:
        """Send alert notification via email."""
        if not self.recipients:
            logger.debug("No email recipients configured, skipping")
            return False
        
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = self._get_subject(alert)
            msg['From'] = self.from_email
            msg['To'] = ', '.join(self.recipients)
            
            # Plain text version
            text_body = f"""
AegisOps Alert: {alert.name}
Status: {alert.status.value.upper()}
Severity: {alert.severity.value.upper()}

{alert.message}

Current Value: {alert.value:.2f}
Threshold: {alert.threshold:.2f}
Started At: {alert.started_at.strftime('%Y-%m-%d %H:%M:%S UTC')}

--
AegisOps Observability Service
            """
            
            msg.attach(MIMEText(text_body, 'plain'))
            msg.attach(MIMEText(self._get_html_body(alert), 'html'))
            
            # Send email
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                if self.smtp_user and self.smtp_password:
                    server.starttls()
                    server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.from_email, self.recipients, msg.as_string())
            
            logger.info(f"Email notification sent for alert: {alert.name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email notification: {e}")
            return False


class NotificationService:
    """Unified notification service for all channels."""
    
    def __init__(self):
        self.slack = SlackNotifier()
        self.email = EmailNotifier()
    
    async def close(self):
        """Close all notification clients."""
        await self.slack.close()
    
    async def send_alert(self, alert: Alert) -> dict:
        """Send alert to all configured channels."""
        results = {
            "slack": False,
            "email": False
        }
        
        # Send to Slack
        if settings.SLACK_WEBHOOK_URL:
            results["slack"] = await self.slack.send_alert(alert)
        
        # Send to Email
        if getattr(settings, 'ALERT_EMAIL_RECIPIENTS', ''):
            results["email"] = await self.email.send_alert(alert)
        
        return results
    
    async def send_test_notification(self, channel: str = "all") -> dict:
        """Send test notification to verify configuration."""
        test_alert = Alert(
            id="test-alert",
            rule_id="test-rule",
            name="Test Alert",
            severity=AlertSeverity.INFO,
            status=AlertStatus.FIRING,
            message="This is a test notification from AegisOps Observability",
            value=1.0,
            threshold=0.5,
            started_at=datetime.now(timezone.utc),
            labels={"test": "true"},
            annotations={"description": "Test notification"}
        )
        
        results = {}
        
        if channel in ["all", "slack"]:
            results["slack"] = await self.slack.send_alert(test_alert)
        
        if channel in ["all", "email"]:
            results["email"] = await self.email.send_alert(test_alert)
        
        return results


# Global instance
notification_service = NotificationService()
