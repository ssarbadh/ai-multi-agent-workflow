"""Graph MCP server - Neo4j dependency and incident queries.

Integrates with Cartography (infrastructure graph) and AegisOps context graph.
Exposes tools for dependency discovery and root cause analysis.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logging import logger
from app.repositories.graph_repository import GraphRepository
from app.servers.base import BaseMCPServer


class GraphExternalMCPServer(BaseMCPServer):
    """MCP server for Neo4j graph queries (Cartography + context graph)."""

    def __init__(self) -> None:
        super().__init__(
            name="graph-server",
            version="0.1.0",
            description="Neo4j graph tools for service dependencies, incident root cause, and dependency tracing",
        )
        self._repo: Optional[GraphRepository] = None

    async def initialize(self) -> None:
        if not settings.GRAPH_MCP_ENABLED:
            logger.info("Graph MCP adapter disabled by configuration")
            return

        if not settings.GRAPH_MCP_NEO4J_URI:
            logger.warning("Graph MCP: NEO4J_URI not configured")
            return

        try:
            from neo4j import GraphDatabase

            driver = GraphDatabase.driver(
                settings.GRAPH_MCP_NEO4J_URI,
                auth=(
                    settings.GRAPH_MCP_NEO4J_USER,
                    settings.GRAPH_MCP_NEO4J_PASSWORD,
                ),
            )
            driver.verify_connectivity()
            self._repo = GraphRepository(
                driver,
                database=settings.GRAPH_MCP_NEO4J_DATABASE,
            )

            self.register_tool(
                name="graph_get_service_dependencies",
                description="Get pods and services that a Kubernetes service depends on or targets. Use for RCA to understand what a failing service connects to.",
                handler=self._get_service_dependencies,
                input_schema={
                    "type": "object",
                    "properties": {
                        "service_name": {"type": "string", "description": "Service name (e.g. checkout, payment)"},
                        "namespace": {"type": "string", "description": "Kubernetes namespace (optional)"},
                        "limit": {"type": "integer", "default": 20},
                    },
                    "required": ["service_name"],
                },
            )
            self.register_tool(
                name="graph_get_upstream_services",
                description="Find services that depend on or route to the given service. Use when tracing impact of an upstream failure.",
                handler=self._get_upstream_services,
                input_schema={
                    "type": "object",
                    "properties": {
                        "service_name": {"type": "string"},
                        "namespace": {"type": "string"},
                        "limit": {"type": "integer", "default": 20},
                    },
                    "required": ["service_name"],
                },
            )
            self.register_tool(
                name="graph_trace_dependency_path",
                description="Trace dependency path downstream or upstream from a service. Use for understanding blast radius or root cause chain.",
                handler=self._trace_dependency_path,
                input_schema={
                    "type": "object",
                    "properties": {
                        "service_name": {"type": "string"},
                        "direction": {"type": "string", "enum": ["downstream", "upstream"], "default": "downstream"},
                        "max_depth": {"type": "integer", "default": 3},
                    },
                    "required": ["service_name"],
                },
            )
            self.register_tool(
                name="graph_get_recent_anomalies",
                description="Get recent anomalies (latency/error spikes) for a service. Use for RCA correlation.",
                handler=self._get_recent_anomalies,
                input_schema={
                    "type": "object",
                    "properties": {
                        "service_name": {"type": "string"},
                        "namespace": {"type": "string"},
                        "limit": {"type": "integer", "default": 20},
                    },
                    "required": ["service_name"],
                },
            )
            self.register_tool(
                name="graph_get_impacted_services",
                description="Get services impacted when a service fails (downstream) or services it depends on (upstream).",
                handler=self._get_impacted_services,
                input_schema={
                    "type": "object",
                    "properties": {
                        "service_name": {"type": "string"},
                        "direction": {"type": "string", "enum": ["downstream", "upstream"], "default": "downstream"},
                        "limit": {"type": "integer", "default": 20},
                    },
                    "required": ["service_name"],
                },
            )
            self.register_tool(
                name="graph_get_incident_root_cause",
                description="Get root cause and remediation for an incident from the context graph.",
                handler=self._get_incident_root_cause,
                input_schema={
                    "type": "object",
                    "properties": {
                        "incident_id": {"type": "string", "description": "Incident ID (e.g. inc_xxx)"},
                    },
                    "required": ["incident_id"],
                },
            )
            self.register_tool(
                name="graph_get_recent_incidents",
                description="Get recent incidents affecting a service. Use for pattern recognition in RCA.",
                handler=self._get_recent_incidents,
                input_schema={
                    "type": "object",
                    "properties": {
                        "service_name": {"type": "string"},
                        "limit": {"type": "integer", "default": 10},
                    },
                    "required": ["service_name"],
                },
            )
            self.register_tool(
                name="graph_list_services",
                description="List services in the graph (from Cartography or context graph).",
                handler=self._list_services,
                input_schema={
                    "type": "object",
                    "properties": {
                        "namespace": {"type": "string"},
                        "limit": {"type": "integer", "default": 50},
                    },
                },
            )
            self.register_tool(
                name="graph_resolve_kubernetes_service",
                description=(
                    "Resolve a Kubernetes workload/service name to the canonical graph name and namespace "
                    "(case-insensitive; uses Neo4j Cartography nodes). Prefer this over graph_list_services "
                    "when inferring namespace for kubectl-style tools."
                ),
                handler=self._resolve_kubernetes_service,
                input_schema={
                    "type": "object",
                    "properties": {
                        "service_name": {
                            "type": "string",
                            "description": "Service or deployment name hint (e.g. hotels-events-publisher)",
                        },
                    },
                    "required": ["service_name"],
                },
            )
            self.register_tool(
                name="graph_find_resource_by_endpoint",
                description=(
                    "Find infrastructure resources (LB/RDS/ElastiCache/S3/ExternalService) by "
                    "endpoint, DNS name, or identifier. Use to validate dependency endpoint existence."
                ),
                handler=self._find_resource_by_endpoint,
                input_schema={
                    "type": "object",
                    "properties": {
                        "endpoint": {
                            "type": "string",
                            "description": "Dependency endpoint/hostname/id hint",
                        },
                        "limit": {"type": "integer", "default": 10},
                    },
                    "required": ["endpoint"],
                },
            )

            logger.info("Graph MCP adapter initialized", neo4j_uri=settings.GRAPH_MCP_NEO4J_URI)
        except ImportError as exc:
            logger.warning("Graph adapter: neo4j package not installed", exc=str(exc))
        except Exception as exc:
            logger.warning("Graph adapter: could not connect to Neo4j", exc=str(exc))

    def _ensure_repo(self) -> Optional[GraphRepository]:
        if not self._repo:
            return None
        return self._repo

    @staticmethod
    def _tool_text(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"type": "text", "text": json.dumps(payload, default=str, ensure_ascii=True)}

    async def _get_service_dependencies(
        self,
        service_name: str,
        namespace: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        repo = self._ensure_repo()
        if not repo:
            return self._tool_text({"error": "Graph adapter not initialized"})
        rows = repo.get_service_dependencies(service_name, namespace, limit)
        return self._tool_text({
            "provider": "graph",
            "service_name": service_name,
            "namespace": namespace,
            # Cartography rows: service_name, namespace, pods[], dependencies[] (related services)
            "dependencies": rows,
            "cartography_rows": rows,
        })

    async def _get_upstream_services(
        self,
        service_name: str,
        namespace: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        repo = self._ensure_repo()
        if not repo:
            return self._tool_text({"error": "Graph adapter not initialized"})
        rows = repo.get_upstream_services(service_name, namespace, limit)
        return self._tool_text({
            "provider": "graph",
            "service_name": service_name,
            "upstream_services": rows,
        })

    async def _trace_dependency_path(
        self,
        service_name: str,
        direction: str = "downstream",
        max_depth: int = 3,
    ) -> Dict[str, Any]:
        repo = self._ensure_repo()
        if not repo:
            return self._tool_text({"error": "Graph adapter not initialized"})
        rows = repo.trace_dependency_path(service_name, direction, max_depth)
        return self._tool_text({
            "provider": "graph",
            "service_name": service_name,
            "direction": direction,
            "path": rows,
        })

    async def _get_recent_anomalies(
        self,
        service_name: str,
        namespace: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        repo = self._ensure_repo()
        if not repo:
            return self._tool_text({"error": "Graph adapter not initialized"})
        rows = repo.get_recent_anomalies(service_name, namespace, limit)
        return self._tool_text({
            "provider": "graph",
            "service_name": service_name,
            "anomalies": rows,
        })

    async def _get_impacted_services(
        self,
        service_name: str,
        direction: str = "downstream",
        limit: int = 20,
    ) -> Dict[str, Any]:
        repo = self._ensure_repo()
        if not repo:
            return self._tool_text({"error": "Graph adapter not initialized"})
        rows = repo.get_impacted_services(service_name, direction, limit)
        return self._tool_text({
            "provider": "graph",
            "service_name": service_name,
            "direction": direction,
            "impacted_services": rows,
        })

    async def _get_incident_root_cause(self, incident_id: str) -> Dict[str, Any]:
        repo = self._ensure_repo()
        if not repo:
            return self._tool_text({"error": "Graph adapter not initialized"})
        rows = repo.get_incident_root_cause(incident_id)
        extended = repo.get_incident_root_cause_extended(incident_id)
        out: Dict[str, Any] = {"provider": "graph", "incident_id": incident_id, "root_cause": rows}
        if extended:
            ex = extended[0]
            out["impacted_services"] = ex.get("impacted_services") or []
            out["anomalies"] = [a for a in (ex.get("anomalies") or []) if a]
            out["error_patterns"] = [e for e in (ex.get("error_patterns") or []) if e]
        return self._tool_text(out)

    async def _get_recent_incidents(
        self,
        service_name: str,
        limit: int = 10,
    ) -> Dict[str, Any]:
        repo = self._ensure_repo()
        if not repo:
            return self._tool_text({"error": "Graph adapter not initialized"})
        rows = repo.get_recent_incidents(service_name, limit)
        return self._tool_text({
            "provider": "graph",
            "service_name": service_name,
            "incidents": rows,
        })

    async def _list_services(
        self,
        namespace: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        repo = self._ensure_repo()
        if not repo:
            return self._tool_text({"error": "Graph adapter not initialized"})
        rows = repo.list_services(namespace, limit)
        return self._tool_text({
            "provider": "graph",
            "namespace": namespace,
            "services": rows,
        })

    async def _resolve_kubernetes_service(self, service_name: str) -> Dict[str, Any]:
        repo = self._ensure_repo()
        if not repo:
            return self._tool_text({"error": "Graph adapter not initialized"})
        resolved = repo.resolve_kubernetes_service(service_name)
        return self._tool_text({
            "provider": "graph",
            "service_name": service_name,
            "resolved": resolved,
        })

    async def _find_resource_by_endpoint(self, endpoint: str, limit: int = 10) -> Dict[str, Any]:
        repo = self._ensure_repo()
        if not repo:
            return self._tool_text({"error": "Graph adapter not initialized"})
        matches = repo.find_resource_by_endpoint(endpoint, limit)
        return self._tool_text({
            "provider": "graph",
            "endpoint": endpoint,
            "matches": matches,
        })

    async def cleanup(self) -> None:
        self._repo = None
