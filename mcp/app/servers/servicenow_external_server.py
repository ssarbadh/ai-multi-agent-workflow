"""ServiceNow MCP adapter server using direct REST API calls."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings
from app.core.logging import logger
from app.servers.base import BaseMCPServer


class ServiceNowExternalMCPServer(BaseMCPServer):
    """Adapter exposing incident history search as MCP tool."""

    def __init__(self):
        super().__init__(
            name="servicenow-mcp",
            version="0.1.0",
            description="ServiceNow tools for incident lookup",
        )
        self._http_client: Optional[httpx.AsyncClient] = None
        self._instance_url = settings.SNOW_INSTANCE_URL.rstrip("/")
        self._username = settings.SNOW_USERNAME
        self._password = settings.SNOW_PASSWORD

    async def initialize(self) -> None:
        if not settings.SERVICENOW_MCP_ENABLED:
            logger.info("ServiceNow MCP adapter disabled by configuration")
            return

        self._http_client = httpx.AsyncClient(timeout=settings.SERVICENOW_MCP_TIMEOUT_SECONDS)

        self.register_tool(
            name="servicenow_search_incidents",
            description="Search ServiceNow incidents using encoded query",
            handler=self._search_incidents,
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
        )

        logger.info("ServiceNow MCP adapter initialized", instance=self._instance_url)

    async def _search_incidents(self, query: str, limit: int = 10) -> Dict[str, Any]:
        if not self._http_client:
            return {"type": "text", "text": "ServiceNow MCP adapter client not initialized"}

        if not self._username or not self._password:
            return {"type": "text", "text": "ServiceNow credentials are not configured"}

        endpoint = f"{self._instance_url}/api/now/table/incident"
        params = {
            "sysparm_query": query,
            "sysparm_limit": limit,
            "sysparm_fields": "sys_id,number,short_description,state,sys_updated_on,priority,impact,urgency",
        }
        headers = {"Accept": "application/json"}

        try:
            response = await self._http_client.get(
                endpoint,
                params=params,
                headers=headers,
                auth=(self._username, self._password),
            )
            response.raise_for_status()
            payload = response.json()
            result = payload.get("result", [])
            return {"type": "text", "text": json.dumps({"incidents": result}, ensure_ascii=True)}
        except Exception as exc:  # noqa: BLE001
            return {"type": "text", "text": f"ServiceNow query failed: {exc}"}

    async def cleanup(self) -> None:
        if self._http_client:
            await self._http_client.aclose()

