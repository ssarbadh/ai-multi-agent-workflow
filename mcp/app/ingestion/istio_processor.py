"""Istio processor - extracts service call graph from Istio MCP and VirtualService config.

Creates (Service)-[:CALLS {request_rate, latency}]->(Service|Database) relationships.

Uses in-process gateway calls when available (avoids HTTP 401/403 for viewer-only clients).
Falls back to HTTP with GRAPH_ENRICHMENT_MCP_API_KEY / API_KEYS for CLI use.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.core.logging import logger


class IstioProcessor:
    """Fetches Istio service dependencies and builds call graph for Neo4j enrichment."""

    @staticmethod
    def namespace_list_from_settings() -> List[str]:
        raw = (getattr(settings, "GRAPH_ENRICHMENT_ISTIO_NAMESPACE", None) or "default").strip()
        if not raw:
            return ["default"]
        return [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()] or ["default"]

    def __init__(
        self,
        mcp_base_url: Optional[str] = None,
        timeout: int = 120,
    ) -> None:
        self._mcp_url = (mcp_base_url or getattr(settings, "GRAPH_ENRICHMENT_MCP_URL", "") or "").rstrip("/")
        self._timeout = timeout
        self._client: Optional[httpx.Client] = None
        explicit_key = (getattr(settings, "GRAPH_ENRICHMENT_MCP_API_KEY", "") or "").strip()
        keys = getattr(settings, "API_KEYS", [])
        fallback = keys[0] if isinstance(keys, list) and keys else ""
        self._api_key = explicit_key or fallback

    def _ensure_client(self) -> Optional[httpx.Client]:
        if self._client is None:
            self._client = httpx.Client(timeout=self._timeout)
        return self._client

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

    def _call_mcp_tool_http(self, tool_name: str, arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Call MCP tool via HTTP (for scripts outside the running app)."""
        if not self._mcp_url:
            return None
        client = self._ensure_client()
        if not client:
            return None
        headers = {"Content-Type": "application/json"}
        api_key_header = getattr(settings, "API_KEY_HEADER", "X-API-Key")
        if self._api_key and api_key_header:
            headers[api_key_header] = self._api_key
        try:
            resp = client.post(
                f"{self._mcp_url}/api/v1/tools/call",
                json={"name": tool_name, "arguments": arguments},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data.get("content", [])
            if content and isinstance(content[0], dict):
                text = content[0].get("text", "")
                if text:
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        return {"virtual_services": [], "destination_rules": []}
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.warning("Istio MCP HTTP tool call failed", tool=tool_name, exc=str(exc))
            return None

    async def _call_mcp_tool_internal(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        from app.ingestion.internal_mcp_tools import call_tool_for_enrichment

        return await call_tool_for_enrichment(tool_name, arguments)

    def _edges_from_routes(
        self,
        hosts: List[Any],
        route_blocks: List[Dict[str, Any]],
        seen: set,
        calls: List[Dict[str, Any]],
    ) -> None:
        for route in route_blocks:
            route_dests = route.get("route", [])
            if not isinstance(route_dests, list):
                route_dests = [route_dests] if route_dests else []
            for d in route_dests:
                if not isinstance(d, dict):
                    continue
                dest = d.get("destination") if isinstance(d.get("destination"), dict) else {}
                host = dest.get("host") or d.get("host")
                if not host:
                    continue
                host_str = str(host).split(".")[0]
                for src_host in hosts:
                    src_str = str(src_host).split(".")[0]
                    key = (src_str, host_str)
                    if key not in seen:
                        seen.add(key)
                        calls.append({
                            "caller": src_str,
                            "callee": host_str,
                            "request_rate": None,
                            "latency_ms": None,
                        })

    def _extract_calls_from_virtual_services(self, vs_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract caller -> callee from VirtualService http and tcp routes."""
        calls: List[Dict[str, Any]] = []
        seen: set = set()
        for vs in vs_list or []:
            hosts = vs.get("hosts", [])
            self._edges_from_routes(hosts, vs.get("http", []) or [], seen, calls)
            self._edges_from_routes(hosts, vs.get("tcp", []) or [], seen, calls)
            self._edges_from_routes(hosts, vs.get("tls", []) or [], seen, calls)
        return calls

    async def fetch_service_call_graph_async(
        self,
        service_name: str,
        namespaces: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Query istio_get_istio_resources_for_service across namespaces (Neo4j names lack namespace)."""
        ns_list = namespaces or self.namespace_list_from_settings()
        all_edges: List[Dict[str, Any]] = []
        seen: set = set()
        for ns in ns_list:
            data = await self._call_mcp_tool_internal(
                "istio_get_istio_resources_for_service",
                {"service_name": service_name, "namespace": ns},
            )
            if not data:
                continue
            if data.get("error"):
                logger.warning(
                    "Istio per-service call failed",
                    service=service_name,
                    namespace=ns,
                    error=str(data.get("error"))[:400],
                )
                continue
            vs_list = data.get("virtual_services", [])
            for c in self._extract_calls_from_virtual_services(vs_list):
                key = (c.get("caller"), c.get("callee"))
                if key not in seen:
                    seen.add(key)
                    all_edges.append(c)
        return all_edges

    async def fetch_namespace_call_graph_async(self, namespace_config: str) -> List[Dict[str, Any]]:
        """All CALLS edges from VirtualServices (multi-namespace string or cluster-wide)."""
        cluster_wide = bool(getattr(settings, "GRAPH_ENRICHMENT_ISTIO_CLUSTER_WIDE", False))
        data = await self._call_mcp_tool_internal(
            "istio_list_virtual_services_in_namespace",
            {
                "namespace": namespace_config or "default",
                "max_items": 800,
                "list_scope": "cluster" if cluster_wide else "namespaced",
            },
        )
        if not data:
            return []
        if data.get("error"):
            logger.error(
                "Istio VirtualService list failed (check kube credentials in MCP container)",
                error=str(data.get("error"))[:600],
                namespaces=namespace_config,
                cluster_wide=cluster_wide,
            )
            return []
        vs_list = data.get("virtual_services", [])
        calls = self._extract_calls_from_virtual_services(vs_list)
        if calls:
            logger.info(
                "Istio namespace scan extracted call edges",
                namespace=namespace_config,
                cluster_wide=cluster_wide,
                virtual_service_count=len(vs_list),
                edge_count=len(calls),
            )
        else:
            logger.warning(
                "Istio scan returned no routable http edges",
                namespace=namespace_config,
                cluster_wide=cluster_wide,
                virtual_service_count=len(vs_list),
            )
        return calls

    def fetch_service_call_graph_http(
        self,
        service_name: str,
        namespace: str = "default",
    ) -> List[Dict[str, Any]]:
        """HTTP-only: per-service VirtualService filter (may be empty if hosts do not match)."""
        data = self._call_mcp_tool_http("istio_get_istio_resources_for_service", {
            "service_name": service_name,
            "namespace": namespace,
        })
        if not data:
            return []
        vs_list = data.get("virtual_services", [])
        return self._extract_calls_from_virtual_services(vs_list)

    def fetch_mesh_hosts(self, namespace: str = "default") -> List[Dict[str, Any]]:
        """Fetch all service mesh hosts in namespace (HTTP)."""
        data = self._call_mcp_tool_http("istio_get_service_mesh_hosts", {"namespace": namespace})
        if not data:
            return []
        return data.get("hosts", [])

    def get_call_graph_simulated(self, service_name: str) -> List[Dict[str, Any]]:
        """Simulate Istio call graph for testing."""
        templates: Dict[str, List[Dict[str, Any]]] = {
            "ems-api-gateway": [
                {"caller": "ems-api-gateway", "callee": "ems-user-svc", "request_rate": 150.0, "latency_ms": 45.0},
                {"caller": "ems-api-gateway", "callee": "ems-orchestration-svc", "request_rate": 80.0, "latency_ms": 120.0},
            ],
            "ems-user-svc": [
                {"caller": "ems-user-svc", "callee": "ems-mongodb", "request_rate": 200.0, "latency_ms": 12.0},
            ],
            "ems-orchestration-svc": [
                {"caller": "ems-orchestration-svc", "callee": "ems-input-core-svc", "request_rate": 50.0, "latency_ms": 80.0},
            ],
        }
        return templates.get(service_name, [
            {"caller": service_name, "callee": f"{service_name}-db", "request_rate": 100.0, "latency_ms": 25.0},
        ])

    async def process_services_async(
        self,
        services: List[str],
        namespace: str,
        use_simulated: bool = False,
        use_internal_gateway: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Build combined call graph. When not simulated, prefers one namespace-wide VS list
        (matches Neo4j service names against graph endpoints later in Neo4j writer).
        """
        if use_simulated:
            all_calls: List[Dict[str, Any]] = []
            seen: set = set()
            for svc in services:
                for c in self.get_call_graph_simulated(svc):
                    key = (c.get("caller"), c.get("callee"))
                    if key not in seen:
                        seen.add(key)
                        all_calls.append(c)
            return all_calls

        if use_internal_gateway:
            calls = await self.fetch_namespace_call_graph_async(namespace)
            if calls:
                return calls
            logger.warning(
                "Namespace Istio scan empty; falling back to per-service internal tool calls",
                namespace=namespace,
            )
            all_calls = []
            seen = set()
            ns_for_fallback = self.namespace_list_from_settings()
            for svc in services:
                for c in await self.fetch_service_call_graph_async(svc, ns_for_fallback):
                    key = (c.get("caller"), c.get("callee"))
                    if key not in seen:
                        seen.add(key)
                        all_calls.append(c)
            return all_calls

        all_calls = []
        seen = set()
        for svc in services:
            calls = self.fetch_service_call_graph_http(svc, namespace)
            for c in calls:
                key = (c.get("caller"), c.get("callee"))
                if key not in seen:
                    seen.add(key)
                    all_calls.append(c)
        return all_calls

    def process_services(
        self,
        services: List[str],
        namespace: str = "default",
        use_simulated: bool = False,
        use_internal_gateway: bool = False,
    ) -> List[Dict[str, Any]]:
        """Sync entry for CLI: simulated is pure sync; internal gateway uses asyncio.run."""
        if use_simulated:
            all_calls: List[Dict[str, Any]] = []
            seen: set = set()
            for svc in services:
                for c in self.get_call_graph_simulated(svc):
                    key = (c.get("caller"), c.get("callee"))
                    if key not in seen:
                        seen.add(key)
                        all_calls.append(c)
            return all_calls
        if use_internal_gateway:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(
                    self.process_services_async(services, namespace, False, True)
                )
            raise RuntimeError(
                "process_services(..., use_internal_gateway=True) from async context: "
                "await process_services_async(...) instead"
            )
        all_calls = []
        seen = set()
        for svc in services:
            calls = self.fetch_service_call_graph_http(svc, namespace)
            for c in calls:
                key = (c.get("caller"), c.get("callee"))
                if key not in seen:
                    seen.add(key)
                    all_calls.append(c)
        return all_calls
