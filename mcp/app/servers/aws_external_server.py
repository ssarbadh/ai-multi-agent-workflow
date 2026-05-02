"""External AWS MCP adapter server."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.core.logging import logger
from app.servers.base import BaseMCPServer


class AWSExternalMCPServer(BaseMCPServer):
    """Adapter that proxies AWS tools to an external MCP server."""

    def __init__(self):
        super().__init__(
            name="aws-mcp",
            version="0.1.0",
            description="AWS tools proxied via external MCP server",
        )
        self._http_client: Optional[httpx.AsyncClient] = None
        self._base_url = settings.AWS_MCP_URL.rstrip("/")
        self._token = settings.AWS_MCP_BEARER_TOKEN

    async def initialize(self) -> None:
        if not settings.AWS_MCP_ENABLED:
            logger.info("AWS MCP adapter disabled by configuration")
            return

        self._http_client = httpx.AsyncClient(timeout=settings.AWS_MCP_TIMEOUT_SECONDS)
        self.register_tool(
            name="aws_list_load_balancers",
            description="List AWS load balancers, optionally filtered by service hint",
            handler=self._list_load_balancers,
            input_schema={
                "type": "object",
                "properties": {
                    "service_name": {"type": "string"},
                    "region": {"type": "string"},
                },
            },
        )
        self.register_tool(
            name="aws_list_s3_buckets",
            description="List S3 buckets for dependency validation",
            handler=self._list_s3_buckets,
            input_schema={"type": "object", "properties": {"bucket_hint": {"type": "string"}}},
        )
        self.register_tool(
            name="aws_list_rds_instances",
            description="List RDS instances and statuses",
            handler=self._list_rds_instances,
            input_schema={"type": "object", "properties": {"instance_hint": {"type": "string"}, "region": {"type": "string"}}},
        )
        self.register_tool(
            name="aws_list_elasticache_clusters",
            description="List ElastiCache clusters and statuses",
            handler=self._list_elasticache_clusters,
            input_schema={"type": "object", "properties": {"cluster_hint": {"type": "string"}, "region": {"type": "string"}}},
        )
        self.register_tool(
            name="aws_list_ec2_instances",
            description="List EC2 instances for network tracing",
            handler=self._list_ec2_instances,
            input_schema={"type": "object", "properties": {"instance_hint": {"type": "string"}, "region": {"type": "string"}}},
        )
        self.register_tool(
            name="aws_network_dependency_diagnostics",
            description="Gather SG/route/NACL diagnostics for RDS/ElastiCache style dependencies",
            handler=self._network_dependency_diagnostics,
            input_schema={
                "type": "object",
                "properties": {
                    "dependency_host": {"type": "string"},
                    "source_ip": {"type": "string"},
                    "region": {"type": "string"},
                },
                "required": ["dependency_host"],
            },
        )
        logger.info("AWS MCP adapter initialized", upstream=self._base_url)

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

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

    async def _call_upstream_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if not self._http_client:
            return {"type": "text", "text": "AWS MCP adapter client not initialized"}
        payload = {"name": tool_name, "arguments": arguments}
        errors: List[str] = []
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
        return {"type": "text", "text": f"Upstream tool call failed for {tool_name}. {', '.join(errors)}"}

    async def _call_upstream_candidates(
        self,
        candidates: List[tuple[str, Dict[str, Any]]],
    ) -> Dict[str, Any]:
        for tool_name, arguments in candidates:
            resp = await self._call_upstream_tool(tool_name, arguments)
            parsed = self._extract_json_text(resp)
            if parsed:
                if isinstance(parsed, dict):
                    parsed["_upstream_tool"] = tool_name
                return {"type": "text", "text": json.dumps(parsed, ensure_ascii=True)}
        return {"type": "text", "text": json.dumps({}, ensure_ascii=True)}

    @staticmethod
    def _extract_json_text(payload: Dict[str, Any]) -> Any:
        text = payload.get("text", "") if isinstance(payload, dict) else ""
        if not isinstance(text, str):
            return {}
        try:
            return json.loads(text)
        except Exception:  # noqa: BLE001
            return {}

    async def _list_load_balancers(self, service_name: str = "", region: str = "") -> Dict[str, Any]:
        candidates = (
            ("aws_list_load_balancers", {"region": region} if region else {}),
            ("list_load_balancers", {"region": region} if region else {}),
            ("elbv2_describe_load_balancers", {"region": region} if region else {}),
        )
        lbs: List[Dict[str, Any]] = []
        for tool, arguments in candidates:
            resp = await self._call_upstream_tool(tool, arguments)
            parsed = self._extract_json_text(resp)
            if not isinstance(parsed, dict):
                continue
            raw = parsed.get("load_balancers") or parsed.get("LoadBalancers") or []
            if not isinstance(raw, list):
                continue
            for item in raw:
                if not isinstance(item, dict):
                    continue
                lb_name = str(item.get("LoadBalancerName") or item.get("name") or "")
                dns_name = str(item.get("DNSName") or item.get("dns_name") or "")
                if service_name and service_name not in lb_name and service_name not in dns_name:
                    continue
                lbs.append(
                    {
                        "name": lb_name,
                        "dns_name": dns_name,
                        "type": item.get("Type") or item.get("type"),
                        "scheme": item.get("Scheme") or item.get("scheme"),
                    }
                )
            if lbs:
                break

        return {
            "type": "text",
            "text": json.dumps(
                {
                    "provider": "aws",
                    "service_name": service_name,
                    "region": region or None,
                    "load_balancers": lbs[:50],
                },
                ensure_ascii=True,
            ),
        }

    async def _list_s3_buckets(self, bucket_hint: str = "") -> Dict[str, Any]:
        response = await self._call_upstream_candidates(
            [
                ("aws_list_s3_buckets", {}),
                ("list_s3_buckets", {}),
                ("s3_list_buckets", {}),
            ]
        )
        parsed = self._extract_json_text(response)
        buckets = parsed.get("buckets") if isinstance(parsed, dict) else []
        if not isinstance(buckets, list):
            buckets = []
        if bucket_hint:
            buckets = [b for b in buckets if bucket_hint.lower() in str(b).lower()]
        return {
            "type": "text",
            "text": json.dumps({"provider": "aws", "buckets": buckets[:200]}, ensure_ascii=True),
        }

    async def _list_rds_instances(self, instance_hint: str = "", region: str = "") -> Dict[str, Any]:
        response = await self._call_upstream_candidates(
            [
                ("aws_list_rds_instances", {"region": region} if region else {}),
                ("rds_describe_db_instances", {"region": region} if region else {}),
                ("describe_db_instances", {"region": region} if region else {}),
            ]
        )
        parsed = self._extract_json_text(response)
        instances = (
            parsed.get("instances")
            or parsed.get("DBInstances")
            or parsed.get("rds_instances")
            or []
            if isinstance(parsed, dict)
            else []
        )
        if not isinstance(instances, list):
            instances = []
        if instance_hint:
            instances = [i for i in instances if instance_hint.lower() in json.dumps(i, default=str).lower()]
        return {
            "type": "text",
            "text": json.dumps({"provider": "aws", "rds_instances": instances[:100]}, ensure_ascii=True),
        }

    async def _list_elasticache_clusters(self, cluster_hint: str = "", region: str = "") -> Dict[str, Any]:
        response = await self._call_upstream_candidates(
            [
                ("aws_list_elasticache_clusters", {"region": region} if region else {}),
                ("elasticache_describe_cache_clusters", {"region": region} if region else {}),
                ("describe_cache_clusters", {"region": region} if region else {}),
            ]
        )
        parsed = self._extract_json_text(response)
        clusters = (
            parsed.get("clusters")
            or parsed.get("CacheClusters")
            or parsed.get("elasticache_clusters")
            or []
            if isinstance(parsed, dict)
            else []
        )
        if not isinstance(clusters, list):
            clusters = []
        if cluster_hint:
            clusters = [c for c in clusters if cluster_hint.lower() in json.dumps(c, default=str).lower()]
        return {
            "type": "text",
            "text": json.dumps({"provider": "aws", "elasticache_clusters": clusters[:100]}, ensure_ascii=True),
        }

    async def _list_ec2_instances(self, instance_hint: str = "", region: str = "") -> Dict[str, Any]:
        response = await self._call_upstream_candidates(
            [
                ("aws_list_ec2_instances", {"region": region} if region else {}),
                ("aws_list_ec2", {"region": region} if region else {}),
                ("ec2_describe_instances", {"region": region} if region else {}),
            ]
        )
        parsed = self._extract_json_text(response)
        instances = (
            parsed.get("instances")
            or parsed.get("Reservations")
            or parsed.get("ec2_instances")
            or []
            if isinstance(parsed, dict)
            else []
        )
        if not isinstance(instances, list):
            instances = []
        if instance_hint:
            instances = [i for i in instances if instance_hint.lower() in json.dumps(i, default=str).lower()]
        return {
            "type": "text",
            "text": json.dumps({"provider": "aws", "ec2_instances": instances[:200]}, ensure_ascii=True),
        }

    async def _network_dependency_diagnostics(
        self,
        dependency_host: str,
        source_ip: str = "",
        region: str = "",
    ) -> Dict[str, Any]:
        rds = await self._list_rds_instances(instance_hint=dependency_host, region=region)
        cache = await self._list_elasticache_clusters(cluster_hint=dependency_host, region=region)
        ec2 = await self._list_ec2_instances(instance_hint="", region=region)
        sgs = await self._call_upstream_candidates(
            [
                ("aws_list_security_groups", {"region": region} if region else {}),
                ("ec2_describe_security_groups", {"region": region} if region else {}),
            ]
        )
        routes = await self._call_upstream_candidates(
            [
                ("aws_describe_route_tables", {"region": region} if region else {}),
                ("ec2_describe_route_tables", {"region": region} if region else {}),
            ]
        )
        nacls = await self._call_upstream_candidates(
            [
                ("aws_describe_network_acls", {"region": region} if region else {}),
                ("ec2_describe_network_acls", {"region": region} if region else {}),
            ]
        )
        return {
            "type": "text",
            "text": json.dumps(
                {
                    "provider": "aws",
                    "dependency_host": dependency_host,
                    "source_ip": source_ip or None,
                    "region": region or None,
                    "rds": self._extract_json_text(rds),
                    "elasticache": self._extract_json_text(cache),
                    "ec2": self._extract_json_text(ec2),
                    "security_groups": self._extract_json_text(sgs),
                    "route_tables": self._extract_json_text(routes),
                    "network_acls": self._extract_json_text(nacls),
                },
                ensure_ascii=True,
            ),
        }

    async def cleanup(self) -> None:
        if self._http_client:
            await self._http_client.aclose()
