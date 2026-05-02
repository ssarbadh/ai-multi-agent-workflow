"""MCP Session Manager - handles client sessions."""

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.core.config import settings
from app.core.logging import logger
from app.core.redis_client import redis_client
from app.models.schemas import Session, SessionCreate, SessionList


class SessionManager:
    """Manages MCP client sessions."""

    def __init__(self):
        self._sessions: Dict[str, Session] = {}

    async def create_session(
        self,
        server_id: str,
        client_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> Session:
        """Create a new session."""
        session_id = str(uuid.uuid4())
        session = Session(
            session_id=session_id,
            server_id=server_id,
            client_id=client_id,
            tenant_id=tenant_id,
            status="active",
            created_at=datetime.now(timezone.utc),
            last_activity=datetime.now(timezone.utc),
            metadata=metadata or {},
        )

        self._sessions[session_id] = session

        # Store in Redis
        await redis_client.set_json(
            f"mcp:session:{session_id}",
            session.model_dump(mode="json"),
            ttl=settings.MCP_SESSION_TTL,
        )

        logger.session_event(session_id, "created", tenant_id, server_id=server_id)
        return session

    async def get_session(self, session_id: str) -> Optional[Session]:
        """Get a session by ID."""
        # Check memory first
        if session_id in self._sessions:
            return self._sessions[session_id]

        # Check Redis
        data = await redis_client.get_json(f"mcp:session:{session_id}")
        if data:
            session = Session(**data)
            self._sessions[session_id] = session
            return session

        return None

    async def update_activity(self, session_id: str) -> bool:
        """Update session last activity timestamp."""
        session = await self.get_session(session_id)
        if not session:
            return False

        session.last_activity = datetime.now(timezone.utc)
        self._sessions[session_id] = session

        # Update Redis
        await redis_client.set_json(
            f"mcp:session:{session_id}",
            session.model_dump(mode="json"),
            ttl=settings.MCP_SESSION_TTL,
        )

        return True

    async def close_session(self, session_id: str) -> bool:
        """Close a session."""
        session = await self.get_session(session_id)
        if not session:
            return False

        session.status = "closed"
        self._sessions[session_id] = session

        # Update Redis
        await redis_client.set_json(
            f"mcp:session:{session_id}",
            session.model_dump(mode="json"),
            ttl=300,  # Keep for 5 minutes after close
        )

        logger.session_event(session_id, "closed", session.tenant_id)
        return True

    async def list_sessions(
        self,
        server_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> SessionList:
        """List sessions with optional filters."""
        sessions = list(self._sessions.values())

        if server_id:
            sessions = [s for s in sessions if s.server_id == server_id]
        if tenant_id:
            sessions = [s for s in sessions if s.tenant_id == tenant_id]
        if status:
            sessions = [s for s in sessions if s.status == status]

        return SessionList(sessions=sessions, total=len(sessions))

    async def cleanup_expired(self) -> int:
        """Cleanup expired sessions."""
        now = datetime.now(timezone.utc)
        expired = []

        for session_id, session in self._sessions.items():
            age = (now - session.last_activity).total_seconds()
            if age > settings.MCP_SESSION_TTL:
                expired.append(session_id)

        for session_id in expired:
            del self._sessions[session_id]
            await redis_client.delete(f"mcp:session:{session_id}")
            logger.session_event(session_id, "expired")

        return len(expired)


# Global instance
session_manager = SessionManager()
