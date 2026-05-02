"""Structured logging configuration for MCP service."""

import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import structlog

from app.core.config import settings


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance."""
    return structlog.get_logger(name)


class MCPLogger:
    """MCP-specific logger with audit capabilities."""

    def __init__(self, name: str = "mcp"):
        self.logger = get_logger(name)

    def tool_call(
        self,
        tool_id: str,
        server_id: str,
        tenant_id: Optional[str] = None,
        params_hash: Optional[str] = None,
        outcome: str = "ok",
        latency_ms: Optional[float] = None,
        **extra: Any,
    ) -> None:
        """Log a tool call (audit)."""
        self.logger.info(
            "tool_call",
            tool_id=tool_id,
            server_id=server_id,
            tenant_id=tenant_id,
            params_hash=params_hash,
            outcome=outcome,
            latency_ms=latency_ms,
            **extra,
        )

    def session_event(
        self,
        session_id: str,
        event_type: str,
        tenant_id: Optional[str] = None,
        **extra: Any,
    ) -> None:
        """Log a session event."""
        self.logger.info(
            "session_event",
            session_id=session_id,
            event_type=event_type,
            tenant_id=tenant_id,
            **extra,
        )

    def gateway_route(
        self,
        request_id: str,
        server_id: str,
        path: str,
        method: str,
        status: int,
        latency_ms: float,
        **extra: Any,
    ) -> None:
        """Log a gateway routing event."""
        self.logger.info(
            "gateway_route",
            request_id=request_id,
            server_id=server_id,
            path=path,
            method=method,
            status=status,
            latency_ms=latency_ms,
            **extra,
        )

    def auth_event(
        self,
        auth_type: str,
        user_id: Optional[str] = None,
        success: bool = True,
        **extra: Any,
    ) -> None:
        """Log an authentication event."""
        level = "info" if success else "warning"
        getattr(self.logger, level)(
            "auth_event",
            auth_type=auth_type,
            user_id=user_id,
            success=success,
            **extra,
        )

    def error(self, message: str, **extra: Any) -> None:
        """Log an error."""
        self.logger.error(message, **extra)

    def info(self, message: str, **extra: Any) -> None:
        """Log info."""
        self.logger.info(message, **extra)

    def warning(self, message: str, **extra: Any) -> None:
        """Log warning."""
        self.logger.warning(message, **extra)

    def debug(self, message: str, **extra: Any) -> None:
        """Log debug."""
        self.logger.debug(message, **extra)


def add_timestamp(
    logger: logging.Logger, method_name: str, event_dict: Dict[str, Any]
) -> Dict[str, Any]:
    """Add ISO timestamp to log events."""
    event_dict["ts"] = datetime.now(timezone.utc).isoformat()
    return event_dict


def add_service_info(
    logger: logging.Logger, method_name: str, event_dict: Dict[str, Any]
) -> Dict[str, Any]:
    """Add service metadata to log events."""
    event_dict["service"] = settings.SERVICE_NAME
    event_dict["env"] = settings.ENVIRONMENT
    event_dict["version"] = settings.VERSION
    return event_dict


def configure_logging() -> None:
    """Configure structured logging."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            add_timestamp,
            add_service_info,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure root logger
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.LOG_LEVEL.upper()),
    )


# Initialize logging on import
configure_logging()
logger = MCPLogger()
