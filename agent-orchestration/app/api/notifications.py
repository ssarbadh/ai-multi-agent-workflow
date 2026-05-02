"""Notification endpoints."""

import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from app.services.notification_service import notification_service

logger = logging.getLogger(__name__)
router = APIRouter()


class EmailRequest(BaseModel):
    """Email notification request."""
    recipient: EmailStr
    subject: str
    body: str
    run_id: str = None


@router.post("/notifications/email")
async def send_email(request: EmailRequest):
    """Send email notification."""
    try:
        await notification_service.send_email(
            recipient=request.recipient,
            subject=request.subject,
            body=request.body,
            run_id=request.run_id
        )
        return {"status": "sent", "recipient": request.recipient}
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        raise HTTPException(status_code=500, detail=str(e))
