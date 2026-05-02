"""Tests for HITL (Human-In-The-Loop) workflow."""

import pytest
import asyncio
from datetime import datetime

from app.agents.safety_approval_agent import SafetyApprovalAgent
from app.models.models import Approval, ApprovalStatus
from app.core.database import AsyncSessionLocal


@pytest.mark.asyncio
async def test_approval_blocking():
    """Test that approval request blocks execution."""
    agent = SafetyApprovalAgent()
    
    # Start approval request in background
    approval_task = asyncio.create_task(
        agent.request_approval(
            run_id="test_run_1",
            action="create_vm",
            details={"vm_name": "test-vm"},
            timeout_seconds=5
        )
    )
    
    # Wait a bit to ensure it's blocking
    await asyncio.sleep(0.5)
    
    # Task should not be done yet (still waiting)
    assert not approval_task.done()
    
    # Approve it
    approval_id = list(agent._pending_approvals.keys())[0]
    agent.respond_to_approval(approval_id, approved=True)
    
    # Now it should complete
    result = await approval_task
    
    assert result["approved"] is True
    assert result["status"] == "approved"


@pytest.mark.asyncio
async def test_approval_rejection():
    """Test that rejection stops execution."""
    agent = SafetyApprovalAgent()
    
    # Start approval request
    approval_task = asyncio.create_task(
        agent.request_approval(
            run_id="test_run_2",
            action="delete_vm",
            details={"vm_name": "prod-vm"},
            timeout_seconds=5
        )
    )
    
    await asyncio.sleep(0.5)
    
    # Reject it
    approval_id = list(agent._pending_approvals.keys())[0]
    agent.respond_to_approval(approval_id, approved=False, comment="Too risky")
    
    # Get result
    result = await approval_task
    
    assert result["approved"] is False
    assert result["status"] == "rejected"


@pytest.mark.asyncio
async def test_approval_timeout():
    """Test that approval times out correctly."""
    agent = SafetyApprovalAgent()
    
    # Start approval with short timeout
    approval_task = asyncio.create_task(
        agent.request_approval(
            run_id="test_run_3",
            action="create_vm",
            details={},
            timeout_seconds=1
        )
    )
    
    # Don't respond, let it timeout
    result = await approval_task
    
    assert result["approved"] is False
    assert result["status"] == "timeout"


@pytest.mark.asyncio
async def test_password_prompt():
    """Test password prompt functionality."""
    agent = SafetyApprovalAgent()
    
    # Start password request
    password_task = asyncio.create_task(
        agent.request_password(
            run_id="test_run_4",
            prompt="Enter sudo password:",
            timeout_seconds=5
        )
    )
    
    await asyncio.sleep(0.5)
    
    # Provide password
    approval_id = list(agent._pending_approvals.keys())[0]
    agent.respond_to_approval(approval_id, approved=True, response="secret123")
    
    # Get result
    result = await password_task
    
    assert result["password"] == "secret123"
    assert result["status"] == "received"


@pytest.mark.asyncio
async def test_approval_database_persistence():
    """Test approval requests are saved to database."""
    async with AsyncSessionLocal() as db:
        # Create approval
        approval = Approval(
            id="test_approval_1",
            run_id="test_run_5",
            approval_type="workflow_step",
            prompt="Approve step 2?",
            context={"step": 2, "action": "create_vm"},
            status=ApprovalStatus.PENDING,
            requested_at=datetime.utcnow(),
            timeout_seconds=300
        )
        db.add(approval)
        await db.commit()
        
        # Verify it exists
        from sqlalchemy import select
        result = await db.execute(select(Approval).where(Approval.id == "test_approval_1"))
        retrieved = result.scalar_one_or_none()
        
        assert retrieved is not None
        assert retrieved.prompt == "Approve step 2?"
        assert retrieved.status == ApprovalStatus.PENDING
        
        # Cleanup
        await db.delete(retrieved)
        await db.commit()


@pytest.mark.asyncio
async def test_multiple_concurrent_approvals():
    """Test handling multiple approval requests concurrently."""
    agent = SafetyApprovalAgent()
    
    # Start multiple approval requests
    task1 = asyncio.create_task(
        agent.request_approval(
            run_id="test_run_6",
            action="action1",
            details={},
            timeout_seconds=10
        )
    )
    
    task2 = asyncio.create_task(
        agent.request_approval(
            run_id="test_run_7",
            action="action2",
            details={},
            timeout_seconds=10
        )
    )
    
    await asyncio.sleep(0.5)
    
    # Both should be pending
    assert not task1.done()
    assert not task2.done()
    assert len(agent._pending_approvals) == 2
    
    # Approve both
    approval_ids = list(agent._pending_approvals.keys())
    agent.respond_to_approval(approval_ids[0], approved=True)
    agent.respond_to_approval(approval_ids[1], approved=True)
    
    # Both should complete
    result1 = await task1
    result2 = await task2
    
    assert result1["approved"] is True
    assert result2["approved"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
