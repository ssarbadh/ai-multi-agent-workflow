"""Structured logging configuration per HLD requirements."""

import logging
import json
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import hashlib

from app.core.config import settings


class StructuredLogFormatter(logging.Formatter):
    """
    Structured JSON log formatter following HLD logging envelope.
    
    Common envelope fields:
    - ts, level, service, env, request_id, session_id, run_id, user_id, role, ip_hash
    """
    
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": settings.SERVICE_NAME,
            "env": settings.ENVIRONMENT,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add context fields if present
        context_fields = [
            "request_id", "session_id", "run_id", "user_id", 
            "role", "ip_hash", "node", "tool_id", "operation"
        ]
        for field in context_fields:
            if hasattr(record, field):
                log_entry[field] = getattr(record, field)
        
        # Add extra data
        if hasattr(record, "extra_data") and record.extra_data:
            log_entry["data"] = record.extra_data
        
        # Add exception info
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_entry)


class ObservabilityLogger:
    """Logger with structured fields for observability."""
    
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self._context: Dict[str, Any] = {}
    
    def set_context(self, **kwargs) -> None:
        """Set context fields for subsequent log calls."""
        self._context.update(kwargs)
    
    def clear_context(self) -> None:
        """Clear context fields."""
        self._context.clear()
    
    def _log(self, level: int, message: str, extra_data: Optional[Dict] = None, **kwargs):
        """Internal log method with context injection."""
        extra = {**self._context, **kwargs}
        if extra_data:
            extra["extra_data"] = extra_data
        self.logger.log(level, message, extra=extra)
    
    def info(self, message: str, extra_data: Optional[Dict] = None, **kwargs):
        self._log(logging.INFO, message, extra_data, **kwargs)
    
    def warning(self, message: str, extra_data: Optional[Dict] = None, **kwargs):
        self._log(logging.WARNING, message, extra_data, **kwargs)
    
    def error(self, message: str, extra_data: Optional[Dict] = None, **kwargs):
        self._log(logging.ERROR, message, extra_data, **kwargs)
    
    def debug(self, message: str, extra_data: Optional[Dict] = None, **kwargs):
        self._log(logging.DEBUG, message, extra_data, **kwargs)
    
    # HLD-specific log methods
    def log_api_request(
        self,
        route: str,
        method: str,
        status: int,
        latency_ms: float,
        bytes_in: int = 0,
        bytes_out: int = 0,
        **kwargs
    ):
        """Log API request per HLD API & SSE logging spec."""
        self.info(
            f"API {method} {route} -> {status}",
            extra_data={
                "route": route,
                "method": method,
                "status": status,
                "latency_ms": latency_ms,
                "bytes_in": bytes_in,
                "bytes_out": bytes_out,
            },
            **kwargs
        )
    
    def log_sse_event(self, event_type: str, session_id: str, **kwargs):
        """Log SSE event."""
        self.info(
            f"SSE event: {event_type}",
            extra_data={"sse_event": {"type": event_type}},
            session_id=session_id,
            **kwargs
        )
    
    def log_agent_node(
        self,
        node: str,
        edge_from: Optional[str],
        edge_to: Optional[str],
        run_id: str,
        latency_ms: float,
        **kwargs
    ):
        """Log LangGraph agent node execution per HLD spec."""
        self.info(
            f"Agent node: {node}",
            extra_data={
                "node": node,
                "edge_from": edge_from,
                "edge_to": edge_to,
                "latency_ms": latency_ms,
            },
            run_id=run_id,
            **kwargs
        )
    
    def log_tool_call(
        self,
        tool_id: str,
        params_hash: str,
        latency_ms: float,
        outcome: str,
        retries: int = 0,
        rate_limited: bool = False,
        **kwargs
    ):
        """Log tool/MCP call per HLD spec."""
        self.info(
            f"Tool call: {tool_id} -> {outcome}",
            extra_data={
                "tool_id": tool_id,
                "tool_params_hash": params_hash,
                "tool_latency_ms": latency_ms,
                "tool_outcome": outcome,
                "retries": retries,
                "rate_limited": rate_limited,
            },
            **kwargs
        )
    
    def log_vm_exec(
        self,
        vm_id: str,
        cmd_hash: str,
        stdout_bytes: int,
        stderr_bytes: int,
        exit_code: int,
        masked: bool = True,
        **kwargs
    ):
        """Log VM execution per HLD spec."""
        self.info(
            f"VM exec: {vm_id} exit={exit_code}",
            extra_data={
                "vm_id": vm_id,
                "cmd_hash": cmd_hash,
                "stdout_bytes": stdout_bytes,
                "stderr_bytes": stderr_bytes,
                "exit_code": exit_code,
                "masked": masked,
            },
            **kwargs
        )
    
    def log_rag_query(
        self,
        retriever: str,
        topk: int,
        scores: list,
        reranker_used: bool,
        filters: Dict,
        latency_ms: float,
        **kwargs
    ):
        """Log RAG query per HLD spec."""
        self.info(
            f"RAG query: {retriever} topk={topk}",
            extra_data={
                "retriever": retriever,
                "topk": topk,
                "scores": scores[:5],  # Limit to top 5
                "reranker_used": reranker_used,
                "filters": filters,
                "latency_ms": latency_ms,
            },
            **kwargs
        )
    
    def log_feedback(
        self,
        message_id: str,
        feedback: str,
        comment_present: bool,
        preference_version: Optional[str] = None,
        effect_applied: bool = False,
        **kwargs
    ):
        """Log feedback per HLD spec."""
        self.info(
            f"Feedback: {message_id} -> {feedback}",
            extra_data={
                "message_id": message_id,
                "feedback": feedback,
                "comment_present": comment_present,
                "preference_profile_version": preference_version,
                "effect_applied": effect_applied,
            },
            **kwargs
        )
    
    def log_approval(
        self,
        gate_id: str,
        reason: str,
        result: str,
        await_time_ms: float,
        **kwargs
    ):
        """Log approval gate per HLD spec."""
        self.info(
            f"Approval: {gate_id} -> {result}",
            extra_data={
                "approval_gate": {"id": gate_id, "reason": reason},
                "approval_result": result,
                "await_time_ms": await_time_ms,
            },
            **kwargs
        )


def hash_params(params: Dict) -> str:
    """Hash parameters for logging (no secrets)."""
    return hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:16]


def hash_ip(ip: str) -> str:
    """Hash IP address for privacy."""
    return hashlib.sha256(ip.encode()).hexdigest()[:16]


def setup_logging() -> None:
    """Configure structured logging."""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL))
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Add structured JSON handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredLogFormatter())
    root_logger.addHandler(handler)


def get_logger(name: str) -> ObservabilityLogger:
    """Get a structured logger instance."""
    return ObservabilityLogger(name)
