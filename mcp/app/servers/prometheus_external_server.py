"""External Prometheus adapter server.

This server exposes Prometheus tools inside AegisOps MCP by querying a
Prometheus HTTP API endpoint directly.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings
from app.core.logging import logger
from app.servers.base import BaseMCPServer


class PrometheusExternalMCPServer(BaseMCPServer):
    """Adapter that proxies tool calls to a public Prometheus MCP server."""

    def __init__(self):
        super().__init__(
            name="prometheus-server",
            version="0.1.0",
            description="Prometheus tools proxied from a public MCP server",
        )
        self._http_client: Optional[httpx.AsyncClient] = None
        self._base_url = settings.PROMETHEUS_MCP_URL.rstrip("/")
        self._token = settings.PROMETHEUS_MCP_BEARER_TOKEN

    async def initialize(self) -> None:
        """Initialize and register proxied Prometheus tools."""
        if not settings.PROMETHEUS_MCP_ENABLED:
            logger.info("Prometheus MCP adapter disabled by configuration")
            return

        self._http_client = httpx.AsyncClient(
            timeout=settings.PROMETHEUS_MCP_TIMEOUT_SECONDS
        )

        # Expose stable internal tool names regardless of upstream naming.
        self.register_tool(
            name="prometheus_execute_query",
            description="Execute a PromQL instant query",
            handler=self._execute_query,
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "PromQL query"},
                },
                "required": ["query"],
            },
        )
        self.register_tool(
            name="prometheus_execute_range_query",
            description="Execute a PromQL range query",
            handler=self._execute_range_query,
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "start_time": {"type": "string", "description": "ISO8601/RFC3339 start time"},
                    "end_time": {"type": "string", "description": "ISO8601/RFC3339 end time"},
                    "step": {"type": "string", "description": "Range step, e.g. 30s, 1m"},
                },
                "required": ["query", "start_time", "end_time", "step"],
            },
        )
        self.register_tool(
            name="prometheus_list_metrics",
            description="List available Prometheus metrics",
            handler=self._list_metrics,
            input_schema={
                "type": "object",
                "properties": {},
            },
        )
        self.register_tool(
            name="prometheus_get_metric_metadata",
            description="Get metadata for a Prometheus metric",
            handler=self._get_metric_metadata,
            input_schema={
                "type": "object",
                "properties": {
                    "metric": {"type": "string", "description": "Metric name"},
                },
            },
        )
        self.register_tool(
            name="prometheus_get_targets",
            description="Get Prometheus scrape target health",
            handler=self._get_targets,
            input_schema={
                "type": "object",
                "properties": {},
            },
        )
        self.register_tool(
            name="prometheus_health_check",
            description="Check upstream Prometheus MCP server health",
            handler=self._health_check,
            input_schema={
                "type": "object",
                "properties": {},
            },
        )

        logger.info("Prometheus MCP adapter initialized", upstream=self._base_url)

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def _get_json(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Call Prometheus HTTP API and normalize response as text content."""
        if not self._http_client:
            return {"type": "text", "text": "Prometheus MCP adapter client not initialized"}
        try:
            response = await self._http_client.get(
                f"{self._base_url}{path}",
                params=params or {},
                headers=self._headers(),
            )
            response.raise_for_status()
            return {"type": "text", "text": json.dumps(response.json(), ensure_ascii=True)}
        except Exception as exc:  # noqa: BLE001
            return {"type": "text", "text": f"Prometheus API request failed ({path}): {exc}"}

    @staticmethod
    def _normalize_upstream_response(data: Any) -> Dict[str, Any]:
        """Normalize different upstream response shapes to MCP text content."""
        if isinstance(data, dict):
            # AegisOps MCP-style response: {"content":[...], "isError":...}
            if "content" in data and isinstance(data.get("content"), list):
                content = data.get("content") or []
                if content and isinstance(content[0], dict):
                    first = content[0]
                    text = first.get("text")
                    if text is not None:
                        return {"type": "text", "text": str(text)}
                    return {"type": "text", "text": json.dumps(first, ensure_ascii=True)}
                return {"type": "text", "text": json.dumps(content, ensure_ascii=True)}

            # Already MCP content item shape
            if "type" in data and "text" in data:
                return {"type": "text", "text": str(data.get("text", ""))}

            return {"type": "text", "text": json.dumps(data, ensure_ascii=True)}

        if isinstance(data, list):
            return {"type": "text", "text": json.dumps(data, ensure_ascii=True)}

        return {"type": "text", "text": str(data)}

    async def _execute_query(self, query: str) -> Dict[str, Any]:
        return await self._get_json("/api/v1/query", {"query": query})

    async def _execute_range_query(
        self,
        query: str,
        start_time: str,
        end_time: str,
        step: str,
    ) -> Dict[str, Any]:
        return await self._get_json(
            "/api/v1/query_range",
            {
                "query": query,
                "start": start_time,
                "end": end_time,
                "step": step,
            },
        )

    async def _list_metrics(self) -> Dict[str, Any]:
        return await self._get_json("/api/v1/label/__name__/values", {})

    async def _get_metric_metadata(self, metric: Optional[str] = None) -> Dict[str, Any]:
        args: Dict[str, Any] = {}
        if metric:
            args["metric"] = metric
        return await self._get_json("/api/v1/metadata", args)

    async def _get_targets(self) -> Dict[str, Any]:
        return await self._get_json("/api/v1/targets", {})

    async def _health_check(self) -> Dict[str, Any]:
        if not self._http_client:
            return {"type": "text", "text": "Prometheus MCP adapter client not initialized"}
        try:
            response = await self._http_client.get(
                f"{self._base_url}/-/healthy",
                headers=self._headers(),
            )
            response.raise_for_status()
            return {"type": "text", "text": f"Prometheus healthy: {response.text.strip()}"}
        except Exception as exc:  # noqa: BLE001
            return {"type": "text", "text": f"Prometheus health check failed: {exc}"}

    async def cleanup(self) -> None:
        if self._http_client:
            await self._http_client.aclose()
