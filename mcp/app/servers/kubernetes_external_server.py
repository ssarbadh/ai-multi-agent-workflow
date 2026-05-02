"""External Kubernetes MCP adapter server."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

import httpx
import yaml

from app.core.config import settings
from app.core.logging import logger
from app.servers.base import BaseMCPServer


class KubernetesExternalMCPServer(BaseMCPServer):
    """Adapter that proxies Kubernetes tools to an external MCP server."""

    def __init__(self):
        super().__init__(
            name="kubernetes-mcp",
            version="0.1.0",
            description="Kubernetes tools proxied via external MCP server",
        )
        self._http_client: Optional[httpx.AsyncClient] = None
        self._base_url = settings.KUBERNETES_MCP_URL.rstrip("/")
        self._token = settings.KUBERNETES_MCP_BEARER_TOKEN
        _b = (getattr(settings, "KUBERNETES_MCP_BACKEND", None) or "flux").lower().strip()
        self._backend: str = _b if _b in ("flux", "containers") else "flux"
        self._local_core_v1: Any = None
        self._local_apps_v1: Any = None

    async def initialize(self) -> None:
        if not settings.KUBERNETES_MCP_ENABLED:
            logger.info("Kubernetes MCP adapter disabled by configuration")
            return

        self._http_client = httpx.AsyncClient(
            timeout=settings.KUBERNETES_MCP_TIMEOUT_SECONDS,
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
        )

        self.register_tool(
            name="kubernetes_list_workloads",
            description=(
                "List deployments/statefulsets (optional pods) by name substring. "
                "Default omits namespace-wide pod list (large; can ENOBUFS). "
                "Set include_pods true to add a second kubectl pod list."
            ),
            handler=self._list_workloads,
            input_schema={
                "type": "object",
                "properties": {
                    "service_name": {"type": "string"},
                    "namespace": {"type": "string", "default": "default"},
                    "include_pods": {
                        "type": "boolean",
                        "default": False,
                        "description": "If true, run a second kubectl list for pods (slower; large namespaces may fail with ENOBUFS)",
                    },
                },
                "required": ["service_name"],
            },
        )
        self.register_tool(
            name="kubernetes_get_pod_logs",
            description="Get pod logs for a service or explicit pod name",
            handler=self._get_pod_logs,
            input_schema={
                "type": "object",
                "properties": {
                    "service_name": {"type": "string"},
                    "pod_name": {"type": "string"},
                    "namespace": {"type": "string", "default": "default"},
                    "tail_lines": {"type": "integer", "default": 200},
                },
            },
        )
        self.register_tool(
            name="kubernetes_get_service_runtime_context",
            description="Get pods, node names, pod IPs and node hints for a service",
            handler=self._get_service_runtime_context,
            input_schema={
                "type": "object",
                "properties": {
                    "service_name": {"type": "string"},
                    "namespace": {"type": "string", "default": "default"},
                },
                "required": ["service_name"],
            },
        )

        if getattr(settings, "KUBERNETES_MCP_LOCAL_WRITE_ENABLED", False):
            self._init_local_k8s_write_tools()

        if settings.KUBERNETES_MCP_EXPOSE_UPSTREAM_TOOLS:
            if self._backend == "flux":
                await self._register_flux_upstream_tools()
            elif self._backend == "containers":
                await self._register_containers_upstream_tools()

        logger.info(
            "Kubernetes MCP adapter initialized",
            upstream=self._base_url,
            backend=self._backend,
        )

    def _mcp_http_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
            if self._backend == "flux":
                headers["X-MCP-AUTH"] = self._token
        return headers

    @staticmethod
    def _parse_streamable_http_sse(body: str) -> Optional[Dict[str, Any]]:
        for line in body.splitlines():
            s = line.strip()
            if s.startswith("data:"):
                raw = s[5:].strip()
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return None
        return None

    async def _mcp_json_rpc(self, method: str, params: Any) -> Dict[str, Any]:
        if not self._http_client:
            return {"error": {"message": "Kubernetes MCP adapter client not initialized"}}
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params if params is not None else {},
        }
        url = f"{self._base_url}/mcp"
        response = await self._http_client.post(
            url,
            json=payload,
            headers=self._mcp_http_headers(),
        )
        response.raise_for_status()
        data = self._parse_streamable_http_sse(response.text)
        if data is None:
            return {
                "error": {
                    "message": "empty_or_invalid_sse",
                    "data": response.text[:800],
                }
            }
        return data

    async def _mcp_tools_call(self, flux_tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        data = await self._mcp_json_rpc(
            "tools/call",
            {"name": flux_tool, "arguments": arguments},
        )
        if "error" in data:
            err = data["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            return {"type": "text", "text": json.dumps({"error": msg}, ensure_ascii=True)}
        return KubernetesExternalMCPServer._normalize_upstream_response(data.get("result", {}))

    @staticmethod
    def _flux_tool_input_schema(tool: Dict[str, Any]) -> Dict[str, Any]:
        raw = tool.get("inputSchema") or {"type": "object", "properties": {}}
        if not isinstance(raw, dict):
            return {"type": "object", "properties": {}}
        return {
            "type": raw.get("type", "object"),
            "properties": raw.get("properties") or {},
            "required": list(raw.get("required") or []),
        }

    @staticmethod
    def _flux_tool_is_destructive(tool: Dict[str, Any]) -> bool:
        ann = tool.get("annotations") if isinstance(tool.get("annotations"), dict) else {}
        return bool(ann.get("destructiveHint"))

    @staticmethod
    def _flux_proxy_handler_factory(server: "KubernetesExternalMCPServer", flux_name: str):
        async def _handler(**kwargs: Any) -> Dict[str, Any]:
            args = {k: v for k, v in kwargs.items() if v is not None}
            return await server._mcp_tools_call(flux_name, args)

        return _handler

    async def _register_flux_upstream_tools(self) -> None:
        if not self._http_client:
            return
        try:
            data = await self._mcp_json_rpc("tools/list", {})
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "kubernetes MCP tools/list failed; only convenience tools registered",
                extra={"upstream": self._base_url, "error": str(exc)},
            )
            return
        if "error" in data:
            err = data["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            logger.warning("kubernetes MCP tools/list returned error", extra={"message": msg})
            return
        result = data.get("result") or {}
        flux_tools = result.get("tools") or []
        if not isinstance(flux_tools, list):
            return
        include_destructive = settings.KUBERNETES_MCP_UPSTREAM_INCLUDE_DESTRUCTIVE
        registered = 0
        for tool in flux_tools:
            if not isinstance(tool, dict):
                continue
            flux_name = tool.get("name")
            if not flux_name or not isinstance(flux_name, str):
                continue
            if not include_destructive and self._flux_tool_is_destructive(tool):
                continue
            reg_name = f"kubernetes_flux_{flux_name}"
            if reg_name in self._tools:
                continue
            desc = str(tool.get("description") or flux_name)
            schema = self._flux_tool_input_schema(tool)

            self.register_tool(
                name=reg_name,
                description=f"[Flux upstream: {flux_name}] {desc}",
                handler=self._flux_proxy_handler_factory(self, flux_name),
                input_schema=schema,
            )
            registered += 1
        logger.info(
            "Registered Flux upstream Kubernetes tools",
            extra={"count": registered, "upstream": self._base_url},
        )

    @staticmethod
    def _containers_tool_is_destructive(tool: Dict[str, Any]) -> bool:
        name = str(tool.get("name") or "").lower()
        if "delete" in name or name.endswith("_uninstall") or name.startswith("helm_uninstall"):
            return True
        ann = tool.get("annotations") if isinstance(tool.get("annotations"), dict) else {}
        return bool(ann.get("destructiveHint"))

    async def _register_containers_upstream_tools(self) -> None:
        if not self._http_client:
            return
        try:
            data = await self._mcp_json_rpc("tools/list", {})
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "containers kubernetes MCP tools/list failed",
                extra={"upstream": self._base_url, "error": str(exc)},
            )
            return
        if "error" in data:
            err = data["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            logger.warning("containers kubernetes MCP tools/list error", extra={"message": msg})
            return
        result = data.get("result") or {}
        ctr_tools = result.get("tools") or []
        if not isinstance(ctr_tools, list):
            return
        include_destructive = settings.KUBERNETES_MCP_UPSTREAM_INCLUDE_DESTRUCTIVE
        registered = 0
        for tool in ctr_tools:
            if not isinstance(tool, dict):
                continue
            tname = tool.get("name")
            if not tname or not isinstance(tname, str):
                continue
            if not include_destructive and self._containers_tool_is_destructive(tool):
                continue
            reg_name = f"kubernetes_native_{tname}"
            if reg_name in self._tools:
                continue
            desc = str(tool.get("description") or tname)
            schema = self._flux_tool_input_schema(tool)

            self.register_tool(
                name=reg_name,
                description=f"[containers/kubernetes-mcp-server: {tname}] {desc}",
                handler=self._flux_proxy_handler_factory(self, tname),
                input_schema=schema,
            )
            registered += 1
        logger.info(
            "Registered containers upstream Kubernetes tools",
            extra={"count": registered, "upstream": self._base_url},
        )

    def _map_legacy_to_upstream(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> Optional[Tuple[str, Dict[str, Any]]]:
        if self._backend == "containers":
            if tool_name == "resources_list":
                kind = str(arguments.get("kind", ""))
                if kind == "Deployment":
                    av = "apps/v1"
                elif kind == "StatefulSet":
                    av = "apps/v1"
                elif kind == "Pod":
                    av = "v1"
                else:
                    av = str(arguments.get("apiVersion", "apps/v1"))
                return (
                    "resources_list",
                    {
                        "apiVersion": av,
                        "kind": kind,
                        "namespace": arguments.get("namespace"),
                    },
                )
            if tool_name == "pods_list_in_namespace":
                return (
                    "pods_list_in_namespace",
                    {"namespace": str(arguments.get("namespace", "default"))},
                )
            if tool_name == "pods_log":
                return (
                    "pods_log",
                    {
                        "name": str(arguments.get("name", "")),
                        "namespace": str(arguments.get("namespace", "default")),
                        "tail": int(arguments.get("tail", 200)),
                    },
                )
            return None

        if tool_name == "resources_list":
            kind = str(arguments.get("kind", ""))
            ns = str(arguments.get("namespace", "default"))
            resource_type = {
                "Deployment": "deployments",
                "StatefulSet": "statefulsets",
                "Pod": "pods",
            }.get(kind)
            if not resource_type:
                return None
            return ("kubectl_get", {"resourceType": resource_type, "namespace": ns, "output": "json"})
        if tool_name == "pods_list_in_namespace":
            return (
                "kubectl_get",
                {
                    "resourceType": "pods",
                    "namespace": str(arguments.get("namespace", "default")),
                    "output": "json",
                },
            )
        if tool_name == "pods_log":
            return (
                "kubectl_logs",
                {
                    "resourceType": "pod",
                    "name": str(arguments.get("name", "")),
                    "namespace": str(arguments.get("namespace", "default")),
                    "tail": int(arguments.get("tail", 200)),
                },
            )
        return None

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
        mapped = self._map_legacy_to_upstream(tool_name, arguments)
        if not mapped:
            return {"type": "text", "text": f"No upstream tool mapping for {tool_name} (backend={self._backend})"}
        upstream_tool, upstream_args = mapped
        try:
            return await self._mcp_tools_call(upstream_tool, upstream_args)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "kubernetes MCP tools/call failed",
                extra={"legacy_tool": tool_name, "upstream_tool": upstream_tool, "error": str(exc)},
            )
            return {
                "type": "text",
                "text": f"Upstream MCP call failed for {tool_name} -> {upstream_tool}: {exc}",
            }

    @staticmethod
    def _coerce_kubectl_list_json(parsed: Any) -> Any:
        # containers/kubernetes-mcp-server YAML list output is often a sequence of resources, not kind: List
        if isinstance(parsed, list):
            parsed = {"items": parsed}
        if not isinstance(parsed, dict):
            return parsed
        items = parsed.get("items")
        if not isinstance(items, list):
            return parsed
        out: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if "metadata" in item:
                out.append(item)
                continue
            if "name" in item:
                out.append(
                    {
                        "metadata": {
                            "name": item.get("name"),
                            "namespace": item.get("namespace"),
                        },
                        "kind": item.get("kind"),
                        "spec": {},
                        "status": {"phase": item.get("status")},
                    }
                )
                continue
            out.append(item)
        return {"items": out}

    @classmethod
    def _extract_json_text(cls, payload: Dict[str, Any]) -> Any:
        text = payload.get("text", "") if isinstance(payload, dict) else ""
        if not isinstance(text, str):
            return {}
        parsed: Any = None
        try:
            parsed = json.loads(text)
        except Exception:  # noqa: BLE001
            try:
                parsed = yaml.safe_load(text)
            except Exception:  # noqa: BLE001
                return {}
        if parsed is None:
            return {}
        return cls._coerce_kubectl_list_json(parsed)

    @staticmethod
    def _kubectl_response_failed(resp: Dict[str, Any]) -> bool:
        text = resp.get("text", "") if isinstance(resp, dict) else ""
        if not isinstance(text, str) or not text.strip():
            return True
        obj: Any = None
        try:
            obj = json.loads(text)
        except Exception:  # noqa: BLE001
            try:
                obj = yaml.safe_load(text)
            except Exception:  # noqa: BLE001
                return True
        if isinstance(obj, dict) and "error" in obj and "items" not in obj:
            return True
        return False

    async def _list_workloads(
        self,
        service_name: str,
        namespace: str = "default",
        include_pods: bool = False,
    ) -> Dict[str, Any]:
        workloads: List[Dict[str, Any]] = []
        items: List[Any] = []
        pod_items: List[Dict[str, Any]] = []

        if self._backend == "containers":
            resps = await asyncio.gather(
                self._mcp_tools_call(
                    "resources_list",
                    {"apiVersion": "apps/v1", "kind": "Deployment", "namespace": namespace},
                ),
                self._mcp_tools_call(
                    "resources_list",
                    {"apiVersion": "apps/v1", "kind": "StatefulSet", "namespace": namespace},
                ),
            )
            for resp in resps:
                if self._kubectl_response_failed(resp):
                    continue
                parsed = self._extract_json_text(resp)
                if isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
                    items.extend(parsed["items"])
            if include_pods:
                pod_resp = await self._mcp_tools_call(
                    "resources_list",
                    {"apiVersion": "v1", "kind": "Pod", "namespace": namespace},
                )
                if not self._kubectl_response_failed(pod_resp):
                    pod_parsed = self._extract_json_text(pod_resp)
                    pod_items = pod_parsed.get("items", []) if isinstance(pod_parsed, dict) else []
        else:
            resp = await self._mcp_tools_call(
                "kubectl_get",
                {
                    "resourceType": "deployment,statefulset",
                    "namespace": namespace,
                    "output": "json",
                },
            )
            if self._kubectl_response_failed(resp):
                logger.warning(
                    "kubernetes_list_workloads: deploy/sts kubectl_get failed, retrying deployments only",
                    extra={"namespace": namespace},
                )
                resp = await self._mcp_tools_call(
                    "kubectl_get",
                    {"resourceType": "deployments", "namespace": namespace, "output": "json"},
                )
            parsed = self._extract_json_text(resp)
            items = parsed.get("items", []) if isinstance(parsed, dict) else []
            if include_pods:
                pod_resp = await self._mcp_tools_call(
                    "kubectl_get",
                    {"resourceType": "pods", "namespace": namespace, "output": "json"},
                )
                if not self._kubectl_response_failed(pod_resp):
                    pod_parsed = self._extract_json_text(pod_resp)
                    pod_items = pod_parsed.get("items", []) if isinstance(pod_parsed, dict) else []
        for item in items[:200]:
            if not isinstance(item, dict):
                continue
            meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            name = str(meta.get("name", ""))
            if service_name and service_name not in name:
                continue
            kind = str(item.get("kind", "") or "")
            if kind not in ("Deployment", "StatefulSet", "Pod"):
                continue
            workloads.append(
                {
                    "kind": kind,
                    "name": name,
                    "namespace": meta.get("namespace"),
                    "containers": self._extract_workload_containers(item),
                }
            )
        for item in pod_items[:200]:
            if not isinstance(item, dict):
                continue
            meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            name = str(meta.get("name", ""))
            if service_name and service_name not in name:
                continue
            kind = str(item.get("kind", "") or "")
            if kind != "Pod":
                continue
            workloads.append(
                {
                    "kind": kind,
                    "name": name,
                    "namespace": meta.get("namespace"),
                    "containers": self._extract_workload_containers(item),
                }
            )
        return {
            "type": "text",
            "text": json.dumps(
                {
                    "provider": "kubernetes",
                    "service_name": service_name,
                    "namespace": namespace,
                    "workloads": workloads[:80],
                },
                ensure_ascii=True,
            ),
        }

    @staticmethod
    def _extract_workload_containers(item: Dict[str, Any]) -> List[Dict[str, Any]]:
        spec = item.get("spec") if isinstance(item.get("spec"), dict) else {}
        template = spec.get("template") if isinstance(spec.get("template"), dict) else {}
        pod_spec = template.get("spec") if isinstance(template.get("spec"), dict) else {}
        containers = pod_spec.get("containers") if isinstance(pod_spec.get("containers"), list) else []
        out = []
        for c in containers[:20]:
            if not isinstance(c, dict):
                continue
            resources = c.get("resources") if isinstance(c.get("resources"), dict) else {}
            out.append(
                {
                    "name": c.get("name"),
                    "requests": resources.get("requests", {}) if isinstance(resources.get("requests"), dict) else {},
                    "limits": resources.get("limits", {}) if isinstance(resources.get("limits"), dict) else {},
                }
            )
        return out

    async def _get_pod_logs(
        self,
        service_name: str = "",
        pod_name: str = "",
        namespace: str = "default",
        tail_lines: int = 200,
    ) -> Dict[str, Any]:
        pod_candidates: List[str] = []
        if pod_name:
            pod_candidates.append(pod_name)
        else:
            pods_resp = await self._call_upstream_tool(
                "pods_list_in_namespace",
                {"namespace": namespace},
            )
            parsed = self._extract_json_text(pods_resp)
            for item in parsed.get("items", [])[:200] if isinstance(parsed, dict) else []:
                if not isinstance(item, dict):
                    continue
                meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
                name = str(meta.get("name", ""))
                if service_name and service_name in name:
                    pod_candidates.append(name)

        out_logs: List[Dict[str, Any]] = []
        candidates = pod_candidates[:3]
        if candidates:
            log_resps = await asyncio.gather(
                *[
                    self._call_upstream_tool(
                        "pods_log",
                        {"name": c, "namespace": namespace, "tail": int(tail_lines)},
                    )
                    for c in candidates
                ]
            )
            for candidate, log_resp in zip(candidates, log_resps):
                parsed = self._extract_json_text(log_resp)
                content = parsed.get("logs") if isinstance(parsed, dict) else None
                if not content and isinstance(log_resp, dict):
                    content = log_resp.get("text", "")
                out_logs.append({"pod_name": candidate, "message": str(content)[:4000]})

        return {
            "type": "text",
            "text": json.dumps(
                {
                    "provider": "kubernetes",
                    "service_name": service_name,
                    "namespace": namespace,
                    "logs": out_logs,
                },
                ensure_ascii=True,
            ),
        }

    def _init_local_k8s_write_tools(self) -> None:
        """Register exec + rollout restart using in-process kube client (RBAC permitting)."""
        try:
            from kubernetes import client, config
            from kubernetes.config.config_exception import ConfigException
        except ImportError as exc:
            logger.warning(
                "Kubernetes local write tools skipped: kubernetes package missing",
                extra={"error": str(exc)},
            )
            return

        kube_path = (getattr(settings, "KUBERNETES_MCP_LOCAL_KUBECONFIG_PATH", "") or "").strip()
        if not kube_path:
            kube_path = (getattr(settings, "ISTIO_MCP_KUBECONFIG_PATH", "") or "").strip()
        kube_path = kube_path or None
        ctx = (getattr(settings, "KUBERNETES_MCP_LOCAL_CONTEXT", "") or "").strip() or None

        try:
            if getattr(settings, "KUBERNETES_MCP_LOCAL_IN_CLUSTER", False):
                config.load_incluster_config()
            else:
                config.load_kube_config(config_file=kube_path, context=ctx)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Kubernetes local write tools: kubeconfig load failed",
                extra={"error": str(exc)},
            )
            return

        self._local_core_v1 = client.CoreV1Api()
        self._local_apps_v1 = client.AppsV1Api()

        self.register_tool(
            name="kubernetes_exec_in_pod",
            description=(
                "Execute a command inside a pod (non-interactive). "
                "Use argv array, e.g. [\"/bin/sh\",\"-c\",\"nslookup example.com\"]."
            ),
            handler=self._kubernetes_exec_in_pod,
            input_schema={
                "type": "object",
                "properties": {
                    "namespace": {"type": "string"},
                    "pod_name": {"type": "string"},
                    "container": {"type": "string", "description": "Optional container name"},
                    "command": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Argv only (invoke /bin/sh -c for shell features)",
                    },
                },
                "required": ["namespace", "pod_name", "command"],
            },
        )
        self.register_tool(
            name="kubernetes_rollout_restart_deployment",
            description="Restart a Deployment via kubectl-style restartedAt annotation.",
            handler=self._kubernetes_rollout_restart_deployment,
            input_schema={
                "type": "object",
                "properties": {
                    "namespace": {"type": "string"},
                    "deployment_name": {"type": "string"},
                },
                "required": ["namespace", "deployment_name"],
            },
        )
        logger.info("Kubernetes local write tools registered (exec, rollout restart)")

    async def _kubernetes_exec_in_pod(
        self,
        namespace: str,
        pod_name: str,
        command: List[str],
        container: str = "",
    ) -> Dict[str, Any]:
        if not self._local_core_v1:
            return {
                "type": "text",
                "text": json.dumps({"provider": "kubernetes", "error": "local_write_client_not_initialized"}),
            }
        from kubernetes.stream import stream

        def _run() -> str:
            return stream(
                self._local_core_v1.connect_get_namespaced_pod_exec,
                pod_name,
                namespace,
                command=command,
                container=container or None,
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )

        try:
            out = await asyncio.to_thread(_run)
        except Exception as exc:  # noqa: BLE001
            return {
                "type": "text",
                "text": json.dumps({"provider": "kubernetes", "error": str(exc)}),
            }
        return {
            "type": "text",
            "text": json.dumps(
                {
                    "provider": "kubernetes",
                    "pod": pod_name,
                    "namespace": namespace,
                    "output": str(out)[:12000],
                },
                ensure_ascii=True,
            ),
        }

    async def _kubernetes_rollout_restart_deployment(
        self,
        namespace: str,
        deployment_name: str,
    ) -> Dict[str, Any]:
        if not self._local_apps_v1:
            return {
                "type": "text",
                "text": json.dumps({"provider": "kubernetes", "error": "local_write_client_not_initialized"}),
            }
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        body: Dict[str, Any] = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": now,
                        }
                    }
                }
            }
        }

        def _patch() -> Any:
            return self._local_apps_v1.patch_namespaced_deployment(
                name=deployment_name,
                namespace=namespace,
                body=body,
            )

        try:
            dep = await asyncio.to_thread(_patch)
            meta = dep.metadata if dep and dep.metadata else None
            return {
                "type": "text",
                "text": json.dumps(
                    {
                        "provider": "kubernetes",
                        "deployment": deployment_name,
                        "namespace": namespace,
                        "restartedAt": now,
                        "resourceVersion": getattr(meta, "resource_version", None),
                    },
                    default=str,
                    ensure_ascii=True,
                ),
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "type": "text",
                "text": json.dumps({"provider": "kubernetes", "error": str(exc)}),
            }

    async def _get_service_runtime_context(self, service_name: str, namespace: str = "default") -> Dict[str, Any]:
        pods_resp = await self._call_upstream_tool(
            "pods_list_in_namespace",
            {"namespace": namespace},
        )
        parsed = self._extract_json_text(pods_resp)
        pods = []
        for item in parsed.get("items", [])[:300] if isinstance(parsed, dict) else []:
            if not isinstance(item, dict):
                continue
            meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            spec = item.get("spec") if isinstance(item.get("spec"), dict) else {}
            status = item.get("status") if isinstance(item.get("status"), dict) else {}
            name = str(meta.get("name", ""))
            if service_name not in name:
                continue
            pods.append(
                {
                    "name": name,
                    "namespace": meta.get("namespace"),
                    "node_name": spec.get("nodeName"),
                    "pod_ip": status.get("podIP"),
                    "phase": status.get("phase"),
                }
            )
        return {
            "type": "text",
            "text": json.dumps(
                {
                    "provider": "kubernetes",
                    "service_name": service_name,
                    "namespace": namespace,
                    "pods": pods[:80],
                },
                ensure_ascii=True,
            ),
        }

    async def cleanup(self) -> None:
        if self._http_client:
            await self._http_client.aclose()
        self._local_core_v1 = None
        self._local_apps_v1 = None