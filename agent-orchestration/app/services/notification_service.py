"""Notification service for email and chat."""

import logging
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class NotificationService:
    """Service for sending notifications via email and chat."""
    
    async def send_email(
        self,
        recipient: str,
        subject: str,
        body: str,
        run_id: Optional[str] = None
    ) -> None:
        """
        Send email notification.
        
        Args:
            recipient: Email address
            subject: Email subject
            body: Email body (HTML or plain text)
            run_id: Optional run ID for tracking
        """
        try:
            # Create message
            message = MIMEMultipart("alternative")
            message["From"] = settings.SMTP_FROM_EMAIL
            message["To"] = recipient
            message["Subject"] = subject
            
            # Add body
            part = MIMEText(body, "html" if "<html>" in body else "plain")
            message.attach(part)
            
            # Send email
            await aiosmtplib.send(
                message,
                hostname=settings.SMTP_HOST,
                port=settings.SMTP_PORT,
                username=settings.SMTP_USERNAME,
                password=settings.SMTP_PASSWORD,
                use_tls=settings.SMTP_USE_TLS,
            )
            
            logger.info(f"Email sent to {recipient}: {subject}")
            
        except Exception as e:
            logger.error(f"Failed to send email: {e}", exc_info=True)
            raise


# Global instance
notification_service = NotificationService()
