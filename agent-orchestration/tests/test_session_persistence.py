"""Tests for session persistence."""

import pytest
import asyncio
from datetime import datetime
from sqlalchemy import select

from app.models.models import Session, Message
from app.core.database import AsyncSessionLocal


@pytest.mark.asyncio
async def test_create_session():
    """Test creating a session persists to database."""
    async with AsyncSessionLocal() as db:
        # Create session
        session = Session(
            id="test_session_1",
            title="Test Session",
            status="active",
            type="service-request",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(session)
        await db.commit()
        
        # Verify it exists
        result = await db.execute(select(Session).where(Session.id == "test_session_1"))
        retrieved = result.scalar_one_or_none()
        
        assert retrieved is not None
        assert retrieved.title == "Test Session"
        assert retrieved.status == "active"
        
        # Cleanup
        await db.delete(retrieved)
        await db.commit()


@pytest.mark.asyncio
async def test_session_survives_restart():
    """Test session persists across database reconnections."""
    session_id = "test_session_restart"
    
    # Create session in first connection
    async with AsyncSessionLocal() as db:
        session = Session(
            id=session_id,
            title="Restart Test",
            status="active",
            type="service-request",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(session)
        await db.commit()
    
    # Retrieve in new connection (simulates restart)
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Session).where(Session.id == session_id))
        retrieved = result.scalar_one_or_none()
        
        assert retrieved is not None
        assert retrieved.title == "Restart Test"
        
        # Cleanup
        await db.delete(retrieved)
        await db.commit()


@pytest.mark.asyncio
async def test_message_persistence():
    """Test messages persist to database."""
    session_id = "test_session_messages"
    
    async with AsyncSessionLocal() as db:
        # Create session
        session = Session(
            id=session_id,
            title="Message Test",
            status="active",
            type="service-request",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(session)
        await db.commit()
        
        # Create messages
        msg1 = Message(
            id="msg_1",
            session_id=session_id,
            role="user",
            content="Hello",
            created_at=datetime.utcnow()
        )
        msg2 = Message(
            id="msg_2",
            session_id=session_id,
            role="assistant",
            content="Hi there!",
            created_at=datetime.utcnow()
        )
        db.add(msg1)
        db.add(msg2)
        await db.commit()
        
        # Retrieve messages
        result = await db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at)
        )
        messages = result.scalars().all()
        
        assert len(messages) == 2
        assert messages[0].content == "Hello"
        assert messages[1].content == "Hi there!"
        
        # Cleanup
        await db.delete(session)
        await db.commit()


@pytest.mark.asyncio
async def test_cascade_delete():
    """Test deleting session cascades to messages."""
    session_id = "test_session_cascade"
    
    async with AsyncSessionLocal() as db:
        # Create session with messages
        session = Session(
            id=session_id,
            title="Cascade Test",
            status="active",
            type="service-request",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(session)
        await db.commit()
        
        msg = Message(
            id="msg_cascade",
            session_id=session_id,
            role="user",
            content="Test",
            created_at=datetime.utcnow()
        )
        db.add(msg)
        await db.commit()
        
        # Delete session
        await db.delete(session)
        await db.commit()
        
        # Verify messages are also deleted
        result = await db.execute(
            select(Message).where(Message.session_id == session_id)
        )
        messages = result.scalars().all()
        
        assert len(messages) == 0


@pytest.mark.asyncio
async def test_session_list_pagination():
    """Test listing sessions with pagination."""
    async with AsyncSessionLocal() as db:
        # Create multiple sessions
        sessions = []
        for i in range(5):
            session = Session(
                id=f"test_session_page_{i}",
                title=f"Session {i}",
                status="active",
                type="service-request",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            sessions.append(session)
            db.add(session)
        await db.commit()
        
        # Query with pagination
        result = await db.execute(
            select(Session)
            .where(Session.id.like("test_session_page_%"))
            .order_by(Session.created_at.desc())
            .limit(3)
            .offset(0)
        )
        page1 = result.scalars().all()
        
        assert len(page1) == 3
        
        # Cleanup
        for session in sessions:
            await db.delete(session)
        await db.commit()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
