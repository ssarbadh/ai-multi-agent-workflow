"""Client for Observability service integration.

Integrates with Observability service for:
- Metrics reporting (Prometheus)
- Distributed tracing (Jaeger)
- Log aggregation
- Alert management
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class ObservabilityClient:
    """
    Client for Observability service integration.
    
    Sends metrics, traces, and logs to the Observability service
    which aggregates them into Prometheus, Jaeger, and log stores.
    """
    
    def __init__(self):
        self.base_url = getattr(settings, 'OBSERVABILITY_SERVICE_URL', 'http://localhost:8004')
        self.timeout = getattr(settings, 'OBSERVABILITY_SERVICE_TIMEOUT', 10)
        self.enabled = getattr(settings, 'OBSERVABILITY_ENABLED', True)
    
    async def record_agent_run(
        self,
        run_id: str,
        agent_type: str,
        status: str,
        duration_seconds: float,
        steps_count: int = 0,
        tool_calls_count: int = 0,
        extra_data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Record agent run metrics.
        
        Args:
            run_id: Run identifier
            agent_type: Type of agent (orchestrator, provisioner, etc.)
            status: Run status (completed, failed, cancelled)
            duration_seconds: Run duration
            steps_count: Number of steps executed
            tool_calls_count: Number of tool calls made
            extra_data: Additional metadata
            
        Returns:
            True if recorded successfully
        """
        if not self.enabled:
            return True
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/metrics/agent-run",
                    json={
                        "run_id": run_id,
                        "agent_type": agent_type,
                        "status": status,
                        "duration_seconds": duration_seconds,
                        "steps_count": steps_count,
                        "tool_calls_count": tool_calls_count,
                        "timestamp": datetime.utcnow().isoformat(),
                        "extra_data": extra_data or {}
                    }
                )
                response.raise_for_status()
                return True
        except Exception as e:
            logger.warning(f"Failed to record agent run metrics: {e}")
            return False
    
    async def record_tool_call(
        self,
        run_id: str,
        tool_name: str,
        status: str,
        duration_ms: float,
        error: Optional[str] = None
    ) -> bool:
        """
        Record tool call metrics.
        
        Args:
            run_id: Run identifier
            tool_name: Name of the tool called
            status: Call status (success, failed)
            duration_ms: Call duration in milliseconds
            error: Error message if failed
            
        Returns:
            True if recorded successfully
        """
        if not self.enabled:
            return True
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/metrics/tool-call",
                    json={
                        "run_id": run_id,
                        "tool_name": tool_name,
                        "status": status,
                        "duration_ms": duration_ms,
                        "error": error,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                )
                response.raise_for_status()
                return True
        except Exception as e:
            logger.warning(f"Failed to record tool call metrics: {e}")
            return False
    
    async def record_llm_call(
        self,
        run_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        duration_ms: float,
        status: str = "success"
    ) -> bool:
        """
        Record LLM call metrics.
        
        Args:
            run_id: Run identifier
            model: LLM model used
            prompt_tokens: Number of prompt tokens
            completion_tokens: Number of completion tokens
            duration_ms: Call duration in milliseconds
            status: Call status
            
        Returns:
            True if recorded successfully
        """
        if not self.enabled:
            return True
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/metrics/llm-call",
                    json={
                        "run_id": run_id,
                        "model": model,
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": prompt_tokens + completion_tokens,
                        "duration_ms": duration_ms,
                        "status": status,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                )
                response.raise_for_status()
                return True
        except Exception as e:
            logger.warning(f"Failed to record LLM call metrics: {e}")
            return False
    
    async def start_trace(
        self,
        run_id: str,
        trace_name: str,
        parent_span_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Start a distributed trace span.
        
        Args:
            run_id: Run identifier
            trace_name: Name of the trace/span
            parent_span_id: Parent span ID if nested
            
        Returns:
            Trace context with span_id and trace_id
        """
        if not self.enabled:
            return {"span_id": "disabled", "trace_id": run_id}
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/traces/start",
                    json={
                        "run_id": run_id,
                        "trace_name": trace_name,
                        "parent_span_id": parent_span_id,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.warning(f"Failed to start trace: {e}")
            return {"span_id": "error", "trace_id": run_id}
    
    async def end_trace(
        self,
        span_id: str,
        status: str = "ok",
        error: Optional[str] = None
    ) -> bool:
        """
        End a distributed trace span.
        
        Args:
            span_id: Span identifier
            status: Span status (ok, error)
            error: Error message if failed
            
        Returns:
            True if recorded successfully
        """
        if not self.enabled:
            return True
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/traces/end",
                    json={
                        "span_id": span_id,
                        "status": status,
                        "error": error,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                )
                response.raise_for_status()
                return True
        except Exception as e:
            logger.warning(f"Failed to end trace: {e}")
            return False
    
    async def send_log(
        self,
        run_id: str,
        level: str,
        message: str,
        context: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Send structured log to observability service.
        
        Args:
            run_id: Run identifier
            level: Log level (debug, info, warning, error, critical)
            message: Log message
            context: Additional context
            
        Returns:
            True if sent successfully
        """
        if not self.enabled:
            return True
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/logs",
                    json={
                        "run_id": run_id,
                        "level": level,
                        "message": message,
                        "context": context or {},
                        "timestamp": datetime.utcnow().isoformat()
                    }
                )
                response.raise_for_status()
                return True
        except Exception as e:
            logger.warning(f"Failed to send log: {e}")
            return False
    
    async def record_workflow_step(
        self,
        run_id: str,
        workflow_id: str,
        step_number: int,
        step_name: str,
        status: str,
        duration_seconds: float,
        error: Optional[str] = None
    ) -> bool:
        """
        Record workflow step execution.
        
        Args:
            run_id: Run identifier
            workflow_id: Workflow identifier
            step_number: Step number
            step_name: Step name
            status: Step status (success, failed, skipped)
            duration_seconds: Step duration
            error: Error message if failed
            
        Returns:
            True if recorded successfully
        """
        if not self.enabled:
            return True
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/metrics/workflow-step",
                    json={
                        "run_id": run_id,
                        "workflow_id": workflow_id,
                        "step_number": step_number,
                        "step_name": step_name,
                        "status": status,
                        "duration_seconds": duration_seconds,
                        "error": error,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                )
                response.raise_for_status()
                return True
        except Exception as e:
            logger.warning(f"Failed to record workflow step: {e}")
            return False
    
    async def record_approval_gate(
        self,
        run_id: str,
        approval_id: str,
        approval_type: str,
        wait_time_seconds: float,
        approved: bool,
        approver: Optional[str] = None
    ) -> bool:
        """
        Record approval gate metrics.
        
        Args:
            run_id: Run identifier
            approval_id: Approval identifier
            approval_type: Type of approval
            wait_time_seconds: Time waited for approval
            approved: Whether approved or rejected
            approver: Who approved/rejected
            
        Returns:
            True if recorded successfully
        """
        if not self.enabled:
            return True
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/metrics/approval-gate",
                    json={
                        "run_id": run_id,
                        "approval_id": approval_id,
                        "approval_type": approval_type,
                        "wait_time_seconds": wait_time_seconds,
                        "approved": approved,
                        "approver": approver,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                )
                response.raise_for_status()
                return True
        except Exception as e:
            logger.warning(f"Failed to record approval gate: {e}")
            return False
    
    async def health_check(self) -> bool:
        """Check if Observability service is healthy."""
        if not self.enabled:
            return True
        
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/health")
                return response.status_code == 200
        except Exception as e:
            logger.warning(f"Observability service health check failed: {e}")
            return False
    
    async def get_metrics(
        self,
        run_id: Optional[str] = None,
        agent_type: Optional[str] = None,
        time_range_minutes: int = 60
    ) -> Dict[str, Any]:
        """
        Get metrics from Observability service.
        
        Args:
            run_id: Optional run ID filter
            agent_type: Optional agent type filter
            time_range_minutes: Time range for metrics
            
        Returns:
            Metrics data
        """
        if not self.enabled:
            return {}
        
        try:
            params = {"time_range_minutes": time_range_minutes}
            if run_id:
                params["run_id"] = run_id
            if agent_type:
                params["agent_type"] = agent_type
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/metrics",
                    params=params
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.warning(f"Failed to get metrics: {e}")
            return {}


# Global instance
observability_client = ObservabilityClient()
