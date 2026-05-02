"""External Istio adapter server.

Provides read-only access to Istio service mesh resources in Kubernetes clusters,
aligned with https://github.com/krutsko/istio-mcp-server tool semantics.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logging import logger
from app.servers.base import BaseMCPServer


class IstioExternalMCPServer(BaseMCPServer):
    """Adapter that queries Istio resources via Kubernetes API."""

    ISTIO_GROUP = "networking.istio.io"
    ISTIO_VS_VERSIONS = ("v1", "v1beta1", "v1alpha3")
    ISTIO_DR_VERSIONS = ("v1", "v1beta1", "v1alpha3")
    ISTIO_VS_PLURAL = "virtualservices"
    ISTIO_DR_PLURAL = "destinationrules"

    def __init__(self):
        super().__init__(
            name="istio-server",
            version="0.1.0",
            description="Istio service mesh tools for Virtual Services, Destination Rules, and mesh hosts",
        )
        self._custom_api = None
        self._core_v1 = None

    async def initialize(self) -> None:
        if not settings.ISTIO_MCP_ENABLED:
            logger.info("Istio MCP adapter disabled by configuration")
            return

        try:
            from kubernetes import client, config
            from kubernetes.config.config_exception import ConfigException

            try:
                if settings.ISTIO_MCP_IN_CLUSTER:
                    config.load_incluster_config()
                else:
                    config.load_kube_config(
                        config_file=settings.ISTIO_MCP_KUBECONFIG_PATH or None,
                        context=settings.ISTIO_MCP_CONTEXT or None,
                    )
            except ConfigException as exc:
                logger.warning("Istio adapter: could not load kubeconfig", exc=str(exc))
                return

            self._custom_api = client.CustomObjectsApi()
            self._core_v1 = client.CoreV1Api()

            self.register_tool(
                name="istio_get_virtual_service",
                description="Get a specific Virtual Service configuration by name",
                handler=self._get_virtual_service,
                input_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "namespace": {"type": "string", "default": "default"},
                    },
                    "required": ["name"],
                },
            )
            self.register_tool(
                name="istio_get_destination_rule",
                description="Get a specific Destination Rule configuration by name",
                handler=self._get_destination_rule,
                input_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "namespace": {"type": "string", "default": "default"},
                    },
                    "required": ["name"],
                },
            )
            self.register_tool(
                name="istio_get_service_mesh_hosts",
                description="List all services and hosts in the service mesh for a namespace",
                handler=self._get_service_mesh_hosts,
                input_schema={
                    "type": "object",
                    "properties": {
                        "namespace": {"type": "string", "default": "default"},
                    },
                },
            )
            self.register_tool(
                name="istio_get_pods_by_service",
                description="Find all pods backing a specific Kubernetes service",
                handler=self._get_pods_by_service,
                input_schema={
                    "type": "object",
                    "properties": {
                        "service_name": {"type": "string"},
                        "namespace": {"type": "string", "default": "default"},
                    },
                    "required": ["service_name"],
                },
            )
            self.register_tool(
                name="istio_get_istio_resources_for_service",
                description="Get Virtual Services and Destination Rules relevant to a service (for RCA context)",
                handler=self._get_istio_resources_for_service,
                input_schema={
                    "type": "object",
                    "properties": {
                        "service_name": {"type": "string"},
                        "namespace": {"type": "string", "default": "default"},
                    },
                    "required": ["service_name"],
                },
            )
            self.register_tool(
                name="istio_list_virtual_services_in_namespace",
                description=(
                    "List VirtualServices: namespaced (one or comma-separated namespaces) or "
                    "cluster-wide. Returns JSON with virtual_services or error (Kubernetes API)."
                ),
                handler=self._list_virtual_services_in_namespace,
                input_schema={
                    "type": "object",
                    "properties": {
                        "namespace": {
                            "type": "string",
                            "default": "default",
                            "description": "Single namespace or comma-separated list when list_scope is namespaced",
                        },
                        "max_items": {"type": "integer", "default": 500},
                        "list_scope": {
                            "type": "string",
                            "enum": ["namespaced", "cluster"],
                            "default": "namespaced",
                            "description": "cluster = list all VirtualServices in the cluster (requires RBAC)",
                        },
                    },
                },
            )

            logger.info("Istio MCP adapter initialized")
        except ImportError as exc:
            logger.warning("Istio adapter: kubernetes package not installed", exc=str(exc))

    @staticmethod
    def _tool_text(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"type": "text", "text": json.dumps(payload, default=str, ensure_ascii=True)}

    @staticmethod
    def _split_namespace_list(namespace: str) -> List[str]:
        """Parse 'flights,activity' or 'flights; activity' into a list."""
        s = (namespace or "default").strip()
        if not s:
            return ["default"]
        parts = [p.strip() for p in s.replace(";", ",").split(",") if p.strip()]
        return parts or ["default"]

    def _istio_failure(self, message: str, **extra: Any) -> Dict[str, Any]:
        """Always return JSON-parseable tool payload (enrichment depends on json.loads)."""
        payload: Dict[str, Any] = {
            "provider": "istio",
            "error": message,
            "virtual_services": [],
        }
        payload.update(extra)
        return self._tool_text(payload)

    def _ensure_client(self) -> str | None:
        if not self._custom_api or not self._core_v1:
            return "Istio adapter client not initialized (check kubeconfig)"
        return None

    @staticmethod
    def _mesh_match_tokens(service_name: str, namespace: str) -> List[str]:
        """Tokens for matching VS/DR: FQDN forms + workload name (avoid single short tokens)."""
        s = (service_name or "").strip()
        ns = (namespace or "").strip()
        raw: List[Optional[str]] = [
            s,
            s.lower() if s else None,
            f"{s}.{ns}" if s and ns else None,
            f"{s}.{ns}.svc.cluster.local" if s and ns else None,
            f"{s}.{ns}.svc" if s and ns else None,
        ]
        if s:
            raw.append(s.replace("-service", ""))
            raw.append(s.replace("-deployment", ""))
        out: List[str] = []
        for t in raw:
            if not t:
                continue
            t = t.strip()
            if len(t) >= 3 and t not in out:
                out.append(t)
        return out

    @staticmethod
    def _collect_spec_string_values(obj: Any, out: List[str], limit: int = 1200) -> None:
        if len(out) >= limit:
            return
        if isinstance(obj, str):
            if obj and len(obj) < 1024:
                out.append(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                IstioExternalMCPServer._collect_spec_string_values(v, out, limit)
        elif isinstance(obj, list):
            for v in obj:
                IstioExternalMCPServer._collect_spec_string_values(v, out, limit)

    def _spec_text_matches_tokens(self, spec: Any, tokens: List[str]) -> bool:
        """True if any token appears in spec (covers http.route.destination.host etc.)."""
        strings: List[str] = []
        self._collect_spec_string_values(spec, strings)
        blob = " ".join(strings).lower()
        for t in tokens:
            tl = t.lower()
            if len(tl) < 4:
                continue
            if tl in blob:
                return True
        return False

    def _virtual_service_matches_service(
        self,
        item: Dict[str, Any],
        tokens: List[str],
    ) -> bool:
        meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        name = str(meta.get("name", "") or "")
        labels = meta.get("labels") if isinstance(meta.get("labels"), dict) else {}
        spec = item.get("spec") if isinstance(item.get("spec"), dict) else {}
        token_set = {t.lower() for t in tokens if len(t) >= 3}
        for t in token_set:
            if len(t) >= 4 and t in name.lower():
                return True
        for v in labels.values():
            if isinstance(v, str) and len(v) >= 3:
                vl = v.lower()
                for t in token_set:
                    if len(t) >= 4 and t in vl:
                        return True
        hosts = spec.get("hosts")
        if isinstance(hosts, list):
            for h in hosts:
                if not isinstance(h, str):
                    continue
                hl = h.lower()
                for t in token_set:
                    if len(t) >= 4 and t in hl:
                        return True
        if self._spec_text_matches_tokens(spec, tokens):
            return True
        gateways = spec.get("gateways")
        if isinstance(gateways, list):
            for g in gateways:
                if isinstance(g, str):
                    gl = g.lower()
                    for t in token_set:
                        if len(t) >= 4 and t in gl:
                            return True
        return False

    def _destination_rule_matches_service(
        self,
        item: Dict[str, Any],
        tokens: List[str],
    ) -> bool:
        meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        name = str(meta.get("name", "") or "")
        spec = item.get("spec") if isinstance(item.get("spec"), dict) else {}
        token_set = {t.lower() for t in tokens if len(t) >= 3}
        for t in token_set:
            if len(t) >= 4 and t in name.lower():
                return True
        host = spec.get("host")
        if isinstance(host, str):
            hl = host.lower()
            for t in token_set:
                if len(t) >= 4 and (t in hl or hl.endswith(t) or t in hl.replace("*", "")):
                    return True
        if self._spec_text_matches_tokens(spec, tokens):
            return True
        return False

    def _get_namespaced_with_fallback(
        self,
        plural: str,
        namespace: str,
        name: str,
        versions: tuple[str, ...],
    ) -> Dict[str, Any]:
        last_exc: Optional[Exception] = None
        for version in versions:
            try:
                return self._custom_api.get_namespaced_custom_object(
                    group=self.ISTIO_GROUP,
                    version=version,
                    namespace=namespace,
                    plural=plural,
                    name=name,
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
        raise last_exc or RuntimeError("Istio API call failed")

    def _list_namespaced_with_fallback(
        self,
        plural: str,
        namespace: str,
        versions: tuple[str, ...],
    ) -> Dict[str, Any]:
        last_exc: Optional[Exception] = None
        for version in versions:
            try:
                return self._custom_api.list_namespaced_custom_object(
                    group=self.ISTIO_GROUP,
                    version=version,
                    namespace=namespace,
                    plural=plural,
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
        raise last_exc or RuntimeError("Istio API list failed")

    async def _get_virtual_service(self, name: str, namespace: str = "default") -> Dict[str, Any]:
        err = self._ensure_client()
        if err:
            return self._istio_failure(err, resource="VirtualService")
        try:
            obj = self._get_namespaced_with_fallback(
                plural=self.ISTIO_VS_PLURAL,
                namespace=namespace,
                name=name,
                versions=self.ISTIO_VS_VERSIONS,
            )
            return self._tool_text({
                "provider": "istio",
                "resource": "VirtualService",
                "name": name,
                "namespace": namespace,
                "spec": obj.get("spec", {}),
                "metadata": {
                    "name": obj.get("metadata", {}).get("name"),
                    "labels": obj.get("metadata", {}).get("labels", {}),
                },
            })
        except Exception as exc:  # noqa: BLE001
            return self._istio_failure(
                f"Istio VirtualService '{name}' not found or error: {exc}",
                resource="VirtualService",
                name=name,
                namespace=namespace,
            )

    async def _get_destination_rule(self, name: str, namespace: str = "default") -> Dict[str, Any]:
        err = self._ensure_client()
        if err:
            return self._istio_failure(err, resource="DestinationRule")
        try:
            obj = self._get_namespaced_with_fallback(
                plural=self.ISTIO_DR_PLURAL,
                namespace=namespace,
                name=name,
                versions=self.ISTIO_DR_VERSIONS,
            )
            return self._tool_text({
                "provider": "istio",
                "resource": "DestinationRule",
                "name": name,
                "namespace": namespace,
                "spec": obj.get("spec", {}),
                "metadata": {
                    "name": obj.get("metadata", {}).get("name"),
                    "labels": obj.get("metadata", {}).get("labels", {}),
                },
            })
        except Exception as exc:  # noqa: BLE001
            return self._istio_failure(
                f"Istio DestinationRule '{name}' not found or error: {exc}",
                resource="DestinationRule",
                name=name,
                namespace=namespace,
            )

    async def _get_service_mesh_hosts(self, namespace: str = "default") -> Dict[str, Any]:
        err = self._ensure_client()
        if err:
            return self._istio_failure(err, resource="ServiceMeshHosts")
        try:
            svc_list = self._core_v1.list_namespaced_service(namespace=namespace)
            hosts = []
            for svc in svc_list.items:
                hosts.append({
                    "name": svc.metadata.name,
                    "namespace": svc.metadata.namespace,
                    "cluster_ip": svc.spec.cluster_ip if svc.spec else None,
                    "ports": [{"port": p.port, "name": p.name} for p in (svc.spec.ports or [])],
                })
            return self._tool_text({
                "provider": "istio",
                "resource": "ServiceMeshHosts",
                "namespace": namespace,
                "count": len(hosts),
                "hosts": hosts,
            })
        except Exception as exc:  # noqa: BLE001
            return self._istio_failure(
                f"Istio service mesh hosts list failed: {exc}",
                resource="ServiceMeshHosts",
                namespace=namespace,
                hosts=[],
            )

    async def _get_pods_by_service(
        self,
        service_name: str,
        namespace: str = "default",
    ) -> Dict[str, Any]:
        err = self._ensure_client()
        if err:
            return self._istio_failure(err, resource="PodsByService")
        try:
            svc = self._core_v1.read_namespaced_service(name=service_name, namespace=namespace)
            selector = svc.spec.selector if svc.spec and svc.spec.selector else {}
            if not selector:
                return self._tool_text({
                    "provider": "istio",
                    "resource": "PodsByService",
                    "service_name": service_name,
                    "namespace": namespace,
                    "pods": [],
                    "message": "Service has no selector",
                })
            label_sel = ",".join(f"{k}={v}" for k, v in selector.items())
            pod_list = self._core_v1.list_namespaced_pod(
                namespace=namespace,
                label_selector=label_sel,
            )
            pods = []
            for pod in pod_list.items:
                pods.append({
                    "name": pod.metadata.name,
                    "phase": pod.status.phase if pod.status else None,
                    "ip": pod.status.pod_ip if pod.status else None,
                })
            return self._tool_text({
                "provider": "istio",
                "resource": "PodsByService",
                "service_name": service_name,
                "namespace": namespace,
                "selector": selector,
                "count": len(pods),
                "pods": pods,
            })
        except Exception as exc:  # noqa: BLE001
            return self._istio_failure(
                f"Istio get pods by service failed: {exc}",
                resource="PodsByService",
                service_name=service_name,
                namespace=namespace,
                pods=[],
            )

    async def _get_istio_resources_for_service(
        self,
        service_name: str,
        namespace: str = "default",
    ) -> Dict[str, Any]:
        """Aggregate Istio resources relevant to a service for RCA context."""
        err = self._ensure_client()
        if err:
            return self._istio_failure(err, service_name=service_name, namespace=namespace)
        result: Dict[str, Any] = {
            "provider": "istio",
            "service_name": service_name,
            "namespace": namespace,
            "virtual_services": [],
            "destination_rules": [],
            "pods": [],
            "match_note": (
                "vs_dr_match uses hosts, metadata name/labels, and full spec string scan "
                "(http/tcp/tls route destination.host, etc.) — not only spec.hosts."
            ),
        }
        try:
            tokens = self._mesh_match_tokens(service_name, namespace)
            # List VirtualServices in namespace and filter by host matching service
            vs_list = self._list_namespaced_with_fallback(
                plural=self.ISTIO_VS_PLURAL,
                namespace=namespace,
                versions=self.ISTIO_VS_VERSIONS,
            )
            for item in vs_list.get("items", []):
                if not isinstance(item, dict):
                    continue
                if not self._virtual_service_matches_service(item, tokens):
                    continue
                spec = item.get("spec", {}) if isinstance(item.get("spec"), dict) else {}
                hosts = spec.get("hosts", []) if isinstance(spec.get("hosts"), list) else []
                result["virtual_services"].append({
                    "name": item.get("metadata", {}).get("name"),
                    "hosts": hosts,
                    "http": spec.get("http", [])[:3],
                })

            # List DestinationRules that might apply (name contains service or is service)
            dr_list = self._list_namespaced_with_fallback(
                plural=self.ISTIO_DR_PLURAL,
                namespace=namespace,
                versions=self.ISTIO_DR_VERSIONS,
            )
            for item in dr_list.get("items", []):
                if not isinstance(item, dict):
                    continue
                if not self._destination_rule_matches_service(item, tokens):
                    continue
                spec = item.get("spec", {}) if isinstance(item.get("spec"), dict) else {}
                host = spec.get("host", "")
                result["destination_rules"].append({
                    "name": item.get("metadata", {}).get("name"),
                    "host": host,
                    "trafficPolicy": spec.get("trafficPolicy"),
                })

            # Get pods backing the service
            try:
                svc = self._core_v1.read_namespaced_service(name=service_name, namespace=namespace)
                selector = svc.spec.selector if svc.spec and svc.spec.selector else {}
                if selector:
                    label_sel = ",".join(f"{k}={v}" for k, v in selector.items())
                    pod_list = self._core_v1.list_namespaced_pod(
                        namespace=namespace,
                        label_selector=label_sel,
                    )
                    for pod in pod_list.items[:10]:
                        result["pods"].append({
                            "name": pod.metadata.name,
                            "phase": pod.status.phase if pod.status else None,
                        })
            except Exception:  # noqa: S110
                pass

            return self._tool_text(result)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Istio get_istio_resources_for_service Kubernetes API error",
                service=service_name,
                namespace=namespace,
                exc=str(exc),
            )
            return self._istio_failure(
                f"Istio resources for service failed: {exc}",
                service_name=service_name,
                namespace=namespace,
                destination_rules=[],
                pods=[],
            )

    def _virtual_service_item_to_entry(self, item: Dict[str, Any]) -> Dict[str, Any]:
        spec = item.get("spec", {}) or {}
        meta = item.get("metadata", {}) or {}
        return {
            "name": meta.get("name"),
            "namespace": meta.get("namespace"),
            "hosts": spec.get("hosts", []),
            "http": (spec.get("http", []) or [])[:20],
            "tcp": (spec.get("tcp", []) or [])[:20],
            "tls": (spec.get("tls", []) or [])[:20],
        }

    async def _list_virtual_services_in_namespace(
        self,
        namespace: str = "default",
        max_items: int = 500,
        list_scope: str = "namespaced",
    ) -> Dict[str, Any]:
        """Return VirtualServices for call-graph extraction (namespaced multi-ns or cluster-wide)."""
        err = self._ensure_client()
        if err:
            return self._istio_failure(err, resource="VirtualServiceList", list_scope=list_scope)

        cap = max(1, min(int(max_items), 2000))
        try:
            virtual_services: List[Dict[str, Any]] = []

            if list_scope == "cluster":
                vs_list = {"items": []}
                last_exc: Optional[Exception] = None
                for version in self.ISTIO_VS_VERSIONS:
                    try:
                        vs_list = self._custom_api.list_cluster_custom_object(
                            group=self.ISTIO_GROUP,
                            version=version,
                            plural=self.ISTIO_VS_PLURAL,
                        )
                        last_exc = None
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_exc = exc
                if last_exc:
                    raise last_exc
                for item in vs_list.get("items", [])[:cap]:
                    virtual_services.append(self._virtual_service_item_to_entry(item))
                return self._tool_text({
                    "provider": "istio",
                    "resource": "VirtualServiceList",
                    "list_scope": "cluster",
                    "namespaces_scanned": None,
                    "count": len(virtual_services),
                    "virtual_services": virtual_services,
                })

            namespaces_scanned: List[str] = []
            per_ns_budget = max(cap // max(len(self._split_namespace_list(namespace)), 1), 50)
            for ns in self._split_namespace_list(namespace):
                namespaces_scanned.append(ns)
                vs_list = self._list_namespaced_with_fallback(
                    plural=self.ISTIO_VS_PLURAL,
                    namespace=ns,
                    versions=self.ISTIO_VS_VERSIONS,
                )
                for item in vs_list.get("items", [])[:per_ns_budget]:
                    virtual_services.append(self._virtual_service_item_to_entry(item))
                if len(virtual_services) >= cap:
                    virtual_services = virtual_services[:cap]
                    break

            return self._tool_text({
                "provider": "istio",
                "resource": "VirtualServiceList",
                "list_scope": "namespaced",
                "namespaces_scanned": namespaces_scanned,
                "namespace": namespace,
                "count": len(virtual_services),
                "virtual_services": virtual_services,
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Istio list VirtualServices Kubernetes API error",
                namespace=namespace,
                list_scope=list_scope,
                exc=str(exc),
            )
            return self._istio_failure(
                f"Istio list VirtualServices failed: {exc}",
                resource="VirtualServiceList",
                list_scope=list_scope,
                namespace=namespace,
                namespaces_scanned=self._split_namespace_list(namespace) if list_scope != "cluster" else None,
            )

    async def cleanup(self) -> None:
        self._custom_api = None
        self._core_v1 = None
