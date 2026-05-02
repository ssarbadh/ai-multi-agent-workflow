"""MCP Server Registry - manages server lifecycle and discovery."""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logging import logger
from app.core.redis_client import redis_client
from app.models.schemas import (
    RegisteredServer,
    ServerHealthCheck,
    ServerStatus,
    ToolDefinition,
    ResourceDefinition,
    PromptDefinition,
)
from app.servers.base import BaseMCPServer
from app.servers.infra_server import InfrastructureMCPServer
from app.servers.rag_server import RAGMCPServer
from app.servers.context_server import ContextMCPServer
from app.servers.prometheus_external_server import PrometheusExternalMCPServer
from app.servers.newrelic_external_server import NewRelicExternalMCPServer
from app.servers.alertmanager_external_server import AlertmanagerExternalMCPServer
from app.servers.quickwit_external_server import QuickwitExternalMCPServer
from app.servers.elasticsearch_external_server import ElasticsearchExternalMCPServer
from app.servers.istio_external_server import IstioExternalMCPServer
from app.servers.kubernetes_external_server import KubernetesExternalMCPServer
from app.servers.aws_external_server import AWSExternalMCPServer
from app.servers.graph_external_server import GraphExternalMCPServer
from app.servers.servicenow_external_server import ServiceNowExternalMCPServer


class ServerRegistry:
    """Registry for MCP servers."""

    def __init__(self):
        self._servers: Dict[str, BaseMCPServer] = {}
        self._registered: Dict[str, RegisteredServer] = {}
        self._health_check_task: Optional[asyncio.Task] = None

    async def initialize(self) -> None:
        """Initialize the registry and built-in servers."""
        # Initialize built-in servers
        infra_server = InfrastructureMCPServer()
        await infra_server.initialize()
        await self.register_server(infra_server)

        rag_server = RAGMCPServer()
        await rag_server.initialize()
        await self.register_server(rag_server)

        context_server = ContextMCPServer()
        await context_server.initialize()
        await self.register_server(context_server)

        if settings.PROMETHEUS_MCP_ENABLED:
            prometheus_server = PrometheusExternalMCPServer()
            await prometheus_server.initialize()
            await self.register_server(prometheus_server)

        if settings.NEWRELIC_MCP_ENABLED:
            newrelic_server = NewRelicExternalMCPServer()
            await newrelic_server.initialize()
            await self.register_server(newrelic_server)

        if settings.ALERTMANAGER_MCP_ENABLED:
            alertmanager_server = AlertmanagerExternalMCPServer()
            await alertmanager_server.initialize()
            await self.register_server(alertmanager_server)

        if settings.QUICKWIT_ENABLED:
            quickwit_server = QuickwitExternalMCPServer()
            await quickwit_server.initialize()
            await self.register_server(quickwit_server)

        if settings.ELASTICSEARCH_MCP_ENABLED:
            elasticsearch_server = ElasticsearchExternalMCPServer()
            await elasticsearch_server.initialize()
            await self.register_server(elasticsearch_server)

        if settings.ISTIO_MCP_ENABLED:
            try:
                istio_server = IstioExternalMCPServer()
                await istio_server.initialize()
                if istio_server.list_tools():
                    await self.register_server(istio_server)
            except Exception as exc:
                logger.warning("Istio MCP adapter skipped", exc=str(exc))

        if settings.KUBERNETES_MCP_ENABLED:
            try:
                kubernetes_server = KubernetesExternalMCPServer()
                await kubernetes_server.initialize()
                if kubernetes_server.list_tools():
                    await self.register_server(kubernetes_server)
            except Exception as exc:
                logger.warning("Kubernetes MCP adapter skipped", exc=str(exc))

        if settings.AWS_MCP_ENABLED:
            try:
                aws_server = AWSExternalMCPServer()
                await aws_server.initialize()
                if aws_server.list_tools():
                    await self.register_server(aws_server)
            except Exception as exc:
                logger.warning("AWS MCP adapter skipped", exc=str(exc))

        if settings.GRAPH_MCP_ENABLED:
            try:
                graph_server = GraphExternalMCPServer()
                await graph_server.initialize()
                if graph_server.list_tools():
                    await self.register_server(graph_server)
            except Exception as exc:
                logger.warning("Graph MCP adapter skipped", exc=str(exc))

        if settings.SERVICENOW_MCP_ENABLED:
            servicenow_server = ServiceNowExternalMCPServer()
            await servicenow_server.initialize()
            await self.register_server(servicenow_server)

        # Start health check loop
        self._health_check_task = asyncio.create_task(self._health_check_loop())

        logger.info(f"Server registry initialized with {len(self._servers)} servers")

    async def shutdown(self) -> None:
        """Shutdown the registry."""
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass

        for server in self._servers.values():
            if hasattr(server, "cleanup"):
                await server.cleanup()

        self._servers.clear()
        self._registered.clear()
        logger.info("Server registry shutdown")

    async def register_server(self, server: BaseMCPServer) -> RegisteredServer:
        """Register an MCP server."""
        server_id = server.name
        self._servers[server_id] = server

        registered = RegisteredServer(
            server_id=server_id,
            name=server.name,
            description=server.description,
            transport=settings.MCP_TRANSPORT,
            status=ServerStatus.RUNNING,
            tools=server.list_tools(),
            resources=server.list_resources(),
            prompts=server.list_prompts(),
            registered_at=datetime.now(timezone.utc),
        )
        self._registered[server_id] = registered

        # Cache in Redis
        await redis_client.set_json(
            f"mcp:server:{server_id}",
            registered.model_dump(mode="json"),
            ttl=settings.MCP_SESSION_TTL,
        )

        logger.info(f"Registered server: {server_id}", tools=len(registered.tools))
        return registered

    def get_server(self, server_id: str) -> Optional[BaseMCPServer]:
        """Get a server by ID."""
        return self._servers.get(server_id)

    def get_registered(self, server_id: str) -> Optional[RegisteredServer]:
        """Get registered server info."""
        return self._registered.get(server_id)

    def list_servers(self) -> List[RegisteredServer]:
        """List all registered servers."""
        return list(self._registered.values())

    def list_all_tools(self) -> List[ToolDefinition]:
        """List all tools from all servers."""
        tools = []
        for server in self._servers.values():
            tools.extend(server.list_tools())
        return tools

    def list_all_resources(self) -> List[ResourceDefinition]:
        """List all resources from all servers."""
        resources = []
        for server in self._servers.values():
            resources.extend(server.list_resources())
        return resources

    def list_all_prompts(self) -> List[PromptDefinition]:
        """List all prompts from all servers."""
        prompts = []
        for server in self._servers.values():
            prompts.extend(server.list_prompts())
        return prompts

    def find_tool(self, tool_name: str) -> Optional[tuple[str, BaseMCPServer]]:
        """Find which server has a tool."""
        for server_id, server in self._servers.items():
            for tool in server.list_tools():
                if tool.name == tool_name:
                    return server_id, server
        return None

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Call a tool by name."""
        result = self.find_tool(tool_name)
        if not result:
            return {"error": f"Tool not found: {tool_name}"}

        server_id, server = result
        response = await server.call_tool(tool_name, arguments, user_id)
        return response.model_dump()

    async def _health_check_loop(self) -> None:
        """Periodic health check for all servers."""
        while True:
            try:
                await asyncio.sleep(settings.MCP_HEALTH_CHECK_INTERVAL)
                for server_id, registered in self._registered.items():
                    # Simple health check - server is healthy if it's in memory
                    if server_id in self._servers:
                        registered.status = ServerStatus.RUNNING
                        registered.last_health_check = datetime.now(timezone.utc)
                    else:
                        registered.status = ServerStatus.ERROR
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check error: {e}")


# Global instance
server_registry = ServerRegistry()
