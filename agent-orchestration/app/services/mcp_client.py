"""Client for MCP (Model Context Protocol) service integration.

Connects Agent Orchestration to MCP servers for tool execution per HLD:
- Infrastructure tools (VMware, AWS, K8s)
- RAG tools (search, ask, reindex)
- Context tools
"""

import logging
from typing import Dict, Any, Optional, List, Tuple
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class MCPClient:
    """
    Client for MCP Gateway service.
    
    Integrates with MCP for:
    - Tool discovery and execution
    - Infrastructure operations via infra-server
    - RAG operations via rag-server
    - Context operations via context-server
    """
    
    def __init__(self):
        self.base_url = getattr(settings, 'MCP_SERVICE_URL', 'http://localhost:8005')
        self.timeout = getattr(settings, 'MCP_SERVICE_TIMEOUT', 60)
        self._tools_cache: Dict[str, Any] = {"items": [], "loaded": False}
        self.api_key = getattr(settings, "MCP_API_KEY", "")
        self.api_key_header = getattr(settings, "MCP_API_KEY_HEADER", "X-API-Key")

    def _headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if self.api_key:
            headers[self.api_key_header] = self.api_key
        return headers
    
    async def list_servers(self) -> List[Dict[str, Any]]:
        """List available MCP servers."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/servers",
                    headers=self._headers(),
                )
                response.raise_for_status()
                data = response.json()
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    return data.get("servers", [])
                return []
        except Exception as e:
            logger.error(f"Failed to list MCP servers: {e}")
            return []
    
    async def list_tools(self, server_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List available tools from MCP servers.
        
        Args:
            server_name: Optional server name to filter tools
            
        Returns:
            List of available tools with schemas
        """
        try:
            params = {}
            if server_name:
                params["server_id"] = server_name
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/tools",
                    params=params,
                    headers=self._headers(),
                )
                response.raise_for_status()
                data = response.json()
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    return data.get("tools", [])
                return []
        except Exception as e:
            logger.error(f"Failed to list MCP tools: {e}")
            return []
    
    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        server_name: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Call an MCP tool.
        
        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments
            server_name: Optional server name
            session_id: Optional session ID for context
            
        Returns:
            Tool execution result
        """
        try:
            payload = {
                "name": tool_name,
                "arguments": arguments
            }
            params = {}
            if session_id:
                params["session_id"] = session_id
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/tools/call",
                    json=payload,
                    params=params,
                    headers=self._headers(),
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to call MCP tool {tool_name}: {e}")
            return {"error": str(e), "success": False}

    async def get_tools_inventory(self, refresh: bool = False) -> List[Dict[str, Any]]:
        """Get cached MCP tool inventory for routing decisions."""
        if not refresh and self._tools_cache["loaded"]:
            return self._tools_cache["items"]

        tools = await self.list_tools()
        self._tools_cache = {"items": tools, "loaded": True}
        return tools

    @staticmethod
    def _extract_tool_identity(tool: Dict[str, Any]) -> Tuple[str, str]:
        """Extract (server, name) identity from varying MCP tool payloads."""
        server = (
            tool.get("server")
            or tool.get("server_name")
            or tool.get("serverId")
            or tool.get("server_id")
            or ""
        )
        name = (
            tool.get("name")
            or tool.get("tool")
            or tool.get("tool_name")
            or ""
        )
        return str(server), str(name)

    async def is_tool_available(
        self,
        server_name: str,
        tool_name: str,
        inventory: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """Check if a specific tool contract is currently available."""
        tools = inventory if inventory is not None else await self.get_tools_inventory()
        for tool in tools:
            server, name = self._extract_tool_identity(tool)
            if server == server_name and name == tool_name:
                return True
        return False

    async def call_first_available_contract(
        self,
        contracts: List[Dict[str, Any]],
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute the first available MCP tool contract from ordered candidates.

        Contract shape:
        {
          "provider": "prometheus|elasticsearch|newrelic|servicenow",
          "server": "observability-server",
          "tool": "prometheus_query_range",
          "arguments": {...}
        }
        """
        inventory = await self.get_tools_inventory()
        attempted: List[Dict[str, Any]] = []

        for contract in contracts:
            provider = contract.get("provider", "unknown")
            server = contract.get("server", "")
            tool = contract.get("tool", "")
            arguments = contract.get("arguments", {})

            if not server or not tool:
                attempted.append(
                    {"provider": provider, "server": server, "tool": tool, "status": "invalid_contract"}
                )
                continue

            available = await self.is_tool_available(server, tool, inventory=inventory)
            if not available:
                attempted.append(
                    {"provider": provider, "server": server, "tool": tool, "status": "not_available"}
                )
                continue

            response = await self.call_tool(
                tool_name=tool,
                arguments=arguments,
                server_name=server,
                session_id=session_id,
            )
            if response.get("error") or response.get("success") is False:
                attempted.append(
                    {
                        "provider": provider,
                        "server": server,
                        "tool": tool,
                        "status": "failed",
                        "error": response.get("error"),
                    }
                )
                continue

            return {
                "status": "success",
                "provider": provider,
                "server": server,
                "tool": tool,
                "response": response,
                "attempted": attempted,
            }

        return {
            "status": "failed",
            "error": "no_available_contract_succeeded",
            "attempted": attempted,
        }
    
    # =========================================================================
    # Infrastructure Tools (via infra-server)
    # =========================================================================
    
    async def vmware_list_vms(
        self,
        datacenter: Optional[str] = None,
        folder: Optional[str] = None
    ) -> Dict[str, Any]:
        """List VMware VMs via MCP infra-server."""
        return await self.call_tool(
            tool_name="vmware_list_vms",
            arguments={"datacenter": datacenter, "folder": folder},
            server_name="infra-server"
        )
    
    async def vmware_vm_power(
        self,
        vm_name: str,
        action: str
    ) -> Dict[str, Any]:
        """Control VMware VM power state."""
        return await self.call_tool(
            tool_name="vmware_vm_power",
            arguments={"vm_name": vm_name, "action": action},
            server_name="infra-server"
        )
    
    async def aws_list_ec2(
        self,
        region: Optional[str] = None
    ) -> Dict[str, Any]:
        """List AWS EC2 instances via MCP."""
        return await self.call_tool(
            tool_name="aws_list_ec2",
            arguments={"region": region},
            server_name="infra-server"
        )
    
    async def aws_ec2_action(
        self,
        instance_id: str,
        action: str,
        region: Optional[str] = None
    ) -> Dict[str, Any]:
        """Control AWS EC2 instance via MCP."""
        return await self.call_tool(
            tool_name="aws_ec2_action",
            arguments={
                "instance_id": instance_id,
                "action": action,
                "region": region
            },
            server_name="infra-server"
        )
    
    async def k8s_list_pods(
        self,
        namespace: Optional[str] = None,
        label_selector: Optional[str] = None
    ) -> Dict[str, Any]:
        """List Kubernetes pods via MCP."""
        return await self.call_tool(
            tool_name="k8s_list_pods",
            arguments={
                "namespace": namespace,
                "label_selector": label_selector
            },
            server_name="infra-server"
        )
    
    async def k8s_scale_deployment(
        self,
        namespace: str,
        deployment: str,
        replicas: int
    ) -> Dict[str, Any]:
        """Scale Kubernetes deployment via MCP."""
        return await self.call_tool(
            tool_name="k8s_scale_deployment",
            arguments={
                "namespace": namespace,
                "deployment": deployment,
                "replicas": replicas
            },
            server_name="infra-server"
        )
    
    # =========================================================================
    # AWS Extended Services (via infra-server) - Replaces Azure per HLD
    # =========================================================================
    
    async def aws_list_eks_clusters(self, region: Optional[str] = None) -> Dict[str, Any]:
        """List EKS clusters via MCP."""
        return await self.call_tool(
            tool_name="aws_list_eks_clusters",
            arguments={"region": region},
            server_name="infra-server"
        )
    
    async def aws_describe_eks_cluster(
        self,
        cluster_name: str,
        region: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get EKS cluster details via MCP."""
        return await self.call_tool(
            tool_name="aws_describe_eks_cluster",
            arguments={"cluster_name": cluster_name, "region": region},
            server_name="infra-server"
        )
    
    async def aws_list_lambda_functions(self, region: Optional[str] = None) -> Dict[str, Any]:
        """List Lambda functions via MCP."""
        return await self.call_tool(
            tool_name="aws_list_lambda_functions",
            arguments={"region": region},
            server_name="infra-server"
        )
    
    async def aws_invoke_lambda(
        self,
        function_name: str,
        payload: Dict[str, Any],
        region: Optional[str] = None
    ) -> Dict[str, Any]:
        """Invoke Lambda function via MCP."""
        return await self.call_tool(
            tool_name="aws_invoke_lambda",
            arguments={
                "function_name": function_name,
                "payload": payload,
                "region": region
            },
            server_name="infra-server"
        )
    
    async def aws_list_rds_instances(self, region: Optional[str] = None) -> Dict[str, Any]:
        """List RDS instances via MCP."""
        return await self.call_tool(
            tool_name="aws_list_rds_instances",
            arguments={"region": region},
            server_name="infra-server"
        )
    
    async def aws_list_load_balancers(self, region: Optional[str] = None) -> Dict[str, Any]:
        """List load balancers via MCP."""
        return await self.call_tool(
            tool_name="aws_list_load_balancers",
            arguments={"region": region},
            server_name="infra-server"
        )
    
    async def aws_list_auto_scaling_groups(self, region: Optional[str] = None) -> Dict[str, Any]:
        """List Auto Scaling groups via MCP."""
        return await self.call_tool(
            tool_name="aws_list_auto_scaling_groups",
            arguments={"region": region},
            server_name="infra-server"
        )
    
    async def aws_set_asg_capacity(
        self,
        asg_name: str,
        desired_capacity: int,
        region: Optional[str] = None
    ) -> Dict[str, Any]:
        """Set Auto Scaling group capacity via MCP."""
        return await self.call_tool(
            tool_name="aws_set_asg_capacity",
            arguments={
                "asg_name": asg_name,
                "desired_capacity": desired_capacity,
                "region": region
            },
            server_name="infra-server"
        )
    
    async def aws_send_ssm_command(
        self,
        instance_ids: List[str],
        commands: List[str],
        region: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send SSM command to EC2 instances via MCP."""
        return await self.call_tool(
            tool_name="aws_send_ssm_command",
            arguments={
                "instance_ids": instance_ids,
                "commands": commands,
                "region": region
            },
            server_name="infra-server"
        )
    
    async def aws_send_email(
        self,
        source: str,
        to_addresses: List[str],
        subject: str,
        body: str,
        region: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send email via AWS SES through MCP."""
        return await self.call_tool(
            tool_name="aws_send_email",
            arguments={
                "source": source,
                "to_addresses": to_addresses,
                "subject": subject,
                "body": body,
                "region": region
            },
            server_name="infra-server"
        )
    
    async def aws_list_hosted_zones(self) -> Dict[str, Any]:
        """List Route53 hosted zones via MCP."""
        return await self.call_tool(
            tool_name="aws_list_hosted_zones",
            arguments={},
            server_name="infra-server"
        )
    
    async def aws_create_dns_record(
        self,
        hosted_zone_id: str,
        name: str,
        record_type: str,
        values: List[str],
        ttl: int = 300
    ) -> Dict[str, Any]:
        """Create DNS record via MCP."""
        return await self.call_tool(
            tool_name="aws_create_dns_record",
            arguments={
                "hosted_zone_id": hosted_zone_id,
                "name": name,
                "record_type": record_type,
                "values": values,
                "ttl": ttl
            },
            server_name="infra-server"
        )
    
    # =========================================================================
    # RAG Tools (via rag-server)
    # =========================================================================
    
    async def rag_search(
        self,
        query: str,
        top_k: int = 10,
        use_hybrid: bool = True,
        filters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Search documents via MCP RAG server."""
        return await self.call_tool(
            tool_name="rag_search",
            arguments={
                "query": query,
                "top_k": top_k,
                "use_hybrid": use_hybrid,
                "filters": filters or {}
            },
            server_name="rag-server"
        )
    
    async def rag_ask(
        self,
        query: str,
        top_k: int = 10,
        include_sources: bool = True
    ) -> Dict[str, Any]:
        """Ask a question via MCP RAG server."""
        return await self.call_tool(
            tool_name="rag_ask",
            arguments={
                "query": query,
                "top_k": top_k,
                "include_sources": include_sources
            },
            server_name="rag-server"
        )
    
    async def rag_reindex(
        self,
        job_type: str = "incremental",
        folder_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Trigger RAG reindexing via MCP."""
        return await self.call_tool(
            tool_name="rag_reindex",
            arguments={
                "job_type": job_type,
                "folder_id": folder_id
            },
            server_name="rag-server"
        )

    # =========================================================================
    # Observability Tools (via prometheus-server)
    # =========================================================================

    async def prometheus_execute_query(self, query: str) -> Dict[str, Any]:
        """Execute PromQL instant query via MCP Prometheus adapter."""
        return await self.call_tool(
            tool_name="prometheus_execute_query",
            arguments={"query": query},
            server_name="prometheus-server",
        )

    async def prometheus_execute_range_query(
        self,
        query: str,
        start_time: str,
        end_time: str,
        step: str = "60s",
    ) -> Dict[str, Any]:
        """Execute PromQL range query via MCP Prometheus adapter."""
        return await self.call_tool(
            tool_name="prometheus_execute_range_query",
            arguments={
                "query": query,
                "start_time": start_time,
                "end_time": end_time,
                "step": step,
            },
            server_name="prometheus-server",
        )

    async def prometheus_list_metrics(self) -> Dict[str, Any]:
        """List Prometheus metric names via MCP Prometheus adapter."""
        return await self.call_tool(
            tool_name="prometheus_list_metrics",
            arguments={},
            server_name="prometheus-server",
        )

    async def prometheus_get_targets(self) -> Dict[str, Any]:
        """List Prometheus scrape targets via MCP Prometheus adapter."""
        return await self.call_tool(
            tool_name="prometheus_get_targets",
            arguments={},
            server_name="prometheus-server",
        )

    async def prometheus_health_check(self) -> Dict[str, Any]:
        """Check Prometheus MCP adapter/upstream health."""
        return await self.call_tool(
            tool_name="prometheus_health_check",
            arguments={},
            server_name="prometheus-server",
        )
    
    # =========================================================================
    # Health & Status
    # =========================================================================
    
    async def health_check(self) -> bool:
        """Check if MCP service is healthy."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # MCP service exposes health at /api/v1/health.
                response = await client.get(
                    f"{self.base_url}/api/v1/health",
                    headers=self._headers(),
                )
                if response.status_code == 200:
                    return True

                # Backward-compatible fallback for deployments exposing /health.
                fallback = await client.get(f"{self.base_url}/health", headers=self._headers())
                return fallback.status_code == 200
        except Exception as e:
            logger.error(f"MCP service health check failed: {e}")
            return False
    
    async def get_server_status(self, server_name: str) -> Dict[str, Any]:
        """Get status of a specific MCP server."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/servers/{server_name}/status"
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to get MCP server status: {e}")
            return {"status": "unknown", "error": str(e)}


# Global instance
mcp_client = MCPClient()
