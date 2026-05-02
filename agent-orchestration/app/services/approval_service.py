"""Approval service for connecting API to approval agent."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ApprovalService:
    """
    Approval service connects the approval API to the safety approval agent.
    
    This service acts as a bridge between:
    - Frontend approval responses (via API)
    - Safety approval agent (blocking execution)
    """
    
    def __init__(self):
        self._approval_agent = None
    
    def set_approval_agent(self, agent):
        """
        Connect to safety approval agent.
        
        Args:
            agent: SafetyApprovalAgent instance
        """
        self._approval_agent = agent
        logger.info("Approval service connected to safety approval agent")
    
    async def notify_approval_response(
        self,
        approval_id: str,
        approved: bool,
        response: Optional[str] = None
    ):
        """
        Notify approval agent of user response.
        
        This is called by the API when a user responds to an approval request.
        It signals the waiting agent to continue execution.
        
        Args:
            approval_id: Approval ID
            approved: Whether approved or rejected
            response: Optional response text (for password/input prompts)
        """
        if not self._approval_agent:
            logger.error("Approval agent not connected")
            return
        
        logger.info(f"Notifying approval agent: {approval_id} approved={approved}")
        
        # Signal the approval agent
        self._approval_agent.respond_to_approval(
            approval_id=approval_id,
            approved=approved,
            response=response
        )


# Global instance
approval_service = ApprovalService()
