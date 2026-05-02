"""External New Relic MCP adapter server."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings
from app.core.logging import logger
from app.servers.base import BaseMCPServer


class NewRelicExternalMCPServer(BaseMCPServer):
    """Adapter that proxies tool calls to external New Relic MCP."""

    def __init__(self):
        super().__init__(
            name="newrelic-mcp",
            version="0.1.0",
            description="New Relic observability tools proxied via external MCP",
        )
        self._http_client: Optional[httpx.AsyncClient] = None
        self._base_url = settings.NEWRELIC_MCP_URL.rstrip("/")
        self._token = settings.NEWRELIC_MCP_BEARER_TOKEN

    async def initialize(self) -> None:
        if not settings.NEWRELIC_MCP_ENABLED:
            logger.info("New Relic MCP adapter disabled by configuration")
            return

        self._http_client = httpx.AsyncClient(timeout=settings.NEWRELIC_MCP_TIMEOUT_SECONDS)

        self.register_tool(
            name="newrelic_query_logs",
            description="Query New Relic logs for a service/incident",
            handler=self._query_logs,
            input_schema={
                "type": "object",
                "properties": {
                    "service": {"type": "string"},
                    "query": {"type": "string"},
                    "time_range": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        )
        self.register_tool(
            name="newrelic_nrql_query",
            description="Execute NRQL query through New Relic MCP",
            handler=self._nrql_query,
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "service": {"type": "string"},
                    "time_range": {"type": "string"},
                    "window": {"type": "string"},
                },
            },
        )
        self.register_tool(
            name="newrelic_list_alert_violations",
            description="List active New Relic alert violations",
            handler=self._list_alert_violations,
            input_schema={
                "type": "object",
                "properties": {
                    "service": {"type": "string"},
                    "time_range": {"type": "string"},
                    "state": {"type": "string"},
                },
            },
        )

        logger.info("New Relic MCP adapter initialized", upstream=self._base_url)

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def _call_upstream_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self._http_client:
            return {"type": "text", "text": "New Relic MCP adapter client not initialized"}

        payload = {"name": tool_name, "arguments": arguments or {}}
        errors = []

        for path in ("/api/v1/tools/call", "/tools/call"):
            try:
                response = await self._http_client.post(
                    f"{self._base_url}{path}",
                    json=payload,
                    headers=self._headers(),
                )
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                return self._normalize_upstream_response(response.json())
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{path}: {exc}")

        return {
            "type": "text",
            "text": f"Failed to call upstream New Relic MCP tool '{tool_name}'. Attempts: {', '.join(errors)}",
        }

    @staticmethod
    def _normalize_upstream_response(data: Any) -> Dict[str, Any]:
        if isinstance(data, dict):
            if "content" in data and isinstance(data.get("content"), list):
                content = data.get("content") or []
                if content and isinstance(content[0], dict):
                    return content[0]
                return {"type": "text", "text": json.dumps(content, ensure_ascii=True)}
            if "type" in data and "text" in data:
                return {"type": "text", "text": str(data.get("text", ""))}
            return {"type": "text", "text": json.dumps(data, ensure_ascii=True)}
        if isinstance(data, list):
            return {"type": "text", "text": json.dumps(data, ensure_ascii=True)}
        return {"type": "text", "text": str(data)}

    async def _query_logs(
        self,
        service: str = "",
        query: str = "",
        time_range: str = "1h",
        limit: int = 100,
    ) -> Dict[str, Any]:
        return await self._call_upstream_tool(
            "query_logs",
            {"service": service, "query": query, "time_range": time_range, "limit": limit},
        )

    async def _nrql_query(
        self,
        query: str = "",
        service: str = "",
        time_range: str = "1h",
        window: str = "5m",
    ) -> Dict[str, Any]:
        return await self._call_upstream_tool(
            "nrql_query",
            {"query": query, "service": service, "time_range": time_range, "window": window},
        )

    async def _list_alert_violations(
        self,
        service: str = "",
        time_range: str = "1h",
        state: str = "open",
    ) -> Dict[str, Any]:
        return await self._call_upstream_tool(
            "list_alert_violations",
            {"service": service, "time_range": time_range, "state": state},
        )

    async def cleanup(self) -> None:
        if self._http_client:
            await self._http_client.aclose()

