"""External Quickwit logs adapter server."""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings
from app.core.logging import logger
from app.servers.base import BaseMCPServer


class QuickwitExternalMCPServer(BaseMCPServer):
    """Adapter that queries Quickwit logs indices directly."""

    def __init__(self):
        super().__init__(
            name="quickwit-server",
            version="0.1.0",
            description="Quickwit logs tools for service-level log retrieval",
        )
        self._http_client: Optional[httpx.AsyncClient] = None

    async def initialize(self) -> None:
        if not settings.QUICKWIT_ENABLED:
            logger.info("Quickwit adapter disabled by configuration")
            return

        self._http_client = httpx.AsyncClient(timeout=settings.QUICKWIT_TIMEOUT_SECONDS)

        self.register_tool(
            name="fetch_service_logs",
            description="Fetch logs for a service from Quickwit",
            handler=self._fetch_service_logs,
            input_schema={
                "type": "object",
                "properties": {
                    "service_name": {"type": "string"},
                    "env": {"type": "string", "enum": ["dev", "prod"], "default": "dev"},
                    "lookback_minutes": {"type": "number", "default": 60},
                },
                "required": ["service_name"],
            },
        )
        self.register_tool(
            name="fetch_service_error_logs",
            description="Fetch error-focused logs for a service from Quickwit",
            handler=self._fetch_service_error_logs,
            input_schema={
                "type": "object",
                "properties": {
                    "service_name": {"type": "string"},
                    "env": {"type": "string", "enum": ["dev", "prod"], "default": "dev"},
                    "lookback_minutes": {"type": "number", "default": 60},
                },
                "required": ["service_name"],
            },
        )

        logger.info("Quickwit adapter initialized")

    @staticmethod
    def _extract_product(service_name: str) -> str:
        """Extract product prefix from service name."""
        service = (service_name or "").strip()
        if not service:
            return "unknown"
        return service.split("-", 1)[0].lower()

    @staticmethod
    def _resolve_env(env: str) -> str:
        value = (env or "dev").strip().lower()
        return "prod" if value == "prod" else "dev"

    def _resolve_base_url(self, env: str) -> str:
        resolved_env = self._resolve_env(env)
        if resolved_env == "prod":
            return settings.QUICKWIT_PROD_URL.rstrip("/")
        return settings.QUICKWIT_DEV_URL.rstrip("/")

    async def _execute_search(
        self,
        service_name: str,
        env: str,
        lookback_minutes: float,
        query: str,
    ) -> Dict[str, Any]:
        if not self._http_client:
            return {"type": "text", "text": "Quickwit adapter client not initialized"}

        resolved_env = self._resolve_env(env)
        product = self._extract_product(service_name)
        index_pattern = f"{product}-consolelogs-{resolved_env}-*"
        base_url = self._resolve_base_url(resolved_env)
        endpoint = f"{base_url}/api/v1/{index_pattern}/search"

        try:
            lookback_sec = max(int(float(lookback_minutes) * 60), 60)
        except (TypeError, ValueError):
            lookback_sec = 3600

        end_timestamp = int(time.time())
        start_timestamp = end_timestamp - lookback_sec

        payload = {
            "query": query,
            "start_timestamp": start_timestamp,
            "end_timestamp": end_timestamp,
            "max_hits": settings.QUICKWIT_MAX_HITS,
            "sort_by": "-fluentbit_timestamp",
        }

        try:
            response = await self._http_client.post(
                endpoint,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
            return {
                "type": "text",
                "text": json.dumps(
                    {
                        "provider": "quickwit",
                        "service_name": service_name,
                        "env": resolved_env,
                        "index_pattern": index_pattern,
                        "query": payload["query"],
                        "start_timestamp": start_timestamp,
                        "end_timestamp": end_timestamp,
                        "result": data,
                    },
                    ensure_ascii=True,
                ),
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "type": "text",
                "text": f"Quickwit logs query failed for {service_name}: {exc}",
            }

    async def _fetch_service_logs(
        self,
        service_name: str,
        env: str = "dev",
        lookback_minutes: float = 60,
    ) -> Dict[str, Any]:
        query = f"kubernetes.container_name:{service_name}"
        return await self._execute_search(service_name, env, lookback_minutes, query)

    async def _fetch_service_error_logs(
        self,
        service_name: str,
        env: str = "dev",
        lookback_minutes: float = 60,
    ) -> Dict[str, Any]:
        query = (
            f"kubernetes.container_name:{service_name} AND "
            "(level:ERROR OR level:WARN OR message:ERROR OR message:Exception OR "
            "message:failed OR message:timeout OR message:Timeout)"
        )
        return await self._execute_search(service_name, env, lookback_minutes, query)

    async def cleanup(self) -> None:
        if self._http_client:
            await self._http_client.aclose()

