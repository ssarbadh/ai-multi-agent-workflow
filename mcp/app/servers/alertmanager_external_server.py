"""External Alertmanager adapter server."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.core.logging import logger
from app.servers.base import BaseMCPServer


class AlertmanagerExternalMCPServer(BaseMCPServer):
    """Adapter that proxies alert tools to external Alertmanager MCP."""

    def __init__(self):
        super().__init__(
            name="alertmanager-mcp",
            version="0.1.0",
            description="Alertmanager tools proxied from external MCP server",
        )
        self._http_client: Optional[httpx.AsyncClient] = None
        self._base_url = settings.ALERTMANAGER_MCP_URL.rstrip("/")
        self._username = settings.ALERTMANAGER_MCP_USERNAME
        self._password = settings.ALERTMANAGER_MCP_PASSWORD
        self._token = settings.ALERTMANAGER_MCP_BEARER_TOKEN

    async def initialize(self) -> None:
        if not settings.ALERTMANAGER_MCP_ENABLED:
            logger.info("Alertmanager MCP adapter disabled by configuration")
            return

        self._http_client = httpx.AsyncClient(timeout=settings.ALERTMANAGER_MCP_TIMEOUT_SECONDS)

        self.register_tool(
            name="alertmanager_get_alerts",
            description="Get active alerts from Alertmanager",
            handler=self._get_alerts,
            input_schema={
                "type": "object",
                "properties": {
                    "filter": {"type": "string"},
                    "filters": {"type": "array", "items": {"type": "string"}},
                    "active": {"type": "boolean"},
                    "silenced": {"type": "boolean"},
                    "inhibited": {"type": "boolean"},
                    "count": {"type": "integer"},
                    "offset": {"type": "integer"},
                },
            },
        )
        self.register_tool(
            name="alertmanager_get_alert_groups",
            description="Get alert groups from Alertmanager",
            handler=self._get_alert_groups,
            input_schema={
                "type": "object",
                "properties": {
                    "active": {"type": "boolean"},
                    "silenced": {"type": "boolean"},
                    "inhibited": {"type": "boolean"},
                    "count": {"type": "integer"},
                    "offset": {"type": "integer"},
                },
            },
        )

        logger.info("Alertmanager MCP adapter initialized", upstream=self._base_url)

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def _get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        if not self._http_client:
            return {"error": "Alertmanager adapter client not initialized"}
        response = await self._http_client.get(
            f"{self._base_url}{path}",
            params=params or {},
            headers=self._headers(),
            auth=(self._username, self._password) if self._username and self._password else None,
        )
        response.raise_for_status()
        return response.json()

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

    async def _get_alerts(
        self,
        filter: str = "",
        filters: Optional[List[str]] = None,
        active: bool = True,
        silenced: bool = False,
        inhibited: bool = False,
        count: int = 10,
        offset: int = 0,
    ) -> Dict[str, Any]:
        try:
            params: Dict[str, Any] = {
                "active": str(active).lower(),
                "silenced": str(silenced).lower(),
                "inhibited": str(inhibited).lower(),
            }
            all_filters: List[str] = []
            if filter:
                all_filters.append(filter)
            if filters:
                all_filters.extend([f for f in filters if isinstance(f, str) and f.strip()])
            if all_filters:
                # Alertmanager API accepts repeated filter query params.
                params["filter"] = all_filters

            data = await self._get_json("/api/v2/alerts", params)
            if isinstance(data, list):
                if count > 0:
                    data = data[offset : offset + count]
                elif offset > 0:
                    data = data[offset:]
            return {"type": "text", "text": json.dumps(data, ensure_ascii=True)}
        except Exception as exc:  # noqa: BLE001
            return {"type": "text", "text": f"Failed to fetch alerts from Alertmanager: {exc}"}

    async def _get_alert_groups(
        self,
        active: bool = True,
        silenced: bool = False,
        inhibited: bool = False,
        count: int = 5,
        offset: int = 0,
    ) -> Dict[str, Any]:
        try:
            params: Dict[str, Any] = {
                "active": str(active).lower(),
                "silenced": str(silenced).lower(),
                "inhibited": str(inhibited).lower(),
            }
            data = await self._get_json("/api/v2/alerts/groups", params)
            if isinstance(data, list):
                if count > 0:
                    data = data[offset : offset + count]
                elif offset > 0:
                    data = data[offset:]
            return {"type": "text", "text": json.dumps(data, ensure_ascii=True)}
        except Exception as exc:  # noqa: BLE001
            return {"type": "text", "text": f"Failed to fetch alert groups from Alertmanager: {exc}"}

    async def cleanup(self) -> None:
        if self._http_client:
            await self._http_client.aclose()

