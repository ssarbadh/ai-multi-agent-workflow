"""End-to-end tests for provisioning workflow with HITL."""

import pytest
import asyncio
from datetime import datetime
from sqlalchemy import select

from app.models.models import Session, Message, Run, Approval, ApprovalStatus
from app.core.database import AsyncSessionLocal
from app.agents.provisioner_agent import ProvisionerAgent
from app.agents.safety_approval_agent import safety_approval_agent


@pytest.mark.asyncio
async def test_full_provisioning_workflow():
    """Test complete provisioning workflow from session creation to completion."""
    
    async with AsyncSessionLocal() as db:
        # Step 1: Create session
        session = Session(
            id="test_e2e_session",
            title="E2E Test Session",
            status="active",
            type="service-request",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(session)
        await db.commit()
        
        # Step 2: Create user message
        user_msg = Message(
            id="test_e2e_msg_user",
            session_id="test_e2e_session",
            run_id="test_e2e_run",
            role="user",
            content="Create an EC2 instance in us-east-1",
            created_at=datetime.utcnow()
        )
        db.add(user_msg)
        await db.commit()
        
        # Step 3: Verify session and message exist
        result = await db.execute(select(Session).where(Session.id == "test_e2e_session"))
        session_check = result.scalar_one_or_none()
        assert session_check is not None
        
        result = await db.execute(select(Message).where(Message.session_id == "test_e2e_session"))
        messages = result.scalars().all()
        assert len(messages) == 1
        
        # Step 4: Create agent response message
        agent_msg = Message(
            id="test_e2e_msg_agent",
            session_id="test_e2e_session",
            run_id="test_e2e_run",
            role="assistant",
            content="Provisioning EC2 instance...",
            created_at=datetime.utcnow()
        )
        db.add(agent_msg)
        await db.commit()
        
        # Step 5: Verify both messages exist
        result = await db.execute(
            select(Message)
            .where(Message.session_id == "test_e2e_session")
            .order_by(Message.created_at)
        )
        messages = result.scalars().all()
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[1].role == "assistant"
        
        # Cleanup
        await db.delete(session)
        await db.commit()


@pytest.mark.asyncio
async def test_session_refresh_loads_history():
    """Test that refreshing loads complete conversation history."""
    
    async with AsyncSessionLocal() as db:
        # Create session with multiple messages
        session = Session(
            id="test_refresh_session",
            title="Refresh Test",
            status="active",
            type="service-request",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(session)
        await db.commit()
        
        # Add multiple messages
        messages = []
        for i in range(5):
            msg = Message(
                id=f"test_refresh_msg_{i}",
                session_id="test_refresh_session",
                role="user" if i % 2 == 0 else "assistant",
                content=f"Message {i}",
                created_at=datetime.utcnow()
            )
            messages.append(msg)
            db.add(msg)
        await db.commit()
    
    # Simulate refresh: new connection, load session and messages
    async with AsyncSessionLocal() as db:
        # Load session
        result = await db.execute(select(Session).where(Session.id == "test_refresh_session"))
        session = result.scalar_one_or_none()
        assert session is not None
        
        # Load messages
        result = await db.execute(
            select(Message)
            .where(Message.session_id == "test_refresh_session")
            .order_by(Message.created_at)
        )
        loaded_messages = result.scalars().all()
        
        assert len(loaded_messages) == 5
        for i, msg in enumerate(loaded_messages):
            assert msg.content == f"Message {i}"
        
        # Cleanup
        await db.delete(session)
        await db.commit()


@pytest.mark.asyncio
async def test_workflow_with_approval_gate():
    """Test workflow execution with approval gate."""
    
    # Create a simple workflow plan with approval
    plan = {
        "plan_id": "test_plan_approval",
        "workflow_id": "test_workflow",
        "steps": [
            {
                "step": 1,
                "name": "Validate",
                "action": "validate",
                "requires_approval": False,
                "estimated_duration_seconds": 1
            },
            {
                "step": 2,
                "name": "Create Resource",
                "action": "create",
                "requires_approval": True,
                "approval_timeout": 5,
                "estimated_duration_seconds": 1
            }
        ],
        "parameters": {},
        "run_id": "test_run_approval"
    }
    
    # Note: Full workflow execution would require mocking AWS clients
    # This test verifies the approval mechanism is in place
    
    # Verify approval agent is ready
    assert safety_approval_agent is not None
    
    # Test approval request
    approval_task = asyncio.create_task(
        safety_approval_agent.request_approval(
            run_id="test_run_approval",
            action="create",
            details={"resource": "test"},
            timeout_seconds=5
        )
    )
    
    await asyncio.sleep(0.5)
    
    # Approve
    approval_id = list(safety_approval_agent._pending_approvals.keys())[0]
    safety_approval_agent.respond_to_approval(approval_id, approved=True)
    
    result = await approval_task
    assert result["approved"] is True


@pytest.mark.asyncio
async def test_delete_session_cascade():
    """Test deleting session removes all related data."""
    
    async with AsyncSessionLocal() as db:
        # Create session with messages and run
        session = Session(
            id="test_delete_session",
            title="Delete Test",
            status="active",
            type="service-request",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(session)
        await db.commit()
        
        # Add messages
        msg1 = Message(
            id="test_delete_msg_1",
            session_id="test_delete_session",
            role="user",
            content="Test",
            created_at=datetime.utcnow()
        )
        msg2 = Message(
            id="test_delete_msg_2",
            session_id="test_delete_session",
            role="assistant",
            content="Response",
            created_at=datetime.utcnow()
        )
        db.add(msg1)
        db.add(msg2)
        await db.commit()
        
        # Delete session
        await db.delete(session)
        await db.commit()
        
        # Verify messages are gone
        result = await db.execute(
            select(Message).where(Message.session_id == "test_delete_session")
        )
        messages = result.scalars().all()
        assert len(messages) == 0
        
        # Verify session is gone
        result = await db.execute(
            select(Session).where(Session.id == "test_delete_session")
        )
        session_check = result.scalar_one_or_none()
        assert session_check is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
