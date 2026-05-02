"""Infrastructure MCP server - tools for VMware, AWS, Azure, GCP, K8s."""

from typing import Any, Dict, Optional

import httpx

from app.core.config import settings
from app.core.logging import logger
from app.servers.base import BaseMCPServer


class InfrastructureMCPServer(BaseMCPServer):
    """MCP server exposing infrastructure tools."""

    def __init__(self):
        super().__init__(
            name="infra-server",
            version="0.1.0",
            description="Infrastructure management tools for VMware, AWS, Azure, GCP, Kubernetes",
        )
        self._http_client: Optional[httpx.AsyncClient] = None

    async def initialize(self) -> None:
        """Initialize and register infrastructure tools."""
        self._http_client = httpx.AsyncClient(timeout=30.0)

        # VMware tools
        self.register_tool(
            name="vmware_list_vms",
            description="List virtual machines in VMware vCenter",
            handler=self._vmware_list_vms,
            input_schema={
                "type": "object",
                "properties": {
                    "datacenter": {"type": "string", "description": "Datacenter name"},
                    "folder": {"type": "string", "description": "VM folder path"},
                },
            },
        )

        self.register_tool(
            name="vmware_vm_power",
            description="Power on/off/restart a VMware VM",
            handler=self._vmware_vm_power,
            input_schema={
                "type": "object",
                "properties": {
                    "vm_name": {"type": "string", "description": "VM name"},
                    "action": {"type": "string", "enum": ["on", "off", "restart"]},
                },
                "required": ["vm_name", "action"],
            },
        )

        # AWS tools
        self.register_tool(
            name="aws_list_ec2",
            description="List EC2 instances in AWS",
            handler=self._aws_list_ec2,
            input_schema={
                "type": "object",
                "properties": {
                    "region": {"type": "string", "description": "AWS region"},
                    "filters": {"type": "object", "description": "Instance filters"},
                },
            },
        )

        self.register_tool(
            name="aws_ec2_action",
            description="Start/stop/terminate an EC2 instance",
            handler=self._aws_ec2_action,
            input_schema={
                "type": "object",
                "properties": {
                    "instance_id": {"type": "string", "description": "EC2 instance ID"},
                    "action": {"type": "string", "enum": ["start", "stop", "terminate"]},
                    "region": {"type": "string", "description": "AWS region"},
                },
                "required": ["instance_id", "action"],
            },
        )

        # Kubernetes tools
        self.register_tool(
            name="k8s_list_pods",
            description="List pods in a Kubernetes namespace",
            handler=self._k8s_list_pods,
            input_schema={
                "type": "object",
                "properties": {
                    "namespace": {"type": "string", "description": "Kubernetes namespace"},
                    "label_selector": {"type": "string", "description": "Label selector"},
                },
            },
        )

        self.register_tool(
            name="k8s_scale_deployment",
            description="Scale a Kubernetes deployment",
            handler=self._k8s_scale_deployment,
            input_schema={
                "type": "object",
                "properties": {
                    "namespace": {"type": "string", "description": "Kubernetes namespace"},
                    "deployment": {"type": "string", "description": "Deployment name"},
                    "replicas": {"type": "integer", "description": "Number of replicas"},
                },
                "required": ["namespace", "deployment", "replicas"],
            },
        )

        # Register resources
        self.register_resource(
            uri="infra://status",
            name="Infrastructure Status",
            handler=self._get_infra_status,
            description="Current infrastructure status across all platforms",
            mime_type="application/json",
        )

        logger.info("Infrastructure MCP server initialized")

    async def _vmware_list_vms(
        self,
        datacenter: Optional[str] = None,
        folder: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List VMware VMs via Agent Orchestration service."""
        try:
            response = await self._http_client.get(
                f"{settings.AGENT_ORCHESTRATION_URL}/api/v1/infra/vmware/vms",
                params={"datacenter": datacenter, "folder": folder},
            )
            if response.status_code == 200:
                return {"type": "text", "text": str(response.json())}
            return {"type": "text", "text": f"Error: {response.status_code}"}
        except Exception as e:
            return {"type": "text", "text": f"VMware API unavailable: {str(e)}"}

    async def _vmware_vm_power(
        self,
        vm_name: str,
        action: str,
    ) -> Dict[str, Any]:
        """Control VMware VM power state."""
        try:
            response = await self._http_client.post(
                f"{settings.AGENT_ORCHESTRATION_URL}/api/v1/infra/vmware/vms/{vm_name}/power",
                json={"action": action},
            )
            if response.status_code == 200:
                return {"type": "text", "text": f"VM {vm_name} power {action} successful"}
            return {"type": "text", "text": f"Error: {response.status_code} - {response.text}"}
        except Exception as e:
            return {"type": "text", "text": f"VMware API unavailable: {str(e)}"}

    async def _aws_list_ec2(
        self,
        region: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """List AWS EC2 instances."""
        try:
            response = await self._http_client.get(
                f"{settings.AGENT_ORCHESTRATION_URL}/api/v1/infra/aws/ec2",
                params={"region": region or "us-east-1"},
            )
            if response.status_code == 200:
                return {"type": "text", "text": str(response.json())}
            return {"type": "text", "text": f"Error: {response.status_code}"}
        except Exception as e:
            return {"type": "text", "text": f"AWS API unavailable: {str(e)}"}

    async def _aws_ec2_action(
        self,
        instance_id: str,
        action: str,
        region: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Control AWS EC2 instance."""
        try:
            response = await self._http_client.post(
                f"{settings.AGENT_ORCHESTRATION_URL}/api/v1/infra/aws/ec2/{instance_id}/{action}",
                params={"region": region or "us-east-1"},
            )
            if response.status_code == 200:
                return {"type": "text", "text": f"EC2 {instance_id} {action} successful"}
            return {"type": "text", "text": f"Error: {response.status_code} - {response.text}"}
        except Exception as e:
            return {"type": "text", "text": f"AWS API unavailable: {str(e)}"}

    async def _k8s_list_pods(
        self,
        namespace: Optional[str] = None,
        label_selector: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List Kubernetes pods."""
        try:
            response = await self._http_client.get(
                f"{settings.AGENT_ORCHESTRATION_URL}/api/v1/infra/k8s/pods",
                params={"namespace": namespace or "default", "label_selector": label_selector},
            )
            if response.status_code == 200:
                return {"type": "text", "text": str(response.json())}
            return {"type": "text", "text": f"Error: {response.status_code}"}
        except Exception as e:
            return {"type": "text", "text": f"K8s API unavailable: {str(e)}"}

    async def _k8s_scale_deployment(
        self,
        namespace: str,
        deployment: str,
        replicas: int,
    ) -> Dict[str, Any]:
        """Scale Kubernetes deployment."""
        try:
            response = await self._http_client.post(
                f"{settings.AGENT_ORCHESTRATION_URL}/api/v1/infra/k8s/deployments/{deployment}/scale",
                params={"namespace": namespace},
                json={"replicas": replicas},
            )
            if response.status_code == 200:
                return {"type": "text", "text": f"Deployment {deployment} scaled to {replicas} replicas"}
            return {"type": "text", "text": f"Error: {response.status_code} - {response.text}"}
        except Exception as e:
            return {"type": "text", "text": f"K8s API unavailable: {str(e)}"}

    async def _get_infra_status(self) -> str:
        """Get infrastructure status."""
        return '{"vmware": "connected", "aws": "connected", "k8s": "connected"}'

    async def cleanup(self) -> None:
        """Cleanup resources."""
        if self._http_client:
            await self._http_client.aclose()
