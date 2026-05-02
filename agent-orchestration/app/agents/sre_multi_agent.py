"""LangGraph-based multi-agent SRE incident workflow."""

from __future__ import annotations

import json
import logging
import re
import shlex
import uuid
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional, Tuple, TypedDict
from pathlib import Path

import httpx
import yaml
from langgraph.graph import END, StateGraph

from app.agents.telemetry_agent import telemetry_agent
from app.core.config import settings
from app.core.redis_client import redis_client
from app.services.llm_client import llm_client
from app.services.rag_client import rag_client
from app.services.snow_service import snow_service
from app.services.vm_executor import vm_executor
from app.services.context_graph_service import context_graph_service
from app.services.mcp_client import mcp_client
from app.services.prompt_catalog_service import PromptCatalogService

logger = logging.getLogger(__name__)

# GitHub Search API rejects invalid or overlong `q` with HTTP 422 (max 256 chars for the whole query).
_GITHUB_ISSUE_SEARCH_SUFFIX = " in:title,body"
_GITHUB_ISSUE_SEARCH_MAX_Q_LEN = 256
_VENDOR_DOC_URLS: Dict[str, str] = {
    "kubernetes": "https://kubernetes.io/docs/tasks/debug/debug-application/",
    "istio": "https://istio.io/latest/docs/ops/common-problems/network-issues/",
    "nginx": "https://kubernetes.github.io/ingress-nginx/troubleshooting/",
    "prometheus": "https://prometheus.io/docs/prometheus/latest/querying/basics/",
}
_CLOUD_STATUS_URLS: Dict[str, str] = {
    "aws": "https://status.aws.amazon.com/",
    "azure": "https://status.azure.com/",
    "gcp": "https://status.cloud.google.com/",
}
_CLOUD_STATUS_FEEDS: Dict[str, str] = {
    "aws": "https://status.aws.amazon.com/rss/all.rss",
    "azure": "https://status.azure.com/en-us/status/feed/",
    "gcp": "https://status.cloud.google.com/incidents.json",
}
_DNS_FAILURE_LOG_TOKENS = (
    "unknownhostexception",
    "no such host",
    "temporary failure in name resolution",
    "nxdomain",
)
_INVESTIGATION_TEXT_TOKENS = (
    "investigate",
    "verify",
    "check ",
    "diagnos",
    "nslookup",
    "dig ",
    "kubectl describe",
    "kubectl logs",
    "kubectl get events",
)
_RUNTIME_FAILURE_LOG_TOKENS = (
    "application run failed",
    "beancreationexception",
    "expression parsing failed",
    "exception encountered during context initialization",
    "failed to start",
    "startup failed",
)
_DEPENDENCY_SUCCESS_LOG_TOKENS = (
    "successfully connected",
    "monitor thread successfully connected",
    "connected to server with description",
    "connection established",
    "connected successfully",
    "adding discovered server",
)
_RUNTIME_FAILURE_REGEXES = (
    r"\b[a-z0-9_.]*exception\b",
    r"\bapplication run failed\b",
    r"\bfailed to start\b",
    r"\bstartup failed\b",
    r"\bcontext initialization\b",
    r"\btraceback\b",
    r"\bpanic:\b",
    r"\bsegmentation fault\b",
)
_MISSING_CONFIG_SIGNAL_TOKENS = (
    "must be set",
    "not set",
    "is required",
    "required",
    "missing",
    "could not resolve placeholder",
    "failed to bind properties",
)
_SENSITIVE_CONFIG_TOKENS = (
    "api key",
    "apikey",
    "token",
    "secret",
    "credential",
    "password",
    "access key",
    "client secret",
)


def _extract_json_blob(text: str) -> Optional[str]:
    """Pull a JSON object from model output (markdown fence or first `{` … last `}`)."""
    if not text or not text.strip():
        return None
    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", text)
    if fenced:
        return fenced.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


class SREMultiAgentState(TypedDict, total=False):
    """Typed state propagated across SRE multi-agent workflow."""

    incident_id: str
    user_id: str
    title: str
    description: str
    target_service: str
    environment: str
    cloud_providers: List[str]
    resource_types: List[str]
    regions: List[str]
    cloud_probe_plan: Dict[str, Any]
    servicenow_incident_id: Optional[str]
    operation_status: str
    current_node: str
    error: Optional[str]
    created_at: str
    updated_at: str

    # Context aggregation payload
    logs: List[Dict[str, Any]]
    metrics: Dict[str, Any]
    alerts: List[Dict[str, Any]]
    rag_results: Dict[str, Any]
    graph_context: List[Dict[str, Any]]
    servicenow_history: List[Dict[str, Any]]
    context_summary: str
    context_sources: Dict[str, Any]
    istio_context: Dict[str, Any]
    extracted_dependencies: List[Dict[str, Any]]
    metric_anomalies: List[Dict[str, Any]]
    additional_context: Dict[str, Any]
    observability_missing_signals: List[str]
    mcp_sources_contributed: List[str]

    # RCA and reasoning
    failing_service: str
    hypothesis: str
    evidence: List[str]
    anomalies: List[str]
    critique_feedback: str
    alternate_causes: List[str]
    root_cause: str
    root_cause_category: str
    is_terminal: bool
    requires_more_data: bool
    rca_confidence: float
    terminal_evidence: List[str]
    terminal_dependency: Optional[str]
    llm_terminal_candidate: bool

    # Confidence
    confidence_components: Dict[str, Any]
    confidence_score: float

    # Fallback + planning
    web_findings: List[Dict[str, Any]]
    remediation_plan: Dict[str, Any]
    graph_remediation_facts: Dict[str, Any]
    remediation_iteration: int
    max_remediation_iterations: int
    web_search_iterations: int
    vendors: List[str]
    clouds: List[str]
    region: str

    # Approval + execution
    approval_id: Optional[str]
    approved: Optional[bool]
    approval_comment: Optional[str]
    approval_requested_at: Optional[str]
    execution_results: List[Dict[str, Any]]
    manual_fallback: Optional[Dict[str, Any]]

    # Post actions
    servicenow_update: Dict[str, Any]
    context_graph_update: Dict[str, Any]
    prompt_versions: Dict[str, str]
    mcp_contract_hits: List[Dict[str, Any]]
    events: List[Dict[str, Any]]
    last_event_seq: int


class SREMultiAgent:
    """Production-grade autonomous SRE workflow with LangGraph orchestration."""

    MCP_CONTEXT_CONTRACTS: Dict[str, List[Dict[str, Any]]] = {
        "logs": [
            {
                "provider": "quickwit",
                "server": "quickwit-server",
                "tool": "fetch_service_error_logs",
            },
            {
                "provider": "quickwit",
                "server": "quickwit-server",
                "tool": "fetch_service_logs",
            },
            {
                "provider": "elasticsearch",
                "server": "elasticsearch-server",
                "tool": "elasticsearch_fetch_service_logs",
            },
            {
                "provider": "newrelic",
                "server": "newrelic-mcp",
                "tool": "newrelic_query_logs",
            },
        ],
        "metrics": [
            {
                "provider": "prometheus",
                "server": "prometheus-server",
                "tool": "prometheus_execute_range_query",
            },
            {
                "provider": "newrelic",
                "server": "newrelic-mcp",
                "tool": "newrelic_nrql_query",
            },
        ],
        "alerts": [
            {
                "provider": "alertmanager",
                "server": "alertmanager-mcp",
                "tool": "alertmanager_get_alerts",
            },
            {
                "provider": "newrelic",
                "server": "newrelic-mcp",
                "tool": "newrelic_list_alert_violations",
            },
        ],
        "incident_history": [
            {
                "provider": "servicenow",
                "server": "servicenow-mcp",
                "tool": "servicenow_search_incidents",
            }
        ],
        "istio": [
            {
                "provider": "istio",
                "server": "istio-server",
                "tool": "istio_get_istio_resources_for_service",
            }
        ],
        "graph": [
            {
                "provider": "graph",
                "server": "graph-server",
                "tool": "graph_get_service_dependencies",
            },
            {
                "provider": "graph",
                "server": "graph-server",
                "tool": "graph_get_impacted_services",
            },
            {
                "provider": "graph",
                "server": "graph-server",
                "tool": "graph_get_recent_anomalies",
            },
            {
                "provider": "graph",
                "server": "graph-server",
                "tool": "graph_get_recent_incidents",
            },
            {
                "provider": "graph",
                "server": "graph-server",
                "tool": "graph_get_incident_root_cause",
            },
            {
                "provider": "graph",
                "server": "graph-server",
                "tool": "graph_list_services",
            },
            {
                "provider": "graph",
                "server": "graph-server",
                "tool": "graph_resolve_kubernetes_service",
            },
        ],
        "kubernetes": [
            {
                "provider": "kubernetes",
                "server": "kubernetes-mcp",
                "tool": "kubernetes_list_workloads",
            },
            {
                "provider": "kubernetes",
                "server": "kubernetes-mcp",
                "tool": "kubernetes_get_pod_logs",
            },
            {
                "provider": "kubernetes",
                "server": "kubernetes-mcp",
                "tool": "kubernetes_get_service_runtime_context",
            },
            {
                "provider": "kubernetes",
                "server": "kubernetes-mcp",
                "tool": "kubernetes_exec_in_pod",
            },
            {
                "provider": "kubernetes",
                "server": "kubernetes-mcp",
                "tool": "kubernetes_rollout_restart_deployment",
            },
        ],
        "aws": [
            {
                "provider": "aws",
                "server": "aws-mcp",
                "tool": "aws_list_load_balancers",
            },
            {
                "provider": "aws",
                "server": "aws-mcp",
                "tool": "aws_list_rds_instances",
            },
            {
                "provider": "aws",
                "server": "aws-mcp",
                "tool": "aws_list_elasticache_clusters",
            },
            {
                "provider": "aws",
                "server": "aws-mcp",
                "tool": "aws_list_ec2_instances",
            },
            {
                "provider": "aws",
                "server": "aws-mcp",
                "tool": "aws_list_s3_buckets",
            },
        ],
    }
    EVENT_HISTORY_LIMIT = 400

    def __init__(self) -> None:
        self.llm = llm_client
        self.telemetry = telemetry_agent
        self.rag = rag_client
        self.snow = snow_service
        self.mcp = mcp_client
        self.vm_executor = vm_executor
        self._state_ttl = settings.SRE_MULTI_STATE_TTL_SECONDS
        self._confidence_threshold = settings.SRE_CONFIDENCE_WEB_THRESHOLD
        self._mcp_context_contracts = self._load_capability_contracts()
        catalog_path = Path(settings.SRE_PROMPT_CATALOG_PATH)
        if not catalog_path.is_absolute():
            project_root = Path(__file__).resolve().parents[2]
            catalog_path = project_root / settings.SRE_PROMPT_CATALOG_PATH
        self.prompts = PromptCatalogService(str(catalog_path))
        self.workflow = self._build_workflow()
        self.post_approval_workflow = self._build_post_approval_workflow()

    def _load_capability_contracts(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Load SRE capability contracts from repo YAML with in-code fallback.

        YAML shape:
        contracts:
          logs: [{provider, server, tool}, ...]
          ...
        """
        default_contracts = self.MCP_CONTEXT_CONTRACTS
        path = Path(settings.SRE_CAPABILITY_CONTRACTS_PATH)
        if not path.is_absolute():
            project_root = Path(__file__).resolve().parents[2]
            path = project_root / settings.SRE_CAPABILITY_CONTRACTS_PATH
        if not path.exists():
            logger.warning("SRE capability contracts file not found: %s. Using in-code defaults.", path)
            return default_contracts
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = yaml.safe_load(handle) or {}
            contracts = payload.get("contracts", {})
            if not isinstance(contracts, dict):
                logger.warning("Invalid contracts payload in %s. Using in-code defaults.", path)
                return default_contracts
            merged: Dict[str, List[Dict[str, Any]]] = {}
            for key, fallback in default_contracts.items():
                raw = contracts.get(key, fallback)
                merged[key] = raw if isinstance(raw, list) else fallback
            # Allow optional extra group for generic provider/resource contracts.
            cloud_provider_contracts = contracts.get("cloud_provider_contracts", [])
            merged["cloud_provider_contracts"] = (
                cloud_provider_contracts if isinstance(cloud_provider_contracts, list) else []
            )
            logger.info("Loaded SRE capability contracts from %s", path)
            return merged
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed loading SRE capability contracts (%s). Using in-code defaults.", exc)
            return default_contracts

    def _build_workflow(self):
        graph = StateGraph(SREMultiAgentState)
        graph.add_node("incident_trigger", self._with_node_events("incident_trigger", self._incident_trigger_node))
        graph.add_node("context_aggregation", self._with_node_events("context_aggregation", self._context_aggregation_node))
        graph.add_node("rca_agent", self._with_node_events("rca_agent", self._rca_agent_node))
        graph.add_node("critique_agent", self._with_node_events("critique_agent", self._critique_agent_node))
        graph.add_node("confidence_scoring", self._with_node_events("confidence_scoring", self._confidence_scoring_node))
        graph.add_node("web_search_agent", self._with_node_events("web_search_agent", self._web_search_agent_node))
        graph.add_node(
            "additional_context_aggregation",
            self._with_node_events("additional_context_aggregation", self._additional_context_aggregation_node),
        )
        graph.add_node("rca_agent_recompute", self._with_node_events("rca_agent_recompute", self._rca_agent_recompute_node))
        graph.add_node("remediation_plan", self._with_node_events("remediation_plan", self._remediation_plan_node))
        graph.add_node("human_approval", self._with_node_events("human_approval", self._human_approval_node))
        graph.add_node("await_approval", self._with_node_events("await_approval", self._await_approval_node))
        graph.add_node("remediation_execution", self._with_node_events("remediation_execution", self._remediation_execution_node))
        graph.add_node(
            "manual_remediation_fallback",
            self._with_node_events("manual_remediation_fallback", self._manual_remediation_fallback_node),
        )
        graph.add_node("servicenow_update", self._with_node_events("servicenow_update", self._servicenow_update_node))
        graph.add_node("context_graph_update", self._with_node_events("context_graph_update", self._context_graph_update_node))

        graph.set_entry_point("incident_trigger")
        graph.add_edge("incident_trigger", "context_aggregation")
        graph.add_edge("context_aggregation", "rca_agent")
        graph.add_edge("rca_agent", "critique_agent")
        graph.add_edge("critique_agent", "confidence_scoring")
        graph.add_conditional_edges(
            "confidence_scoring",
            self._route_after_confidence,
            {"web_search_agent": "web_search_agent", "remediation_plan": "remediation_plan"},
        )
        graph.add_edge("web_search_agent", "rca_agent_recompute")
        graph.add_edge("rca_agent_recompute", "remediation_plan")
        graph.add_conditional_edges(
            "remediation_plan",
            self._route_after_remediation_plan,
            {"additional_context_aggregation": "additional_context_aggregation", "human_approval": "human_approval"},
        )
        graph.add_edge("additional_context_aggregation", "rca_agent")
        graph.add_conditional_edges(
            "human_approval",
            self._route_after_human_approval,
            {
                "await_approval": "await_approval",
                "remediation_execution": "remediation_execution",
                "manual_remediation_fallback": "manual_remediation_fallback",
            },
        )
        graph.add_edge("await_approval", END)
        graph.add_conditional_edges(
            "remediation_execution",
            self._route_after_execution,
            {"servicenow_update": "servicenow_update", "manual_remediation_fallback": "manual_remediation_fallback"},
        )
        graph.add_edge("manual_remediation_fallback", "servicenow_update")
        graph.add_edge("servicenow_update", "context_graph_update")
        graph.add_edge("context_graph_update", END)
        return graph.compile()

    def _build_post_approval_workflow(self):
        graph = StateGraph(SREMultiAgentState)
        graph.add_node("remediation_execution", self._with_node_events("remediation_execution", self._remediation_execution_node))
        graph.add_node(
            "manual_remediation_fallback",
            self._with_node_events("manual_remediation_fallback", self._manual_remediation_fallback_node),
        )
        graph.add_node("servicenow_update", self._with_node_events("servicenow_update", self._servicenow_update_node))
        graph.add_node("context_graph_update", self._with_node_events("context_graph_update", self._context_graph_update_node))

        graph.set_entry_point("remediation_execution")
        graph.add_conditional_edges(
            "remediation_execution",
            self._route_after_execution,
            {"servicenow_update": "servicenow_update", "manual_remediation_fallback": "manual_remediation_fallback"},
        )
        graph.add_edge("manual_remediation_fallback", "servicenow_update")
        graph.add_edge("servicenow_update", "context_graph_update")
        graph.add_edge("context_graph_update", END)
        return graph.compile()

    def _state_key(self, incident_id: str) -> str:
        return f"sre_multi_agent:incident:{incident_id}"

    def _langgraph_run_config(self, incident_id: str, workflow_name: str) -> Dict[str, Any]:
        """RunnableConfig for LangSmith: tags and metadata on the root graph run."""
        return {
            "run_name": f"{workflow_name}:{incident_id}",
            "metadata": {"incident_id": incident_id, "workflow": workflow_name},
            "tags": ["sre_multi_agent", workflow_name],
        }

    async def _emit_event(
        self,
        state: SREMultiAgentState,
        *,
        event_type: str,
        message: str,
        node: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        chat_visible: bool = True,
        persist: bool = True,
    ) -> None:
        events = state.get("events")
        if not isinstance(events, list):
            events = []
            state["events"] = events
        last_seq_raw = state.get("last_event_seq", 0)
        try:
            last_seq = int(last_seq_raw)
        except (TypeError, ValueError):
            last_seq = len(events)
        seq = last_seq + 1
        event = {
            "seq": seq,
            "timestamp": datetime.utcnow().isoformat(),
            "incident_id": state.get("incident_id"),
            "type": event_type,
            "node": node or state.get("current_node"),
            "message": message,
            "chat_visible": bool(chat_visible),
            "data": data or {},
        }
        events.append(event)
        if len(events) > self.EVENT_HISTORY_LIMIT:
            state["events"] = events[-self.EVENT_HISTORY_LIMIT :]
        state["last_event_seq"] = seq
        if persist:
            await self._persist_state(state)

    def _node_display_name(self, node_name: str) -> str:
        return node_name.replace("_", " ")

    def _node_end_message(self, node_name: str, state: SREMultiAgentState) -> str:
        if node_name == "context_aggregation":
            return (
                f"Context aggregated: logs={len(state.get('logs', []))}, "
                f"alerts={len(state.get('alerts', []))}, anomalies={len(state.get('metric_anomalies', []))}."
            )
        if node_name in {"rca_agent", "rca_agent_recompute"}:
            return f"Hypothesis updated: {state.get('hypothesis') or 'insufficient evidence'}."
        if node_name == "confidence_scoring":
            return f"Confidence scored at {state.get('confidence_score', 0.0)}."
        if node_name == "web_search_agent":
            return f"External findings collected: {len(state.get('web_findings', []))}."
        if node_name == "remediation_plan":
            commands = state.get("remediation_plan", {}).get("step_by_step_commands", [])
            return f"Remediation plan prepared with {len(commands) if isinstance(commands, list) else 0} commands."
        if node_name == "remediation_execution":
            results = state.get("execution_results", [])
            success = len([r for r in results if isinstance(r, dict) and r.get("status") == "success"])
            return f"Remediation execution complete ({success}/{len(results)} successful)."
        if node_name == "human_approval" and state.get("operation_status") == "waiting_approval":
            return "Waiting for human approval before executing remediation."
        return f"Completed {self._node_display_name(node_name)}."

    def _with_node_events(
        self,
        node_name: str,
        node_fn: Callable[[SREMultiAgentState], Awaitable[SREMultiAgentState]],
    ) -> Callable[[SREMultiAgentState], Awaitable[SREMultiAgentState]]:
        async def _wrapped(state: SREMultiAgentState) -> SREMultiAgentState:
            await self._emit_event(
                state,
                event_type="node_start",
                node=node_name,
                message=f"Starting {self._node_display_name(node_name)}.",
            )
            try:
                result = await node_fn(state)
            except Exception as exc:
                await self._emit_event(
                    state,
                    event_type="node_error",
                    node=node_name,
                    message=f"{self._node_display_name(node_name)} failed: {exc}",
                    data={"error": str(exc)},
                )
                raise
            await self._emit_event(
                result,
                event_type="node_end",
                node=node_name,
                message=self._node_end_message(node_name, result),
            )
            return result

        return _wrapped

    async def _persist_state(self, state: SREMultiAgentState) -> None:
        state["updated_at"] = datetime.utcnow().isoformat()
        await redis_client.client.setex(
            self._state_key(state["incident_id"]),
            self._state_ttl,
            json.dumps(state, default=str),
        )

    async def _load_state(self, incident_id: str) -> Optional[SREMultiAgentState]:
        payload = await redis_client.client.get(self._state_key(incident_id))
        if not payload:
            return None
        return json.loads(payload)

    @staticmethod
    def _normalize_label_list(values: Any) -> List[str]:
        if isinstance(values, str):
            raw = values.strip()
            if not raw:
                return []
            if raw.startswith("["):
                try:
                    parsed = json.loads(raw)
                    values = parsed if isinstance(parsed, list) else []
                except json.JSONDecodeError:
                    values = [p.strip() for p in raw.split(",") if p.strip()]
            else:
                values = [p.strip() for p in raw.split(",") if p.strip()]
        if not isinstance(values, list):
            return []
        out: List[str] = []
        for value in values:
            if not isinstance(value, str):
                continue
            cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower()).strip("-")
            if cleaned and cleaned not in out:
                out.append(cleaned)
        return out

    def _default_web_search_scope(self) -> Tuple[List[str], List[str], str]:
        vendors = self._normalize_label_list(settings.SRE_WEB_SEARCH_DEFAULT_VENDORS)
        clouds = self._normalize_label_list(settings.SRE_WEB_SEARCH_DEFAULT_CLOUDS)
        region = str(settings.SRE_WEB_SEARCH_DEFAULT_REGION or settings.AWS_REGION or "").strip()
        return vendors, clouds, region

    def _allowed_incident_environments(self) -> List[str]:
        return self._normalize_label_list(settings.SRE_ALLOWED_ENVIRONMENTS) or ["dev", "staging", "prod"]

    def _resolve_incident_scope(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        allowed_envs = self._allowed_incident_environments()
        environment = str(
            payload.get("environment")
            or settings.SRE_DEFAULT_INCIDENT_ENVIRONMENT
            or ""
        ).strip().lower()
        if not environment:
            raise ValueError(
                "Missing incident environment. Provide 'environment' in request or configure "
                "SRE_DEFAULT_INCIDENT_ENVIRONMENT."
            )
        if environment not in allowed_envs:
            raise ValueError(
                f"Invalid incident environment '{environment}'. Allowed values from "
                f"SRE_ALLOWED_ENVIRONMENTS: {', '.join(allowed_envs)}."
            )

        cloud_providers = self._normalize_label_list(payload.get("cloud_providers"))
        if not cloud_providers:
            cloud_providers = self._normalize_label_list(payload.get("clouds"))
        if not cloud_providers:
            cloud_providers = self._normalize_label_list(settings.SRE_DEFAULT_CLOUD_PROVIDERS)
        if not cloud_providers:
            raise ValueError(
                "Missing cloud providers. Provide 'cloud_providers' in request or configure "
                "SRE_DEFAULT_CLOUD_PROVIDERS."
            )

        resource_types = self._normalize_label_list(payload.get("resource_types"))
        if not resource_types:
            resource_types = self._normalize_label_list(settings.SRE_DEFAULT_RESOURCE_TYPES)
        if not resource_types:
            raise ValueError(
                "Missing resource types. Provide 'resource_types' in request or configure "
                "SRE_DEFAULT_RESOURCE_TYPES."
            )

        regions = self._normalize_label_list(payload.get("regions"))
        if not regions:
            regions = self._normalize_label_list(payload.get("region"))
        if not regions:
            regions = self._normalize_label_list(settings.SRE_DEFAULT_REGIONS)

        return {
            "environment": environment,
            "cloud_providers": cloud_providers,
            "resource_types": resource_types,
            "regions": regions,
        }

    async def create_incident(self, payload: Dict[str, Any]) -> SREMultiAgentState:
        incident_id = f"inc_{uuid.uuid4().hex[:10]}"
        resolved_scope = self._resolve_incident_scope(payload)
        default_vendors, default_clouds, default_region = self._default_web_search_scope()
        vendors = self._normalize_label_list(payload.get("vendors")) or default_vendors
        clouds = self._normalize_label_list(payload.get("clouds")) or resolved_scope["cloud_providers"] or default_clouds
        region = str(payload.get("region") or default_region).strip()
        if not region and resolved_scope["regions"]:
            region = resolved_scope["regions"][0]
        initial_state: SREMultiAgentState = {
            "incident_id": incident_id,
            "user_id": payload.get("user_id", "unknown-user"),
            "title": payload.get("title", "Incident"),
            "description": payload.get("description", ""),
            "target_service": payload.get("target_service", "unknown-service"),
            "environment": resolved_scope["environment"],
            "cloud_providers": resolved_scope["cloud_providers"],
            "resource_types": resolved_scope["resource_types"],
            "regions": resolved_scope["regions"],
            "cloud_probe_plan": {},
            "vendors": vendors,
            "clouds": clouds,
            "region": region,
            "servicenow_incident_id": payload.get("servicenow_incident_id"),
            "operation_status": "queued",
            "current_node": "incident_trigger",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "approved": payload.get("auto_approve", None),
            "approval_comment": None,
            "approval_id": None,
            "execution_results": [],
            "remediation_iteration": 0,
            "max_remediation_iterations": 2,
            "web_search_iterations": 0,
            "is_terminal": False,
            "requires_more_data": True,
            "root_cause": "",
            "root_cause_category": "unknown",
            "terminal_evidence": [],
            "terminal_dependency": None,
            "llm_terminal_candidate": False,
            "prompt_versions": {},
            "mcp_contract_hits": [],
            "events": [],
            "last_event_seq": 0,
        }
        await self._emit_event(
            initial_state,
            event_type="workflow_queued",
            node="incident_trigger",
            message="Incident queued for SRE workflow execution.",
            data={
                "title": initial_state.get("title"),
                "target_service": initial_state.get("target_service"),
                "environment": initial_state.get("environment"),
                "cloud_providers": initial_state.get("cloud_providers"),
                "resource_types": initial_state.get("resource_types"),
            },
            persist=False,
        )
        await self._persist_state(initial_state)
        return initial_state

    async def run_incident_workflow(self, incident_id: str) -> SREMultiAgentState:
        state = await self._load_state(incident_id)
        if not state:
            raise ValueError(f"Incident not found: {incident_id}")

        state["operation_status"] = "running"
        await self._emit_event(
            state,
            event_type="workflow_started",
            node=state.get("current_node"),
            message="SRE workflow started.",
            data={"workflow": "sre_main_workflow"},
            persist=False,
        )
        await self._persist_state(state)

        try:
            final_state = await self.workflow.ainvoke(
                state,
                config=self._langgraph_run_config(incident_id, "sre_main_workflow"),
            )
            if final_state.get("operation_status") != "waiting_approval":
                final_state["operation_status"] = "completed"
                await self._emit_event(
                    final_state,
                    event_type="workflow_completed",
                    node=final_state.get("current_node"),
                    message="SRE workflow completed.",
                    data={"status": final_state.get("operation_status")},
                    persist=False,
                )
            await self._persist_state(final_state)
            return final_state
        except Exception as exc:
            logger.exception("SRE multi-agent workflow failed: %s", exc)
            state["operation_status"] = "failed"
            state["error"] = str(exc)
            await self._emit_event(
                state,
                event_type="workflow_failed",
                node=state.get("current_node"),
                message=f"SRE workflow failed: {exc}",
                data={"error": str(exc)},
                persist=False,
            )
            await self._persist_state(state)
            return state

    async def approve_remediation(self, incident_id: str, approved: bool, comment: Optional[str]) -> SREMultiAgentState:
        state = await self._load_state(incident_id)
        if not state:
            raise ValueError(f"Incident not found: {incident_id}")

        state["approved"] = approved
        state["approval_comment"] = comment
        await self._emit_event(
            state,
            event_type="approval_decision",
            node="human_approval",
            message=f"Remediation {'approved' if approved else 'rejected'} by user.",
            data={"approved": approved, "comment": comment or ""},
            persist=False,
        )

        if not approved:
            state = await self._manual_remediation_fallback_node(state)
            state = await self._servicenow_update_node(state)
            state = await self._context_graph_update_node(state)
            state["operation_status"] = "completed"
            await self._emit_event(
                state,
                event_type="workflow_completed",
                node=state.get("current_node"),
                message="Workflow completed with manual remediation fallback.",
                persist=False,
            )
            await self._persist_state(state)
            return state

        state["operation_status"] = "running"
        await self._persist_state(state)
        final_state = await self.post_approval_workflow.ainvoke(
            state,
            config=self._langgraph_run_config(incident_id, "sre_post_approval_workflow"),
        )
        final_state["operation_status"] = "completed"
        await self._emit_event(
            final_state,
            event_type="workflow_completed",
            node=final_state.get("current_node"),
            message="Post-approval remediation workflow completed.",
            persist=False,
        )
        await self._persist_state(final_state)
        return final_state

    async def get_incident_status(self, incident_id: str) -> Optional[Dict[str, Any]]:
        state = await self._load_state(incident_id)
        if not state:
            return None
        return {
            "incident_id": incident_id,
            "status": state.get("operation_status"),
            "current_node": state.get("current_node"),
            "confidence_score": state.get("confidence_score"),
            "approval_required": state.get("operation_status") == "waiting_approval",
            "approval_id": state.get("approval_id"),
            "failing_service": state.get("failing_service"),
            "hypothesis": state.get("hypothesis"),
            "root_cause": state.get("root_cause"),
            "rca_confidence": state.get("rca_confidence"),
            "root_cause_category": state.get("root_cause_category"),
            "is_terminal": state.get("is_terminal", False),
            "requires_more_data": state.get("requires_more_data", True),
            "terminal_evidence": state.get("terminal_evidence", []),
            "terminal_dependency": state.get("terminal_dependency"),
            "llm_terminal_candidate": state.get("llm_terminal_candidate", False),
            "remediation_plan": state.get("remediation_plan"),
            "approval_presentation": state.get("approval_presentation", {}),
            "execution_results": state.get("execution_results", []),
            "servicenow_update": state.get("servicenow_update", {}),
            "context_graph_update": state.get("context_graph_update", {}),
            "context_sources": state.get("context_sources", {}),
            "prompt_versions": state.get("prompt_versions", {}),
            "mcp_contract_hits": state.get("mcp_contract_hits", []),
            "last_event_seq": state.get("last_event_seq", 0),
            "error": state.get("error"),
            "updated_at": state.get("updated_at"),
        }

    async def get_incident_events(
        self,
        incident_id: str,
        *,
        after_seq: int = 0,
        limit: int = 100,
    ) -> Optional[Dict[str, Any]]:
        state = await self._load_state(incident_id)
        if not state:
            return None
        events = state.get("events", [])
        if not isinstance(events, list):
            events = []
        filtered = [event for event in events if int(event.get("seq", 0) or 0) > after_seq]
        selected = filtered[: max(1, min(limit, 500))]
        return {
            "incident_id": incident_id,
            "status": state.get("operation_status"),
            "current_node": state.get("current_node"),
            "last_event_seq": state.get("last_event_seq", 0),
            "events": selected,
            "has_more": len(filtered) > len(selected),
        }

    async def _incident_trigger_node(self, state: SREMultiAgentState) -> SREMultiAgentState:
        state["current_node"] = "incident_trigger"
        await self._persist_state(state)
        return state

    def reload_prompt_catalog(self) -> Dict[str, Any]:
        """Reload prompt catalog templates from disk."""
        return self.prompts.reload()

    @staticmethod
    def _record_prompt_version(state: SREMultiAgentState, prompt_key: str, version: str = "1.0.0") -> None:
        state.setdefault("prompt_versions", {})
        state["prompt_versions"][prompt_key] = version

    async def _context_aggregation_node(self, state: SREMultiAgentState) -> SREMultiAgentState:
        state["current_node"] = "context_aggregation"
        self._record_prompt_version(state, "context_aggregation_agent")

        description = state.get("description", "")
        target = state.get("target_service", "all")

        mcp_context = await self._collect_context_via_mcp(
            incident_id=state["incident_id"],
            target_service=target,
            description=description,
            environment=str(state.get("environment") or ""),
            cloud_providers=self._normalize_label_list(state.get("cloud_providers")),
            resource_types=self._normalize_label_list(state.get("resource_types")),
            regions=self._normalize_label_list(state.get("regions")),
        )

        logs = mcp_context.get("logs")
        if not logs:
            logs = await self.telemetry.collect_logs(target=target, time_range="1h")

        metrics = mcp_context.get("metrics")
        if not metrics:
            metrics = await self.telemetry.collect_metrics(target=target, time_range="1h")

        alerts = mcp_context.get("alerts", [])

        rag_results = await self.rag.search_knowledge_base(query=description, top_k=5, use_hybrid=True)
        graph_context = await context_graph_service.query_related_context(target, limit=5)
        snow_history = mcp_context.get("incident_history")
        if not snow_history:
            snow_history = await self._query_servicenow_history(target)

        extracted_dependencies = self._extract_dependencies_from_logs(logs)
        metric_anomalies = self._build_metric_anomalies(metrics)

        state["logs"] = logs[:50]
        state["metrics"] = metrics
        state["alerts"] = alerts[:20]
        state["rag_results"] = rag_results
        graph_payload = mcp_context.get("graph", {"dependencies": [], "recent_incidents": []})
        if not graph_payload.get("dependencies") and extracted_dependencies:
            graph_payload["dependencies"] = [
                {
                    "service_name": state.get("target_service", ""),
                    "namespace": None,
                    "pods": [],
                    "dependencies": extracted_dependencies,
                    "source": "logs_dependency_extraction_fallback",
                }
            ]
        state["graph_context"] = graph_payload
        state["servicenow_history"] = snow_history
        state["istio_context"] = mcp_context.get("istio", {})
        state["extracted_dependencies"] = extracted_dependencies
        state["metric_anomalies"] = metric_anomalies
        state["context_sources"] = mcp_context.get("sources", {})
        state["mcp_contract_hits"] = mcp_context.get("contract_hits", [])
        state["additional_context"] = {
            "kubernetes": mcp_context.get("kubernetes", {}),
            "aws": mcp_context.get("aws", {}),
            "cloud_provider_context": mcp_context.get("cloud_provider_context", {}),
        }
        state["cloud_probe_plan"] = mcp_context.get("cloud_probe_plan", {})
        state["mcp_sources_contributed"] = sorted(list(state["context_sources"].keys()))
        source_missing = []
        for capability in ("logs", "metrics", "graph", "istio"):
            if capability not in state["context_sources"]:
                source_missing.append(capability)
        if not metrics:
            source_missing.append("metrics_data")
        if not extracted_dependencies:
            source_missing.append("dependency_extraction")
        state["observability_missing_signals"] = sorted(list(set(source_missing)))
        istio_ctx = state.get("istio_context", {})
        istio_summary = (
            f"istio_vs={len(istio_ctx.get('virtual_services', []))}, "
            f"istio_dr={len(istio_ctx.get('destination_rules', []))}"
            if istio_ctx else "istio=disabled"
        )
        graph_ctx = state.get("graph_context", {})
        graph_summary = (
            f"graph_deps={len(graph_ctx.get('dependencies', []))}, "
            f"graph_incidents={len(graph_ctx.get('recent_incidents', []))}"
            if graph_ctx and (graph_ctx.get("dependencies") or graph_ctx.get("recent_incidents")) else "graph=disabled"
        )
        state["context_summary"] = (
            f"env={state.get('environment', 'unknown')}, clouds={','.join(state.get('cloud_providers', []))}, "
            f"logs={len(state['logs'])}, alerts={len(state['alerts'])}, "
            f"rag_docs={len(rag_results.get('results', []))}, graph_hits={len(graph_payload.get('dependencies', []))}, "
            f"extracted_dependencies={len(extracted_dependencies)}, metric_anomalies={len(metric_anomalies)}, "
            f"k8s_workloads={len((mcp_context.get('kubernetes', {}) or {}).get('workloads', []))}, "
            f"aws_lbs={len((mcp_context.get('aws', {}) or {}).get('load_balancers', []))}, "
            f"mcp_logs={state['context_sources'].get('logs', {}).get('provider', 'fallback')}, "
            f"mcp_metrics={state['context_sources'].get('metrics', {}).get('provider', 'fallback')}, "
            f"{istio_summary}, {graph_summary}"
        )

        # Guardrail: fail fast when context is logs-only (prevents generic RCA responses).
        if state["logs"] and not state["alerts"] and not state["metric_anomalies"] and not extracted_dependencies:
            state["operation_status"] = "failed"
            state["error"] = "Context aggregation produced logs-only evidence without dependencies/anomalies."

        await self._persist_state(state)
        return state

    def _rank_cloud_providers(
        self,
        *,
        cloud_providers: List[str],
        resource_types: List[str],
        description: str,
        target_service: str,
    ) -> Dict[str, Any]:
        description_lc = f"{description} {target_service}".lower()
        unique_providers = [p for p in self._normalize_label_list(cloud_providers) if p]
        rankings: List[Dict[str, Any]] = []
        for idx, provider in enumerate(unique_providers):
            score = 0.15
            reasons: List[str] = []
            if provider in description_lc:
                score += 0.45
                reasons.append("mentioned_in_incident")
            provider_signals = {
                "aws": ("amazonaws.com", ".elb.", ".rds.", "route53", "ec2"),
                "azure": ("azure.com", "azurewebsites.net", "azure dns"),
                "gcp": ("googleapis.com", "gcp", "cloud run", "gke"),
            }
            if any(signal in description_lc for signal in provider_signals.get(provider, ())):
                score += 0.25
                reasons.append("provider_specific_signal")
            if resource_types:
                score += 0.1
                reasons.append("resource_scope_present")
            score += max(0.0, 0.1 - (idx * 0.02))
            rankings.append(
                {
                    "provider": provider,
                    "confidence": round(min(score, 0.99), 3),
                    "reasons": reasons or ["request_order"],
                }
            )
        rankings.sort(key=lambda item: item.get("confidence", 0.0), reverse=True)
        top_n = max(1, int(settings.SRE_CLOUD_PROBE_TOP_N or 1))
        selected = [entry["provider"] for entry in rankings[:top_n]]
        return {"rankings": rankings, "selected": selected, "top_n": top_n}

    def _build_cloud_contracts(
        self,
        *,
        selected_clouds: List[str],
        resource_types: List[str],
        service_hint: str,
        regions: List[str],
    ) -> Dict[str, List[Dict[str, Any]]]:
        normalized_resources = set(self._normalize_label_list(resource_types))
        all_contracts = self._mcp_context_contracts.get("cloud_provider_contracts", [])
        grouped: Dict[str, List[Dict[str, Any]]] = {provider: [] for provider in selected_clouds}
        for contract in all_contracts:
            if not isinstance(contract, dict):
                continue
            provider = str(contract.get("provider") or "").strip().lower()
            if provider not in grouped:
                continue
            contract_resources = set(self._normalize_label_list(contract.get("resource_types")))
            if normalized_resources and contract_resources and not (normalized_resources & contract_resources):
                continue
            args = contract.get("arguments")
            if not isinstance(args, dict):
                args = {}
            args = dict(args)
            if "service_hint" in args and not args["service_hint"]:
                args["service_hint"] = service_hint
            if "instance_hint" in args and not args["instance_hint"]:
                args["instance_hint"] = service_hint
            if "cluster_hint" in args and not args["cluster_hint"]:
                args["cluster_hint"] = service_hint
            if "bucket_hint" in args and not args["bucket_hint"]:
                args["bucket_hint"] = service_hint
            if regions and "region" in args and not args["region"]:
                args["region"] = regions[0]
            grouped[provider].append(
                {
                    "provider": provider,
                    "server": contract.get("server"),
                    "tool": contract.get("tool"),
                    "arguments": args,
                }
            )

        # Backward-compatible AWS contracts fallback.
        if "aws" in grouped and not grouped["aws"]:
            for contract in self._mcp_context_contracts["aws"]:
                tool = contract.get("tool")
                if tool == "aws_list_load_balancers":
                    args = {}
                elif tool == "aws_list_rds_instances":
                    args = {"instance_hint": service_hint}
                elif tool == "aws_list_elasticache_clusters":
                    args = {"cluster_hint": service_hint}
                elif tool == "aws_list_ec2_instances":
                    args = {"instance_hint": service_hint}
                elif tool == "aws_list_s3_buckets":
                    args = {"bucket_hint": service_hint}
                else:
                    args = {}
                if regions:
                    args["region"] = regions[0]
                grouped["aws"].append({**contract, "arguments": args})
        return grouped

    async def _collect_context_via_mcp(
        self,
        incident_id: str,
        target_service: str,
        description: str,
        environment: str,
        cloud_providers: List[str],
        resource_types: List[str],
        regions: List[str],
    ) -> Dict[str, Any]:
        """
        Fetch context from MCP contracts with provider-specific priorities.

        Explicit contract groups:
        - logs: Quickwit -> Elasticsearch -> New Relic
        - metrics: Prometheus -> New Relic
        - alerts: Alertmanager -> New Relic
        - incident_history: ServiceNow
        """
        if not settings.SRE_USE_MCP_FOR_CONTEXT_AGGREGATION:
            return {"sources": {}, "contract_hits": []}

        result: Dict[str, Any] = {
            "logs": [],
            "metrics": {},
            "alerts": [],
            "incident_history": [],
            "istio": {},
            "graph": {"dependencies": [], "recent_incidents": []},
            "kubernetes": {"workloads": [], "pod_logs": [], "runtime": {}},
            "aws": {"load_balancers": []},
            "cloud_provider_context": {},
            "cloud_probe_plan": {},
            "sources": {},
            "contract_hits": [],
        }

        now = datetime.utcnow()
        one_hour_ago = now.timestamp() - 3600
        start_time = datetime.utcfromtimestamp(one_hour_ago).isoformat() + "Z"
        end_time = now.isoformat() + "Z"

        logs_contracts = []
        for contract in self._mcp_context_contracts["logs"]:
            if contract.get("tool") in {"fetch_service_logs", "fetch_service_error_logs"}:
                args = {
                    "service_name": target_service,
                    "env": environment or settings.ENVIRONMENT,
                    "lookback_minutes": 60,
                }
            elif contract.get("tool") == "elasticsearch_fetch_service_logs":
                args = {
                    "service_name": target_service,
                    "lookback_minutes": 60,
                }
            else:
                args = {
                    "service": target_service,
                    "query": description,
                    "time_range": "1h",
                    "limit": 100,
                }
            logs_contracts.append(
                {
                    **contract,
                    "arguments": args,
                }
            )

        metrics_contracts = []
        pod_regex = self._target_service_to_pod_regex(target_service)
        for contract in self._mcp_context_contracts["metrics"]:
            if contract.get("tool") == "prometheus_execute_range_query":
                args = {
                    "query": (
                        'sum(rate(container_cpu_usage_seconds_total'
                        f'{{image!="",pod=~"{pod_regex}",container!=""}}[5m])) by (pod,container)'
                    ),
                    "start_time": start_time,
                    "end_time": end_time,
                    "step": "60s",
                }
            else:
                args = {
                    "service": target_service,
                    "query": f"SELECT average(cpuPercent) FROM SystemSample WHERE entityName = '{target_service}' SINCE 1 hour ago",
                    "time_range": "1h",
                    "window": "5m",
                }
            metrics_contracts.append({**contract, "arguments": args})

        alerts_contracts = []
        for contract in self._mcp_context_contracts["alerts"]:
            if contract.get("tool") == "alertmanager_get_alerts":
                alert_filters = self._build_alertmanager_filters(target_service)
                args = {
                    "filters": alert_filters,
                    "active": True,
                    "silenced": False,
                    "inhibited": False,
                    "count": 25,
                    "offset": 0,
                }
            else:
                args = {
                    "service": target_service,
                    "state": "open",
                    "time_range": "1h",
                }
            alerts_contracts.append({**contract, "arguments": args})
        incident_contracts = [
            {
                **contract,
                "arguments": {
                    "query": f"short_descriptionLIKE{target_service}^ORDERBYDESCsys_created_on",
                    "limit": 5,
                },
            }
            for contract in self._mcp_context_contracts["incident_history"]
        ]

        # Infer namespace from target_service (e.g. "prod/my-service" -> namespace=prod, service=my-service)
        if "/" in (target_service or ""):
            parts = target_service.split("/", 1)
            istio_namespace, istio_service = parts[0].strip(), self._sanitize_k8s_service_name(parts[1])
        else:
            istio_namespace = "default"
            istio_service = self._sanitize_k8s_service_name(target_service or "")
            inferred_ns = await self._infer_namespace_from_graph(incident_id, istio_service)
            if inferred_ns:
                istio_namespace = inferred_ns

        # Logs contracts need content-aware fallback: a successful call with empty logs should
        # still fall through to the next provider.
        for contract in logs_contracts:
            logs_call = await self.mcp.call_first_available_contract([contract], session_id=incident_id)
            result["contract_hits"].append({"capability": "logs", **logs_call})
            if logs_call.get("status") != "success":
                continue
            normalized_logs = self._normalize_logs(logs_call.get("response", {}))
            if not normalized_logs:
                continue
            result["logs"] = normalized_logs
            result["sources"]["logs"] = {
                "provider": logs_call.get("provider"),
                "server": logs_call.get("server"),
                "tool": logs_call.get("tool"),
            }
            break

        # After logs: prefer namespace from log metadata (e.g. kubernetes.namespace_name) over graph/default.
        if "/" not in (target_service or ""):
            log_ns = self._extract_namespace_from_normalized_logs(result.get("logs") or [])
            if log_ns:
                istio_namespace = log_ns

        # Only collect Istio context when we have a concrete service (not "all").
        # Try namespace fallbacks to avoid false-empty mesh context when VS/DR are in a
        # different namespace from the workload.
        istio_call = {"status": "skipped", "provider": "istio", "reason": "no_target_service"}
        if istio_service and istio_service.lower() != "all":
            istio_call = await self._call_istio_with_namespace_fallback(
                incident_id=incident_id,
                service_name=istio_service,
                primary_namespace=istio_namespace,
            )

        # Graph contracts: dependencies + recent incidents (when we have a target service)
        graph_deps_contracts = []
        graph_incidents_contracts = []
        if istio_service and istio_service.lower() != "all":
            for contract in self._mcp_context_contracts["graph"]:
                if contract.get("tool") == "graph_get_service_dependencies":
                    graph_deps_contracts.append({
                        **contract,
                        "arguments": {
                            "service_name": istio_service,
                            "namespace": istio_namespace or None,
                            "limit": 20,
                        },
                    })
                elif contract.get("tool") == "graph_get_recent_incidents":
                    graph_incidents_contracts.append({
                        **contract,
                        "arguments": {
                            "service_name": istio_service,
                            "limit": 10,
                        },
                    })

        metrics_call = await self.mcp.call_first_available_contract(metrics_contracts, session_id=incident_id)
        alerts_call = await self.mcp.call_first_available_contract(alerts_contracts, session_id=incident_id)
        history_call = await self.mcp.call_first_available_contract(incident_contracts, session_id=incident_id)
        graph_deps_call = (
            await self.mcp.call_first_available_contract(graph_deps_contracts, session_id=incident_id)
            if graph_deps_contracts
            else {"status": "skipped", "provider": "graph", "reason": "no_target_service"}
        )
        graph_incidents_call = (
            await self.mcp.call_first_available_contract(graph_incidents_contracts, session_id=incident_id)
            if graph_incidents_contracts
            else {"status": "skipped", "provider": "graph", "reason": "no_target_service"}
        )

        k8s_workload_contracts: List[Dict[str, Any]] = []
        k8s_logs_contracts: List[Dict[str, Any]] = []
        k8s_runtime_contracts: List[Dict[str, Any]] = []
        if istio_service and istio_service.lower() != "all":
            for contract in self._mcp_context_contracts["kubernetes"]:
                if contract.get("tool") == "kubernetes_list_workloads":
                    k8s_workload_contracts.append(
                        {
                            **contract,
                            "arguments": {
                                "service_name": istio_service,
                                "namespace": istio_namespace,
                            },
                        }
                    )
                elif contract.get("tool") == "kubernetes_get_pod_logs":
                    k8s_logs_contracts.append(
                        {
                            **contract,
                            "arguments": {
                                "service_name": istio_service,
                                "namespace": istio_namespace,
                                "tail_lines": 200,
                            },
                        }
                    )
                elif contract.get("tool") == "kubernetes_get_service_runtime_context":
                    k8s_runtime_contracts.append(
                        {
                            **contract,
                            "arguments": {
                                "service_name": istio_service,
                                "namespace": istio_namespace,
                            },
                        }
                    )
        k8s_workload_call = (
            await self.mcp.call_first_available_contract(k8s_workload_contracts, session_id=incident_id)
            if k8s_workload_contracts
            else {"status": "skipped", "provider": "kubernetes", "reason": "no_target_service"}
        )
        k8s_logs_call = (
            await self.mcp.call_first_available_contract(k8s_logs_contracts, session_id=incident_id)
            if k8s_logs_contracts
            else {"status": "skipped", "provider": "kubernetes", "reason": "no_target_service"}
        )
        k8s_runtime_call = (
            await self.mcp.call_first_available_contract(k8s_runtime_contracts, session_id=incident_id)
            if k8s_runtime_contracts
            else {"status": "skipped", "provider": "kubernetes", "reason": "no_target_service"}
        )
        cloud_probe_plan = self._rank_cloud_providers(
            cloud_providers=cloud_providers,
            resource_types=resource_types,
            description=description,
            target_service=target_service,
        )
        result["cloud_probe_plan"] = cloud_probe_plan
        cloud_contracts = self._build_cloud_contracts(
            selected_clouds=cloud_probe_plan.get("selected", []),
            resource_types=resource_types,
            service_hint=istio_service or target_service,
            regions=regions,
        )
        cloud_calls: List[Tuple[str, Dict[str, Any]]] = []
        for provider in cloud_probe_plan.get("selected", []):
            provider_contracts = cloud_contracts.get(provider, [])
            if not provider_contracts:
                cloud_calls.append(
                    (
                        provider,
                        {
                            "status": "skipped",
                            "provider": provider,
                            "reason": "no_matching_contracts",
                        },
                    )
                )
                continue
            provider_call = await self.mcp.call_first_available_contract(
                provider_contracts,
                session_id=incident_id,
            )
            cloud_calls.append((provider, provider_call))

        for capability, call in (
            ("metrics", metrics_call),
            ("alerts", alerts_call),
            ("incident_history", history_call),
            ("istio", istio_call),
            ("kubernetes_workloads", k8s_workload_call),
            ("kubernetes_pod_logs", k8s_logs_call),
            ("kubernetes_runtime", k8s_runtime_call),
        ):
            result["contract_hits"].append({"capability": capability, **call})
            if call.get("status") != "success":
                continue
            result["sources"][capability] = {
                "provider": call.get("provider"),
                "server": call.get("server"),
                "tool": call.get("tool"),
            }
            raw_response = call.get("response", {})
            if capability == "metrics":
                result["metrics"] = self._normalize_metrics(raw_response)
            elif capability == "alerts":
                result["alerts"] = self._normalize_alerts(raw_response)
            elif capability == "incident_history":
                result["incident_history"] = self._normalize_incident_history(raw_response)
            elif capability == "istio":
                result["istio"] = self._normalize_istio_context(raw_response)
            elif capability == "kubernetes_workloads":
                result["kubernetes"]["workloads"] = self._normalize_kubernetes_workloads(raw_response)
            elif capability == "kubernetes_pod_logs":
                result["kubernetes"]["pod_logs"] = self._normalize_logs(raw_response)
            elif capability == "kubernetes_runtime":
                runtime_payload = self._extract_result_payload(raw_response)
                if isinstance(runtime_payload, dict):
                    result["kubernetes"]["runtime"] = runtime_payload

        for provider, call in cloud_calls:
            capability = f"cloud_provider:{provider}"
            result["contract_hits"].append({"capability": capability, **call})
            if call.get("status") != "success":
                continue
            raw_response = call.get("response", {})
            result["sources"][capability] = {
                "provider": call.get("provider"),
                "server": call.get("server"),
                "tool": call.get("tool"),
            }
            payload = self._extract_result_payload(raw_response)
            result["cloud_provider_context"][provider] = payload if isinstance(payload, dict) else {"raw": payload}
            if provider == "aws":
                result["aws"] = self._normalize_aws_context(raw_response)

        # Graph: merge dependencies and recent incidents
        result["contract_hits"].append({"capability": "graph", **graph_deps_call})
        result["contract_hits"].append({"capability": "graph_incidents", **graph_incidents_call})
        if graph_deps_call.get("status") == "success":
            result["graph"]["dependencies"] = self._normalize_graph_dependencies(
                graph_deps_call.get("response", {})
            )
            result["sources"]["graph"] = {
                "provider": graph_deps_call.get("provider"),
                "server": graph_deps_call.get("server"),
                "tool": "graph_get_service_dependencies",
            }
        if graph_incidents_call.get("status") == "success":
            result["graph"]["recent_incidents"] = self._normalize_graph_incidents(
                graph_incidents_call.get("response", {})
            )
            if "graph" not in result["sources"]:
                result["sources"]["graph"] = {
                    "provider": graph_incidents_call.get("provider"),
                    "server": graph_incidents_call.get("server"),
                    "tool": "graph_get_recent_incidents",
                }

        # Enrich Prometheus context with additional SRE-oriented metrics.
        prometheus_bundle = await self._collect_prometheus_metrics_bundle(
            incident_id=incident_id,
            target_service=target_service,
            start_time=start_time,
            end_time=end_time,
        )
        if prometheus_bundle.get("successful_queries", 0) > 0:
            result["metrics"] = prometheus_bundle
            result["sources"]["metrics"] = {
                "provider": "prometheus",
                "server": "prometheus-server",
                "tool": "prometheus_execute_query_bundle",
            }

        return result

    async def _call_istio_with_namespace_fallback(
        self,
        incident_id: str,
        service_name: str,
        primary_namespace: str,
    ) -> Dict[str, Any]:
        best_success: Optional[Dict[str, Any]] = None
        for namespace in self._build_istio_namespace_candidates(primary_namespace):
            contracts = [
                {
                    **contract,
                    "arguments": {"service_name": service_name, "namespace": namespace},
                }
                for contract in self._mcp_context_contracts["istio"]
            ]
            call = await self.mcp.call_first_available_contract(contracts, session_id=incident_id)
            if call.get("status") != "success":
                continue
            normalized = self._normalize_istio_context(call.get("response", {}))
            if not best_success:
                best_success = call
            if normalized.get("virtual_services") or normalized.get("destination_rules"):
                return call
        return best_success or {"status": "failed", "provider": "istio", "error": "no_istio_context_found"}

    @staticmethod
    def _extract_result_payload(response: Dict[str, Any]) -> Any:
        def _try_json(value: Any) -> Any:
            if not isinstance(value, str):
                return value
            stripped = value.strip()
            if not stripped:
                return value
            if stripped.startswith("{") or stripped.startswith("["):
                try:
                    return json.loads(stripped)
                except json.JSONDecodeError:
                    return value
            return value

        if isinstance(response, str):
            response = _try_json(response)

        if isinstance(response, dict) and "content" in response and isinstance(response.get("content"), list):
            content = response.get("content") or []
            for item in content:
                if not isinstance(item, dict):
                    continue
                parsed = _try_json(item.get("text"))
                if isinstance(parsed, dict) and "data" in parsed and "status" in parsed:
                    return parsed.get("data")
                if parsed not in (None, ""):
                    return parsed
            return response

        if "result" in response:
            return response["result"]
        if "data" in response:
            return response["data"]
        return response

    def _normalize_logs(self, response: Dict[str, Any]) -> List[Dict[str, Any]]:
        payload = self._extract_result_payload(response)
        items: List[Any] = []
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict):
            if isinstance(payload.get("logs"), list):
                items = payload.get("logs", [])
            elif isinstance(payload.get("result"), dict) and isinstance(payload["result"].get("hits"), list):
                # Quickwit search response shape.
                items = payload["result"].get("hits", [])
        normalized: List[Dict[str, Any]] = []
        for item in items[:200]:
            if not isinstance(item, dict):
                continue
            entry = item.get("json") if isinstance(item.get("json"), dict) else item
            kubernetes = entry.get("kubernetes") if isinstance(entry.get("kubernetes"), dict) else {}
            normalized.append(
                {
                    "timestamp": (
                        entry.get("fluentbit_timestamp")
                        or entry.get("timestamp")
                        or entry.get("@timestamp")
                    ),
                    "severity": entry.get("severity") or entry.get("level") or "info",
                    "message": (
                        entry.get("message")
                        or entry.get("log")
                        or entry.get("msg")
                        or entry.get("text")
                        or ""
                    ),
                    "source": entry.get("source") or entry.get("service") or kubernetes.get("container_name") or "mcp",
                    "traceId": entry.get("traceId") or entry.get("trace_id"),
                    "logUrl": entry.get("logUrl") or entry.get("log_url"),
                    "kubernetes_namespace": kubernetes.get("namespace_name")
                    or kubernetes.get("namespace")
                    or entry.get("namespace_name")
                    or entry.get("kubernetes_namespace"),
                }
            )
        return normalized

    def _normalize_metrics(self, response: Dict[str, Any]) -> Dict[str, Any]:
        payload = self._extract_result_payload(response)
        if isinstance(payload, dict) and "resultType" in payload and "result" in payload:
            return {
                "metrics": {
                    "result_type": payload.get("resultType"),
                    "series": payload.get("result", []),
                }
            }
        if isinstance(payload, dict) and "metrics" in payload:
            return payload
        if isinstance(payload, list):
            return {"metrics": {"series": payload}}
        return payload if isinstance(payload, dict) else {"metrics": {}}

    def _normalize_alerts(self, response: Dict[str, Any]) -> List[Dict[str, Any]]:
        payload = self._extract_result_payload(response)
        items = payload if isinstance(payload, list) else payload.get("alerts", []) if isinstance(payload, dict) else []
        normalized: List[Dict[str, Any]] = []
        for item in items[:100]:
            if not isinstance(item, dict):
                continue
            labels = item.get("labels") if isinstance(item.get("labels"), dict) else {}
            status = item.get("status") if isinstance(item.get("status"), dict) else {}
            annotations = item.get("annotations") if isinstance(item.get("annotations"), dict) else {}
            normalized.append(
                {
                    "name": item.get("name") or item.get("alertname") or labels.get("alertname") or "unknown-alert",
                    "status": item.get("state") or status.get("state") or item.get("status") or "unknown",
                    "severity": item.get("severity") or labels.get("severity") or "unknown",
                    "startsAt": item.get("startsAt") or item.get("timestamp"),
                    "summary": item.get("summary") or annotations.get("summary") or annotations.get("description") or item.get("description") or "",
                }
            )
        return normalized

    @staticmethod
    def _target_service_to_pod_regex(target_service: str) -> str:
        """Convert target service hint into a pod regex used in PromQL filters."""
        target = (target_service or "").strip()
        if not target or target in {"all", "unknown-service"}:
            return ".*"
        if target.startswith("~"):
            return target[1:] or ".*"
        safe = target.replace("\\", "\\\\").replace('"', '\\"')
        return f".*{safe}.*"

    def _build_alertmanager_filters(self, target_service: str) -> List[str]:
        """Build label-aware Alertmanager matchers using common Kubernetes labels."""
        target = (target_service or "").strip().rstrip("-")
        if not target or target in {"all", "unknown-service"}:
            return []

        pod_regex = self._target_service_to_pod_regex(target)
        safe = target.replace("\\", "\\\\").replace('"', '\\"')
        return [
            f'pod=~"{pod_regex}"',
            f'kubernetes_name=~".*{safe}.*"',
            f'app_kubernetes_io_name=~".*{safe}.*"',
            f'argocd_argoproj_io_instance=~".*{safe}.*"',
        ]

    async def _collect_prometheus_metrics_bundle(
        self,
        incident_id: str,
        target_service: str,
        start_time: str,
        end_time: str,
    ) -> Dict[str, Any]:
        """Collect SRE-focused Prometheus metrics for RCA context."""
        pod_regex = self._target_service_to_pod_regex(target_service)
        query_specs: List[Dict[str, Any]] = [
            {
                "id": "cpu_usage_cores_by_pod_container",
                "tool": "prometheus_execute_query",
                "query": (
                    'sum(rate(container_cpu_usage_seconds_total'
                    f'{{image!="",pod=~"{pod_regex}",container!=""}}[5m])) by (pod,container)'
                ),
            },
            {
                "id": "memory_working_set_bytes_by_pod_container",
                "tool": "prometheus_execute_query",
                "query": (
                    'sum(container_memory_working_set_bytes'
                    f'{{pod=~"{pod_regex}",image!="",container!=""}}) by (pod,container)'
                ),
            },
            {
                "id": "container_restarts_total_by_pod_container",
                "tool": "prometheus_execute_query",
                "query": (
                    'sum(kube_pod_container_status_restarts_total'
                    f'{{pod=~"{pod_regex}",container!=""}}) by (pod,container)'
                ),
            },
            {
                "id": "cpu_throttling_ratio_by_pod_container",
                "tool": "prometheus_execute_query",
                "query": (
                    'sum(rate(container_cpu_cfs_throttled_periods_total'
                    f'{{pod=~"{pod_regex}",container!=""}}[5m])) by (pod,container) '
                    '/ clamp_min(sum(rate(container_cpu_cfs_periods_total'
                    f'{{pod=~"{pod_regex}",container!=""}}[5m])) by (pod,container), 1)'
                ),
            },
            {
                "id": "memory_usage_vs_request_pct",
                "tool": "prometheus_execute_query",
                "query": (
                    '100 * sum(container_memory_working_set_bytes'
                    f'{{pod=~"{pod_regex}",image!="",container!=""}}) '
                    '/ clamp_min(sum(kube_pod_container_resource_requests'
                    f'{{pod=~"{pod_regex}",resource="memory"}}), 1)'
                ),
            },
            {
                "id": "cpu_usage_vs_request_pct",
                "tool": "prometheus_execute_query",
                "query": (
                    '100 * sum(rate(container_cpu_usage_seconds_total'
                    f'{{pod=~"{pod_regex}",image!="",container!=""}}[5m])) '
                    '/ clamp_min(sum(kube_pod_container_resource_requests'
                    f'{{pod=~"{pod_regex}",resource="cpu"}}), 1)'
                ),
            },
            {
                "id": "oom_killed_indicator_by_pod_container",
                "tool": "prometheus_execute_query",
                "query": (
                    'max(kube_pod_container_status_last_terminated_reason'
                    f'{{reason="OOMKilled",pod=~"{pod_regex}",container!=""}}) by (pod,container)'
                ),
            },
            {
                "id": "cpu_usage_trend_1h",
                "tool": "prometheus_execute_range_query",
                "query": (
                    'sum(rate(container_cpu_usage_seconds_total'
                    f'{{image!="",pod=~"{pod_regex}",container!=""}}[5m])) by (pod,container)'
                ),
                "start_time": start_time,
                "end_time": end_time,
                "step": "60s",
            },
            {
                "id": "memory_usage_trend_1h",
                "tool": "prometheus_execute_range_query",
                "query": (
                    'sum(container_memory_working_set_bytes'
                    f'{{pod=~"{pod_regex}",image!="",container!=""}}) by (pod,container)'
                ),
                "start_time": start_time,
                "end_time": end_time,
                "step": "60s",
            },
        ]

        bundle: Dict[str, Any] = {
            "provider": "prometheus",
            "pod_regex": pod_regex,
            "time_window": {"start": start_time, "end": end_time},
            "queries": {},
            "successful_queries": 0,
            "failed_queries": 0,
        }

        for spec in query_specs:
            tool_name = spec["tool"]
            arguments = {"query": spec["query"]}
            if tool_name == "prometheus_execute_range_query":
                arguments.update(
                    {
                        "start_time": spec["start_time"],
                        "end_time": spec["end_time"],
                        "step": spec["step"],
                    }
                )

            response = await self.mcp.call_tool(
                tool_name=tool_name,
                arguments=arguments,
                server_name="prometheus-server",
                session_id=incident_id,
            )
            payload = self._extract_result_payload(response)
            result = payload if isinstance(payload, dict) else {}
            series = result.get("result") if isinstance(result.get("result"), list) else []

            query_item: Dict[str, Any] = {
                "tool": tool_name,
                "query": spec["query"],
                "result_type": result.get("resultType") if isinstance(result, dict) else None,
                "series_count": len(series),
                "series": series[:20],
            }

            if isinstance(result, dict):
                bundle["successful_queries"] += 1
            else:
                bundle["failed_queries"] += 1
                query_item["error"] = str(payload)

            bundle["queries"][spec["id"]] = query_item

        return bundle

    def _normalize_incident_history(self, response: Dict[str, Any]) -> List[Dict[str, Any]]:
        payload = self._extract_result_payload(response)
        items = payload if isinstance(payload, list) else payload.get("incidents", []) if isinstance(payload, dict) else []
        normalized: List[Dict[str, Any]] = []
        for item in items[:20]:
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "id": item.get("sys_id") or item.get("id"),
                    "number": item.get("number"),
                    "summary": item.get("short_description") or item.get("summary") or "",
                    "state": item.get("state"),
                    "updated_at": item.get("sys_updated_on") or item.get("updated_at"),
                }
            )
        return normalized

    def _normalize_istio_context(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Extract Istio resources (VirtualServices, DestinationRules, pods) from MCP response."""
        payload = self._extract_result_payload(response)
        if not isinstance(payload, dict) or payload.get("provider") != "istio":
            return {}
        return {
            "service_name": payload.get("service_name"),
            "namespace": payload.get("namespace"),
            "virtual_services": payload.get("virtual_services", []),
            "destination_rules": payload.get("destination_rules", []),
            "pods": payload.get("pods", []),
            "match_note": payload.get("match_note"),
        }

    def _normalize_graph_dependencies(self, response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract Cartography service rows from MCP response (pods, namespace per service)."""
        payload = self._extract_result_payload(response)
        if not isinstance(payload, dict) or payload.get("provider") != "graph":
            return []
        deps = payload.get("dependencies") or payload.get("cartography_rows") or []
        return deps if isinstance(deps, list) else []

    def _normalize_graph_incidents(self, response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract graph recent incidents from MCP response."""
        payload = self._extract_result_payload(response)
        if not isinstance(payload, dict) or payload.get("provider") != "graph":
            return []
        incidents = payload.get("incidents", [])
        return incidents if isinstance(incidents, list) else []

    def _normalize_kubernetes_workloads(self, response: Dict[str, Any]) -> List[Dict[str, Any]]:
        payload = self._extract_result_payload(response)
        if not isinstance(payload, dict):
            return []
        workloads = payload.get("workloads") or payload.get("items") or []
        return workloads if isinstance(workloads, list) else []

    def _normalize_aws_load_balancers(self, response: Dict[str, Any]) -> List[Dict[str, Any]]:
        payload = self._extract_result_payload(response)
        if not isinstance(payload, dict):
            return []
        lbs = payload.get("load_balancers") or payload.get("LoadBalancers") or []
        return lbs if isinstance(lbs, list) else []

    def _normalize_aws_context(self, response: Dict[str, Any]) -> Dict[str, Any]:
        payload = self._extract_result_payload(response)
        if not isinstance(payload, dict):
            return {"load_balancers": [], "rds_instances": [], "elasticache_clusters": [], "ec2_instances": [], "s3_buckets": []}
        lbs = payload.get("load_balancers") or payload.get("LoadBalancers") or []
        rds = payload.get("rds_instances") or payload.get("instances") or payload.get("DBInstances") or []
        cache = payload.get("elasticache_clusters") or payload.get("clusters") or payload.get("CacheClusters") or []
        ec2 = payload.get("ec2_instances") or payload.get("instances") or payload.get("Reservations") or []
        buckets = payload.get("buckets") or payload.get("Buckets") or []
        return {
            "load_balancers": lbs if isinstance(lbs, list) else [],
            "rds_instances": rds if isinstance(rds, list) else [],
            "elasticache_clusters": cache if isinstance(cache, list) else [],
            "ec2_instances": ec2 if isinstance(ec2, list) else [],
            "s3_buckets": buckets if isinstance(buckets, list) else [],
        }

    @staticmethod
    def _extract_dependencies_from_logs(logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        patterns = [
            (r"[\w.-]+\.elb\.amazonaws\.com", "AWS_ELB"),
            (r"[\w.-]+\.rds\.amazonaws\.com", "AWS_RDS"),
            (r"[\w.-]+\.cache\.amazonaws\.com", "AWS_CACHE"),
            (r"\brabbitmq\b|\bamqp\b", "RABBITMQ"),
            (r"\bredis\b", "REDIS"),
            (r"\bmongo(?:db)?\b", "MONGODB"),
            (r"\bpostgres(?:ql)?\b", "POSTGRESQL"),
        ]
        found: Dict[str, Dict[str, Any]] = {}
        for entry in logs[:200]:
            msg = str(entry.get("message", ""))
            lower_msg = msg.lower()
            for pattern, dep_type in patterns:
                for match in re.findall(pattern, lower_msg):
                    key = f"{dep_type}:{match}"
                    if key not in found:
                        dependency_signal: Dict[str, Any] = {
                            "type": dep_type,
                            "name": match,
                            "source": "logs",
                            "evidence_signal": msg[:300],
                        }
                        failure_type = SREMultiAgent._classify_failure_type_from_message(msg)
                        if failure_type:
                            dependency_signal["failure_signal"] = msg[:300]
                            dependency_signal["failure_type"] = failure_type
                        found[key] = dependency_signal
            if any(
                token in lower_msg
                for token in ("no such host", "temporary failure in name resolution", "nxdomain", "servfail")
            ):
                key = "KUBERNETES_DNS:cluster-dns"
                if key not in found:
                    found[key] = {
                        "type": "KUBERNETES_DNS",
                        "name": "cluster-dns",
                        "source": "logs",
                        "failure_signal": msg[:300],
                    }
        return list(found.values())[:30]

    @staticmethod
    def _build_metric_anomalies(metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
        anomalies: List[Dict[str, Any]] = []
        queries = metrics.get("queries", {}) if isinstance(metrics, dict) else {}
        if not isinstance(queries, dict):
            return anomalies
        for query_id, payload in queries.items():
            if not isinstance(payload, dict):
                continue
            for series in payload.get("series", [])[:20]:
                if not isinstance(series, dict):
                    continue
                values = series.get("values", [])
                if not isinstance(values, list) or len(values) < 4:
                    continue
                nums: List[float] = []
                for point in values[-20:]:
                    if not isinstance(point, list) or len(point) < 2:
                        continue
                    try:
                        nums.append(float(point[1]))
                    except (TypeError, ValueError):
                        continue
                if len(nums) < 4:
                    continue
                baseline = sum(nums[:-1]) / max(1, len(nums) - 1)
                current = nums[-1]
                if baseline <= 0:
                    continue
                if current >= baseline * 2.0:
                    anomalies.append(
                        {
                            "type": query_id,
                            "value": round(current, 4),
                            "baseline": round(baseline, 4),
                            "ratio": round(current / baseline, 4),
                        }
                    )
        return anomalies[:30]

    @staticmethod
    def _build_log_evidence_digest(logs: List[Dict[str, Any]]) -> Dict[str, Any]:
        runtime_failure_signals: List[str] = []
        dependency_failure_signals: List[str] = []
        dependency_success_signals: List[str] = []
        error_count = 0
        warn_count = 0

        for entry in logs[:300]:
            if not isinstance(entry, dict):
                continue
            message = str(entry.get("message", "")).strip()
            if not message:
                continue
            lower = message.lower()
            severity = str(entry.get("severity", "")).strip().lower()
            if severity == "error" or " error " in lower:
                error_count += 1
            elif severity == "warn" or " warn " in lower:
                warn_count += 1

            if SREMultiAgent._is_runtime_failure_message(message):
                if message[:260] not in runtime_failure_signals:
                    runtime_failure_signals.append(message[:260])
            if any(token in lower for token in _DEPENDENCY_SUCCESS_LOG_TOKENS):
                if message[:260] not in dependency_success_signals:
                    dependency_success_signals.append(message[:260])
            failure_type = SREMultiAgent._classify_failure_type_from_message(message)
            if failure_type:
                tagged = f"{failure_type}: {message[:240]}"
                if tagged not in dependency_failure_signals:
                    dependency_failure_signals.append(tagged)

        return {
            "runtime_failure_signals": runtime_failure_signals[:8],
            "dependency_failure_signals": dependency_failure_signals[:8],
            "dependency_success_signals": dependency_success_signals[:8],
            "error_count": error_count,
            "warn_count": warn_count,
        }

    @staticmethod
    def _build_metrics_evidence_digest(metrics: Dict[str, Any]) -> Dict[str, Any]:
        queries = metrics.get("queries", {}) if isinstance(metrics, dict) else {}
        if not isinstance(queries, dict):
            return {"summary": ["metrics_unavailable"]}

        def _extract_values(query_id: str) -> List[float]:
            payload = queries.get(query_id, {})
            if not isinstance(payload, dict):
                return []
            out: List[float] = []
            for series in payload.get("series", []) if isinstance(payload.get("series"), list) else []:
                if not isinstance(series, dict):
                    continue
                value = series.get("value")
                if isinstance(value, list) and len(value) >= 2:
                    try:
                        out.append(float(value[1]))
                    except (TypeError, ValueError):
                        continue
            return out

        cpu_usage_pct = _extract_values("cpu_usage_vs_request_pct")
        mem_usage_pct = _extract_values("memory_usage_vs_request_pct")
        cpu_throttle = _extract_values("cpu_throttling_ratio_by_pod_container")
        oom_killed = _extract_values("oom_killed_indicator_by_pod_container")
        restarts = []
        for series in (
            (queries.get("container_restarts_total_by_pod_container", {}) or {}).get("series", [])
            if isinstance(queries.get("container_restarts_total_by_pod_container", {}), dict)
            else []
        ):
            if not isinstance(series, dict):
                continue
            metric = series.get("metric", {}) if isinstance(series.get("metric"), dict) else {}
            container = str(metric.get("container", "")).strip().lower()
            if container == "istio-proxy":
                continue
            value = series.get("value")
            if isinstance(value, list) and len(value) >= 2:
                try:
                    restarts.append(float(value[1]))
                except (TypeError, ValueError):
                    continue

        max_cpu_pct = max(cpu_usage_pct) if cpu_usage_pct else None
        max_mem_pct = max(mem_usage_pct) if mem_usage_pct else None
        max_cpu_throttle = max(cpu_throttle) if cpu_throttle else None
        max_restart_count = max(restarts) if restarts else None
        oom_killed_detected = any(v > 0 for v in oom_killed)
        resource_pressure_detected = bool(
            (max_cpu_pct is not None and max_cpu_pct >= 85.0)
            or (max_mem_pct is not None and max_mem_pct >= 90.0)
            or (max_cpu_throttle is not None and max_cpu_throttle >= 0.2)
            or oom_killed_detected
        )

        summary: List[str] = []
        if max_cpu_pct is not None:
            summary.append(f"max_cpu_usage_vs_request_pct={round(max_cpu_pct, 3)}")
        if max_mem_pct is not None:
            summary.append(f"max_memory_usage_vs_request_pct={round(max_mem_pct, 3)}")
        if max_cpu_throttle is not None:
            summary.append(f"max_cpu_throttle_ratio={round(max_cpu_throttle, 4)}")
        if max_restart_count is not None:
            summary.append(f"max_app_container_restarts={int(max_restart_count)}")
        summary.append(f"oom_killed_detected={oom_killed_detected}")
        summary.append(f"resource_pressure_detected={resource_pressure_detected}")

        return {
            "max_cpu_usage_vs_request_pct": round(max_cpu_pct, 4) if max_cpu_pct is not None else None,
            "max_memory_usage_vs_request_pct": round(max_mem_pct, 4) if max_mem_pct is not None else None,
            "max_cpu_throttle_ratio": round(max_cpu_throttle, 6) if max_cpu_throttle is not None else None,
            "max_app_container_restarts": int(max_restart_count) if max_restart_count is not None else None,
            "oom_killed_detected": oom_killed_detected,
            "resource_pressure_detected": resource_pressure_detected,
            "summary": summary,
        }

    @staticmethod
    def _build_logs_prompt_view(logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        selected: List[Dict[str, Any]] = []
        for entry in logs[:300]:
            if not isinstance(entry, dict):
                continue
            message = str(entry.get("message", "")).strip()
            if not message:
                continue
            lower = message.lower()
            is_priority = bool(
                SREMultiAgent._is_runtime_failure_message(message)
                or any(token in lower for token in _DEPENDENCY_SUCCESS_LOG_TOKENS)
                or SREMultiAgent._classify_failure_type_from_message(message)
                or "error" in lower
                or "exception" in lower
                or "warn" in lower
            )
            if not is_priority and len(selected) >= 12:
                continue
            selected.append(
                {
                    "timestamp": entry.get("timestamp"),
                    "severity": entry.get("severity"),
                    "source": entry.get("source"),
                    "message": message[:320],
                }
            )
            if len(selected) >= 40:
                break
        return selected

    @staticmethod
    def _build_metrics_prompt_view(metrics: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(metrics, dict):
            return {}
        out: Dict[str, Any] = {
            "provider": metrics.get("provider"),
            "time_window": metrics.get("time_window"),
            "queries": {},
        }
        queries = metrics.get("queries", {})
        if not isinstance(queries, dict):
            return out
        for query_id, payload in list(queries.items())[:20]:
            if not isinstance(payload, dict):
                continue
            samples: List[Dict[str, Any]] = []
            series = payload.get("series", [])
            if isinstance(series, list):
                for item in series[:5]:
                    if not isinstance(item, dict):
                        continue
                    sample_val = item.get("value")
                    if sample_val is None and isinstance(item.get("values"), list) and item["values"]:
                        sample_val = item["values"][-1]
                    samples.append(
                        {
                            "metric": item.get("metric", {}),
                            "value": sample_val,
                        }
                    )
            out["queries"][query_id] = {
                "result_type": payload.get("result_type"),
                "series_count": payload.get("series_count"),
                "samples": samples,
            }
        return out

    @staticmethod
    def _is_runtime_failure_message(message: str) -> bool:
        text = str(message or "").strip()
        if not text:
            return False
        lower = text.lower()
        if any(token in lower for token in _RUNTIME_FAILURE_LOG_TOKENS):
            return True
        if any(re.search(pattern, lower) for pattern in _RUNTIME_FAILURE_REGEXES):
            # Keep dependency-protocol failures in dependency classification path.
            dep_failure = SREMultiAgent._classify_failure_type_from_message(text)
            if dep_failure:
                return False
            return True
        return False

    @staticmethod
    def _split_target_service(target_service: str) -> Tuple[str, str]:
        """Return (namespace, service_name). Namespace is empty if not in ns/svc form."""
        if not target_service:
            return "", ""
        ts = target_service.strip()
        if "/" in ts:
            ns, name = ts.split("/", 1)
            return ns.strip(), name.strip()
        return "", ts

    @staticmethod
    def _sanitize_k8s_service_name(raw: str) -> str:
        """Reduce LLM or ticket prose to a single DNS-like Kubernetes service name."""
        if not raw:
            return ""
        blocked_tokens = {
            "potentially",
            "other",
            "services",
            "service",
            "dependency",
            "dependencies",
            "dependent",
            "component",
            "relying",
            "same",
            "dns",
            "resolution",
            "issue",
            "failure",
            "unknown",
        }
        s = raw.strip().split("\n")[0].strip()
        s = re.sub(r"\s*\([^)]*\)\s*$", "", s).strip()
        if "/" in s:
            left, right = s.split("/", 1)
            s = (right or left).strip()
        for prefix in ("service ", "kubernetes service ", "deployment ", "svc ", "pod ", "k8s "):
            if s.lower().startswith(prefix):
                s = s[len(prefix) :].strip()
                break
        candidates = re.findall(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", s.lower())
        candidates = [c for c in candidates if len(c) >= 3 and c not in blocked_tokens]
        if candidates:
            return max(candidates, key=len)
        return ""

    @staticmethod
    def _build_service_aliases(raw: str) -> List[str]:
        """Generate stable aliases for matching service references across tools/logs."""
        if not raw:
            return []
        ns, name = SREMultiAgent._split_target_service(raw)
        base = SREMultiAgent._sanitize_k8s_service_name(name or raw)
        aliases = [base, raw.strip().lower(), (name or "").strip().lower(), ns.strip().lower()]
        out: List[str] = []
        for alias in aliases:
            val = (alias or "").strip().lower()
            if val and val not in out:
                out.append(val)
        return out

    @staticmethod
    def _normalize_dependency_key(raw: str) -> str:
        """Preserve endpoint-like dependencies; sanitize Kubernetes service hints."""
        value = str(raw or "").strip().lower()
        if not value:
            return ""
        if "." in value and any(
            token in value
            for token in ("amazonaws.com", "svc.cluster.local", "azure.com", "googleapis.com")
        ):
            return value
        return SREMultiAgent._sanitize_k8s_service_name(value) or value

    @staticmethod
    def _message_has_dns_failure(message: str) -> bool:
        lower = str(message or "").lower()
        return any(token in lower for token in _DNS_FAILURE_LOG_TOKENS)

    def _derive_terminal_conclusion(self, state: SREMultiAgentState) -> Dict[str, Any]:
        """
        Determine whether evidence is conclusive enough to skip further investigation.

        Current deterministic classes supported:
        - DNS_RESOURCE_MISSING: endpoint absent in infra/cloud inventory + DNS resolution failure.
        - RUNTIME_FAILURE (config): explicit startup/runtime error states required config/credential missing.
        """
        additional = state.get("additional_context", {}) if isinstance(state.get("additional_context"), dict) else {}
        dependency_findings = (
            additional.get("dependency_findings", [])
            if isinstance(additional.get("dependency_findings"), list)
            else []
        )
        external_evals = (
            additional.get("external_dependency_evaluations", [])
            if isinstance(additional.get("external_dependency_evaluations"), list)
            else []
        )
        debug_dns = (
            additional.get("debug_pod_dns_checks", [])
            if isinstance(additional.get("debug_pod_dns_checks"), list)
            else []
        )
        logs = state.get("logs", []) if isinstance(state.get("logs"), list) else []

        not_found_hosts: Dict[str, Dict[str, Any]] = {}
        for item in external_evals[:20]:
            if not isinstance(item, dict):
                continue
            host = str(item.get("endpoint", "")).strip().lower()
            verdict = str(item.get("existence_verdict", "")).strip().lower()
            if host and verdict == "not_found":
                not_found_hosts[host] = item

        if not not_found_hosts:
            runtime_terminal = self._derive_runtime_config_terminal_conclusion(state, logs)
            if runtime_terminal:
                return runtime_terminal
            return {"is_terminal": False}

        dns_failed_hosts = set()
        for probe in debug_dns[:20]:
            if not isinstance(probe, dict):
                continue
            host = str(probe.get("endpoint", "")).strip().lower()
            verdict = str(probe.get("dns_verdict", "")).strip().lower()
            if host and verdict == "nxdomain_or_nodata":
                dns_failed_hosts.add(host)

        for entry in logs[:300]:
            if not isinstance(entry, dict):
                continue
            msg = str(entry.get("message", ""))
            if not self._message_has_dns_failure(msg):
                continue
            lower = msg.lower()
            for host in not_found_hosts:
                if host in lower:
                    dns_failed_hosts.add(host)

        for finding in dependency_findings[:30]:
            if not isinstance(finding, dict):
                continue
            dep = str(finding.get("dependency", "")).strip().lower()
            if not dep:
                continue
            failure_types = {
                str(ft).strip().lower()
                for ft in (finding.get("failure_types", []) if isinstance(finding.get("failure_types"), list) else [])
                if str(ft).strip()
            }
            if "dns_probe_failure" in failure_types or "dns" in failure_types:
                for host in not_found_hosts:
                    if dep in host or host in dep:
                        dns_failed_hosts.add(host)

        if not dns_failed_hosts:
            runtime_terminal = self._derive_runtime_config_terminal_conclusion(state, logs)
            if runtime_terminal:
                return runtime_terminal
            return {"is_terminal": False}

        selected_host = sorted(dns_failed_hosts)[0]
        host_eval = not_found_hosts.get(selected_host, {})
        resource_type = str((host_eval.get("classification") or {}).get("resource_type", "")).lower()
        dependency_name = "dependency endpoint"
        if resource_type == "load_balancer":
            dependency_name = "load balancer endpoint"
        elif resource_type == "rds":
            dependency_name = "RDS endpoint"
        elif resource_type == "elasticache":
            dependency_name = "ElastiCache endpoint"

        root_cause = f"{dependency_name} '{selected_host}' does not exist and fails DNS resolution."

        evidence = [
            f"Endpoint missing in inventory/cloud lookup: {selected_host}",
            f"DNS resolution failure for endpoint: {selected_host}",
        ]

        return {
            "is_terminal": True,
            "requires_more_data": False,
            "root_cause_category": "DNS_RESOURCE_MISSING",
            "root_cause": root_cause,
            "terminal_dependency": selected_host,
            "terminal_evidence": evidence,
            "confidence_override": 0.95,
        }

    @staticmethod
    def _extract_missing_runtime_config_signal(logs: List[Dict[str, Any]]) -> Optional[Dict[str, str]]:
        """Extract explicit missing required config/credential signal from runtime-failure logs."""
        for entry in logs[:300]:
            if not isinstance(entry, dict):
                continue
            message = str(entry.get("message", "")).strip()
            if not message or not SREMultiAgent._is_runtime_failure_message(message):
                continue
            lower = message.lower()
            if not any(token in lower for token in _MISSING_CONFIG_SIGNAL_TOKENS):
                continue
            sensitive = any(token in lower for token in _SENSITIVE_CONFIG_TOKENS)
            # Prefer explicit env-style keys first.
            key_match = re.search(
                r"\b([A-Z][A-Z0-9_]{2,})\b(?=[^A-Za-z0-9]*(?:must be set|is required|required|not set|missing))",
                message,
            )
            key = key_match.group(1) if key_match else ""
            if not key:
                phrase_match = re.search(
                    r"\b([A-Za-z0-9_.-]{2,60}(?:[_\s-]?(?:api[_\s-]?key|token|secret|password|credential)))\b",
                    message,
                    re.IGNORECASE,
                )
                if phrase_match:
                    candidate = phrase_match.group(1)
                    key = re.sub(r"[^A-Za-z0-9]+", "_", candidate).strip("_").upper()
            if not key and not sensitive:
                continue
            return {
                "config_key": key or "REQUIRED_CONFIG_KEY",
                "signal": re.sub(r"\s+", " ", message).strip()[:260],
                "failure_type": "auth" if sensitive else "unknown",
            }
        return None

    def _derive_runtime_config_terminal_conclusion(
        self, state: SREMultiAgentState, logs: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Terminal for explicit runtime startup failures due to missing required config."""
        signal = self._extract_missing_runtime_config_signal(logs)
        if not signal:
            return None
        dependency_findings = (
            (state.get("additional_context") or {}).get("dependency_findings", [])
            if isinstance(state.get("additional_context"), dict)
            else []
        )
        for item in dependency_findings if isinstance(dependency_findings, list) else []:
            if not isinstance(item, dict):
                continue
            if str(item.get("status", "")).strip().lower() == "confirmed_failed":
                # Prefer dependency terminal classes when hard dependency outages are proven.
                return None
        metrics_digest = self._build_metrics_evidence_digest(state.get("metrics", {}))
        if bool(metrics_digest.get("resource_pressure_detected")):
            return None
        service_name = str(state.get("target_service") or state.get("failing_service") or "service")
        config_key = str(signal.get("config_key") or "REQUIRED_CONFIG_KEY")
        root_cause = (
            f"The `{service_name}` workload fails during startup because required runtime configuration "
            f"`{config_key}` is missing or empty."
        )
        evidence = [
            f"Explicit startup/runtime config error in logs: {signal.get('signal')}",
            f"Missing required config key: {config_key}",
            "resource_pressure_detected=False",
        ]
        return {
            "is_terminal": True,
            "requires_more_data": False,
            "root_cause_category": "RUNTIME_FAILURE",
            "root_cause": root_cause,
            "terminal_dependency": None,
            "terminal_evidence": evidence,
            "runtime_required_config_key": config_key,
            "failure_type": signal.get("failure_type", "configuration"),
            "confidence_override": 0.93,
        }

    def _apply_terminal_conclusion(self, state: SREMultiAgentState) -> None:
        terminal = self._derive_terminal_conclusion(state)
        if not terminal.get("is_terminal"):
            # Never treat LLM-declared terminal RCA as final without verified checks.
            state["is_terminal"] = False
            state["requires_more_data"] = True
            state["terminal_dependency"] = None
            state["terminal_evidence"] = []
            return
        state["is_terminal"] = True
        state["requires_more_data"] = False
        state["root_cause_category"] = str(terminal.get("root_cause_category", "unknown"))
        state["terminal_dependency"] = terminal.get("terminal_dependency")
        state["terminal_evidence"] = terminal.get("terminal_evidence", [])
        state.setdefault("additional_context", {})
        if isinstance(state["additional_context"], dict):
            failure_type = str(
                terminal.get("failure_type")
                or ("dns" if str(terminal.get("root_cause_category", "")).upper() == "DNS_RESOURCE_MISSING" else "unknown")
            )
            state["additional_context"]["failure_type"] = failure_type
            runtime_key = terminal.get("runtime_required_config_key")
            if runtime_key:
                state["additional_context"]["runtime_required_config_key"] = str(runtime_key)
        if terminal.get("root_cause"):
            state["root_cause"] = str(terminal.get("root_cause"))
            state["hypothesis"] = str(terminal.get("root_cause"))
        if not isinstance(state.get("evidence"), list):
            state["evidence"] = []
        for item in terminal.get("terminal_evidence", []):
            if item not in state["evidence"]:
                state["evidence"].append(item)

    def _apply_runtime_failure_guardrail(self, state: SREMultiAgentState) -> None:
        """Prefer explicit application runtime failures over speculative dependency narratives."""
        if bool(state.get("is_terminal", False)):
            return
        logs = state.get("logs", []) if isinstance(state.get("logs"), list) else []
        log_digest = self._build_log_evidence_digest(logs)
        runtime_signals = log_digest.get("runtime_failure_signals", [])
        if not isinstance(runtime_signals, list) or not runtime_signals:
            return
        dependency_findings = (
            (state.get("additional_context") or {}).get("dependency_findings", [])
            if isinstance(state.get("additional_context"), dict)
            else []
        )
        has_confirmed_dependency_failure = False
        for item in dependency_findings if isinstance(dependency_findings, list) else []:
            if not isinstance(item, dict):
                continue
            if str(item.get("status", "")).strip().lower() == "confirmed_failed":
                has_confirmed_dependency_failure = True
                break
        if has_confirmed_dependency_failure:
            return

        metrics_digest = self._build_metrics_evidence_digest(state.get("metrics", {}))
        resource_pressure = bool(metrics_digest.get("resource_pressure_detected"))
        service_name = str(state.get("target_service") or state.get("failing_service") or "service")
        primary_signal = str(runtime_signals[0])
        concise_signal = re.sub(r"\s+", " ", primary_signal).strip()[:220]
        root_cause = (
            f"The `{service_name}` workload is failing during application startup/runtime "
            f"(e.g. `{concise_signal}`), which is consistent with a service-level runtime failure."
        )
        if not resource_pressure:
            root_cause += " CPU/memory signals do not indicate resource exhaustion."

        state["root_cause_category"] = "RUNTIME_FAILURE"
        state["root_cause"] = root_cause
        state["hypothesis"] = root_cause
        state.setdefault("additional_context", {})
        if isinstance(state["additional_context"], dict):
            state["additional_context"]["failure_type"] = str(
                (state["additional_context"] or {}).get("failure_type") or "unknown"
            )
            state["additional_context"]["runtime_failure_guardrail"] = {
                "applied": True,
                "runtime_signal": concise_signal,
                "resource_pressure_detected": resource_pressure,
            }
        if not isinstance(state.get("evidence"), list):
            state["evidence"] = []
        runtime_marker = f"runtime_log_signature={concise_signal}"
        if runtime_marker not in state["evidence"]:
            state["evidence"].append(runtime_marker)
        metric_marker = f"resource_pressure_detected={resource_pressure}"
        if metric_marker not in state["evidence"]:
            state["evidence"].append(metric_marker)

    @staticmethod
    def _build_istio_namespace_candidates(primary_namespace: str) -> List[str]:
        candidates: List[str] = []
        primary = (primary_namespace or "").strip()
        if primary:
            candidates.append(primary)
        extra = str(getattr(settings, "SRE_ISTIO_VIRTUALSERVICE_NAMESPACES", "") or "").strip()
        if extra:
            for item in extra.replace(";", ",").split(","):
                ns = item.strip()
                if ns and ns not in candidates:
                    candidates.append(ns)
        if not candidates:
            candidates.append("default")
        return candidates[:8]

    @staticmethod
    def _extract_namespace_from_normalized_logs(logs: List[Dict[str, Any]]) -> Optional[str]:
        for entry in logs[:80]:
            if not isinstance(entry, dict):
                continue
            ns = entry.get("kubernetes_namespace")
            if isinstance(ns, str) and ns.strip():
                return ns.strip()
        return None

    @staticmethod
    def _is_control_plane_service(service_hint: str) -> bool:
        """Best-effort detection of control-plane dependencies when graph lookup is unavailable."""
        normalized = (service_hint or "").strip().lower()
        if not normalized:
            return False
        tokens = (
            "kube-proxy",
            "metrics-server",
            "node-local-dns",
            "cluster-autoscaler",
            "external-dns",
            "aws-node",
            "calico",
            "cilium",
            "flannel",
            "weave-net",
            "csi-",
        )
        return any(token in normalized for token in tokens)

    async def _infer_namespace_from_graph(self, incident_id: str, service_name: str) -> Optional[str]:
        sanitized = self._sanitize_k8s_service_name(service_name)
        if not sanitized or sanitized.lower() == "all":
            return None
        response = await self.mcp.call_tool(
            tool_name="graph_resolve_kubernetes_service",
            arguments={"service_name": sanitized},
            server_name="graph-server",
            session_id=incident_id,
        )
        payload = self._extract_result_payload(response)
        if not isinstance(payload, dict):
            return None
        resolved = payload.get("resolved")
        if isinstance(resolved, dict):
            ns = resolved.get("namespace")
            if isinstance(ns, str) and ns.strip():
                return ns.strip()
        return None

    async def _resolve_namespace_for_k8s_logs(
        self,
        incident_id: str,
        service_hint: str,
        fallback: Optional[str],
    ) -> str:
        raw_ns, _ = self._split_target_service(service_hint or "")
        if raw_ns:
            return raw_ns
        if isinstance(fallback, str) and fallback.strip():
            return fallback.strip()
        normalized_hint = self._sanitize_k8s_service_name(service_hint)
        if self._is_control_plane_service(normalized_hint):
            return "kube-system"
        ns = await self._infer_namespace_from_graph(incident_id, service_hint)
        if ns:
            return ns
        return "default"

    @staticmethod
    def _classify_failure_type_from_message(message: str) -> Optional[str]:
        if not message:
            return None
        lower = message.lower()
        if any(token in lower for token in _DEPENDENCY_SUCCESS_LOG_TOKENS):
            return None
        if any(token in lower for token in ("no such host", "temporary failure in name resolution", "nxdomain")):
            return "dns"
        if "connection refused" in lower or "econnrefused" in lower:
            return "connection_refused"
        timeout_match = re.search(
            r"\b(?:i/o timeout|timed out|timeout while|timeout after|read timeout|connect timeout|"
            r"sockettimeout|deadline exceeded|context deadline exceeded|operation timed out)\b",
            lower,
        )
        timeout_config_noise = (
            "logicalsessiontimeoutminutes",
            "connecttimeoutms",
            "sockettimeoutms",
            "serverselectiontimeoutms",
            "waitqueuetimeoutms",
        )
        if timeout_match and not any(token in lower for token in timeout_config_noise):
            return "timeout"
        if "unauthorized" in lower or "forbidden" in lower or "access denied" in lower:
            return "auth"
        return None

    @staticmethod
    def _extract_endpoint_host_candidates(dependencies: List[Dict[str, Any]], logs: List[Dict[str, Any]]) -> List[str]:
        hosts: List[str] = []
        endpoint_pattern = re.compile(
            r"([a-z0-9][a-z0-9.-]+\.(?:elb|rds|cache)\.[a-z0-9-]+\.amazonaws\.com|[a-z0-9][a-z0-9.-]+\.s3\.[a-z0-9-]+\.amazonaws\.com)"
        )
        for dep in dependencies[:40]:
            if not isinstance(dep, dict):
                continue
            name = str(dep.get("name", "")).strip().lower()
            if endpoint_pattern.search(name):
                hosts.append(name)
        for item in logs[:300]:
            if not isinstance(item, dict):
                continue
            msg = str(item.get("message", "")).lower()
            hosts.extend(endpoint_pattern.findall(msg))
        deduped: List[str] = []
        for host in hosts:
            norm = host.strip().strip('.,:;"\'')
            if norm and norm not in deduped:
                deduped.append(norm)
        return deduped[:8]

    @staticmethod
    def _classify_dns_probe_output(output: str) -> str:
        """Classify nslookup/dig-style output without assuming a specific DNS server."""
        if not output:
            return "empty"
        lower = output.lower()
        if any(
            x in lower
            for x in (
                "nxdomain",
                "** server can't find",
                "can't find",
                "name or service not known",
                "no servers could be reached",
            )
        ):
            return "nxdomain_or_nodata"
        if "no answer" in lower and "address" not in lower:
            return "nxdomain_or_nodata"
        if "address:" in lower or "addresses:" in lower:
            return "resolved"
        if "connection timed out" in lower or "timed out" in lower:
            return "timeout"
        return "inconclusive"

    async def _run_debug_pod_dns_checks(
        self,
        incident_id: str,
        endpoints: List[str],
    ) -> Dict[str, Any]:
        """Optional in-cluster DNS probes via kubernetes_exec_in_pod (debug pod)."""
        if not getattr(settings, "SRE_DEBUG_POD_DNS_CHECKS_ENABLED", False):
            return {"results": [], "mcp_hits": []}
        ns = (getattr(settings, "SRE_DEBUG_POD_NAMESPACE", "") or "").strip()
        pod_name = (getattr(settings, "SRE_DEBUG_POD_NAME", "") or "").strip()
        if not ns or not pod_name or not endpoints:
            return {"results": [], "mcp_hits": []}
        container = (getattr(settings, "SRE_DEBUG_POD_CONTAINER", "") or "").strip()
        results: List[Dict[str, Any]] = []
        mcp_hits: List[Dict[str, Any]] = []
        for host in endpoints[:4]:
            safe = shlex.quote(host)
            cmd = ["/bin/sh", "-c", f"nslookup {safe} 2>&1; echo '---'; getent hosts {safe} 2>&1 || true"]
            args: Dict[str, Any] = {
                "namespace": ns,
                "pod_name": pod_name,
                "command": cmd,
            }
            if container:
                args["container"] = container
            call = await self.mcp.call_first_available_contract(
                [
                    {
                        "provider": "kubernetes",
                        "server": "kubernetes-mcp",
                        "tool": "kubernetes_exec_in_pod",
                        "arguments": args,
                    }
                ],
                session_id=incident_id,
            )
            mcp_hits.append({"capability": "debug_pod_dns", **call})
            out = ""
            if call.get("status") == "success":
                payload = self._extract_result_payload(call.get("response", {}))
                if isinstance(payload, dict):
                    out = str(payload.get("output", "") or "")
                elif isinstance(payload, str):
                    out = payload
            verdict = self._classify_dns_probe_output(out)
            results.append(
                {
                    "endpoint": host,
                    "dns_verdict": verdict,
                    "output_excerpt": out[:4000],
                }
            )
        return {"results": results, "mcp_hits": mcp_hits}

    @staticmethod
    def _apply_debug_dns_to_findings(
        findings: List[Dict[str, Any]],
        debug_results: List[Dict[str, Any]],
        external_evals: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Attach DNS probe evidence; strengthen verdict when graph/AWS already missing endpoint."""
        if not debug_results or not findings:
            return findings
        not_found_hosts = {
            str(e.get("endpoint", "")).lower()
            for e in external_evals
            if isinstance(e, dict) and str(e.get("existence_verdict", "")).lower() == "not_found"
        }
        for probe in debug_results:
            if not isinstance(probe, dict):
                continue
            host = str(probe.get("endpoint", "")).strip().lower()
            verdict = str(probe.get("dns_verdict", "")).strip().lower()
            excerpt = str(probe.get("output_excerpt", ""))[:500]
            if verdict not in ("nxdomain_or_nodata",):
                continue
            for item in findings:
                if not isinstance(item, dict):
                    continue
                dep = str(item.get("dependency", "")).strip().lower()
                if not dep:
                    continue
                if dep in host or host.startswith(dep) or host.split(".")[0] == dep.split(".")[0]:
                    fts = item.setdefault("failure_types", [])
                    if "dns_probe_failure" not in fts:
                        fts.append("dns_probe_failure")
                    if host in not_found_hosts or str(item.get("status", "")).lower() == "confirmed_failed":
                        item["status"] = "confirmed_failed"
                    item.setdefault("evidence", []).append(
                        {
                            "source": "debug_pod_dns",
                            "signal": verdict,
                            "message_excerpt": excerpt,
                        }
                    )
                    break
        return findings

    @staticmethod
    def _classify_dependency_endpoint(host: str) -> Dict[str, Any]:
        normalized = (host or "").strip().lower()
        classification: Dict[str, Any] = {
            "endpoint": normalized,
            "cloud": "unknown",
            "resource_type": "unknown",
            "region": None,
            "resource_hint": normalized.split(".", 1)[0] if normalized else "",
        }
        region_match = re.search(r"\.([a-z]{2}-[a-z0-9-]+-\d)\.amazonaws\.com", normalized)
        if region_match:
            classification["region"] = region_match.group(1)
        if ".elb." in normalized and normalized.endswith(".amazonaws.com"):
            classification["cloud"] = "aws"
            classification["resource_type"] = "load_balancer"
        elif ".rds." in normalized and normalized.endswith(".amazonaws.com"):
            classification["cloud"] = "aws"
            classification["resource_type"] = "rds"
        elif ".cache." in normalized and normalized.endswith(".amazonaws.com"):
            classification["cloud"] = "aws"
            classification["resource_type"] = "elasticache"
        elif ".s3." in normalized and normalized.endswith(".amazonaws.com"):
            classification["cloud"] = "aws"
            classification["resource_type"] = "s3"
        return classification

    @staticmethod
    def _has_direct_dependency_failure_signal(logs: List[Dict[str, Any]]) -> bool:
        for entry in logs[:200]:
            if not isinstance(entry, dict):
                continue
            msg = str(entry.get("message", "")).lower()
            if not msg:
                continue
            if any(token in msg for token in ("no such host", "temporary failure in name resolution", "nxdomain")):
                if any(token in msg for token in (".elb.", ".rds.", ".cache.", "amazonaws.com")):
                    return True
        return False

    def _build_dependency_findings(
        self,
        services_checked: List[str],
        merged_logs: List[Dict[str, Any]],
        dependency_kubernetes_context: Dict[str, Any],
        aws_diagnostics: List[Any],
        external_dependency_evaluations: Optional[List[Dict[str, Any]]] = None,
        primary_service: str = "",
    ) -> List[Dict[str, Any]]:
        findings: Dict[str, Dict[str, Any]] = {}
        excluded_aliases = set(self._build_service_aliases(primary_service))

        def _ensure(service_name: str) -> Dict[str, Any]:
            key = self._normalize_dependency_key(service_name) or service_name or "unknown"
            if key not in findings:
                findings[key] = {
                    "dependency": key,
                    "status": "inconclusive",
                    "failure_types": [],
                    "evidence": [],
                }
            return findings[key]

        for name in services_checked[:20]:
            if isinstance(name, str) and name.strip():
                if self._sanitize_k8s_service_name(name) in excluded_aliases:
                    continue
                _ensure(name)

        for entry in merged_logs[:300]:
            if not isinstance(entry, dict):
                continue
            msg = str(entry.get("message", ""))
            source = self._sanitize_k8s_service_name(str(entry.get("source", "")))
            matched_service = source if source in findings else None
            lower_msg = msg.lower()
            if not matched_service:
                for svc in findings.keys():
                    if svc and svc in lower_msg:
                        matched_service = svc
                        break
            if matched_service and matched_service in excluded_aliases:
                continue
            if not matched_service:
                matched_service = "unknown"
            record = _ensure(matched_service)

            failure_type = self._classify_failure_type_from_message(msg)
            if failure_type:
                if failure_type not in record["failure_types"]:
                    record["failure_types"].append(failure_type)
                record["status"] = "confirmed_failed"
                if len(record["evidence"]) < 4:
                    record["evidence"].append(
                        {
                            "source": "kubernetes_logs",
                            "signal": failure_type,
                            "message_excerpt": msg[:220],
                            "timestamp": entry.get("timestamp"),
                        }
                    )

        for dep_name, dep_ctx in dependency_kubernetes_context.items():
            if not isinstance(dep_ctx, dict):
                continue
            if self._sanitize_k8s_service_name(dep_name) in excluded_aliases:
                continue
            record = _ensure(dep_name)
            runtime = dep_ctx.get("runtime", {})
            runtime_blob = json.dumps(runtime, default=str).lower() if runtime else ""
            if not runtime_blob:
                continue
            if any(token in runtime_blob for token in ("crashloopbackoff", "imagepullbackoff", '"phase": "failed"')):
                record["status"] = "confirmed_failed"
                if "runtime_failure" not in record["failure_types"]:
                    record["failure_types"].append("runtime_failure")
                if len(record["evidence"]) < 4:
                    record["evidence"].append(
                        {
                            "source": "kubernetes_runtime",
                            "signal": "runtime_failure",
                            "message_excerpt": runtime_blob[:220],
                        }
                    )
            elif record["status"] == "inconclusive" and any(
                token in runtime_blob for token in ('"phase": "running"', '"ready": true', "available")
            ):
                record["status"] = "confirmed_healthy"
                if len(record["evidence"]) < 4:
                    record["evidence"].append(
                        {
                            "source": "kubernetes_runtime",
                            "signal": "healthy_runtime",
                            "message_excerpt": runtime_blob[:220],
                        }
                    )

        for diag in aws_diagnostics[:10]:
            diag_text = json.dumps(diag, default=str)
            lower_diag = diag_text.lower()
            target = "aws_dependency"
            host_match = re.search(r"[a-z0-9.-]+\.(?:elb|rds|cache)\.amazonaws\.com", lower_diag)
            if host_match:
                target = host_match.group(0)
            record = _ensure(target)
            if any(token in lower_diag for token in ("failed", "unhealthy", "timeout", "refused", "no such host", "nxdomain")):
                record["status"] = "confirmed_failed"
                if "network_dependency_failure" not in record["failure_types"]:
                    record["failure_types"].append("network_dependency_failure")
                if len(record["evidence"]) < 4:
                    record["evidence"].append(
                        {
                            "source": "aws_network_diagnostics",
                            "signal": "network_dependency_failure",
                            "message_excerpt": diag_text[:220],
                        }
                    )
            elif record["status"] == "inconclusive" and any(
                token in lower_diag for token in ("healthy", "available", "ok", "success")
            ):
                record["status"] = "confirmed_healthy"
                if len(record["evidence"]) < 4:
                    record["evidence"].append(
                        {
                            "source": "aws_network_diagnostics",
                            "signal": "network_dependency_healthy",
                            "message_excerpt": diag_text[:220],
                        }
                    )

        for evaluation in (external_dependency_evaluations or [])[:12]:
            if not isinstance(evaluation, dict):
                continue
            endpoint = str(evaluation.get("endpoint", "")).strip().lower()
            if not endpoint:
                continue
            record = _ensure(endpoint)
            verdict = str(evaluation.get("existence_verdict", "")).strip().lower()
            if verdict == "not_found":
                record["status"] = "confirmed_failed"
                if "endpoint_not_found" not in record["failure_types"]:
                    record["failure_types"].append("endpoint_not_found")
                if len(record["evidence"]) < 4:
                    record["evidence"].append(
                        {
                            "source": "external_dependency_lookup",
                            "signal": "endpoint_not_found",
                            "message_excerpt": json.dumps(evaluation, default=str)[:220],
                        }
                    )
            elif verdict == "exists" and record["status"] == "inconclusive":
                record["status"] = "confirmed_healthy"
                if len(record["evidence"]) < 4:
                    record["evidence"].append(
                        {
                            "source": "external_dependency_lookup",
                            "signal": "endpoint_exists",
                            "message_excerpt": json.dumps(evaluation, default=str)[:220],
                        }
                    )

        ordered = sorted(
            findings.values(),
            key=lambda item: (
                0 if item.get("status") == "confirmed_failed" else 1 if item.get("status") == "inconclusive" else 2,
                str(item.get("dependency", "")),
            ),
        )
        return ordered[:20]

    async def _ensure_graph_context_for_remediation(self, state: SREMultiAgentState) -> None:
        """If Cartography returned no rows during aggregation, retry graph_get_service_dependencies once."""
        gc = state.get("graph_context")
        if not isinstance(gc, dict):
            gc = {"dependencies": [], "recent_incidents": []}
            state["graph_context"] = gc
        deps = gc.get("dependencies")
        if isinstance(deps, list) and deps:
            return
        if not settings.SRE_USE_MCP_FOR_CONTEXT_AGGREGATION:
            return
        target = state.get("target_service") or ""
        ns, svc = self._split_target_service(target)
        if not svc or svc.lower() == "all":
            return
        contracts = [
            {
                "provider": "graph",
                "server": "graph-server",
                "tool": "graph_get_service_dependencies",
                "arguments": {
                    "service_name": svc,
                    "namespace": ns or None,
                    "limit": 20,
                },
            }
        ]
        call = await self.mcp.call_first_available_contract(contracts, session_id=state.get("incident_id", ""))
        if call.get("status") != "success":
            return
        normalized = self._normalize_graph_dependencies(call.get("response", {}))
        if not normalized:
            return
        gc["dependencies"] = normalized
        if isinstance(state.get("context_sources"), dict):
            state["context_sources"]["graph"] = {
                "provider": call.get("provider"),
                "server": call.get("server"),
                "tool": "graph_get_service_dependencies",
            }

    def _extract_graph_remediation_facts(self, state: SREMultiAgentState) -> Dict[str, Any]:
        """Derive concrete Kubernetes identifiers from Cartography graph rows, Istio, and target_service."""
        ts_ns, ts_svc = self._split_target_service(state.get("target_service") or "")
        k8s_service = ts_svc or ""
        namespace: Optional[str] = ts_ns or None
        pod_names: List[str] = []

        graph_ctx = state.get("graph_context") or {}
        deps = graph_ctx.get("dependencies") or []
        if isinstance(deps, list):
            for row in deps:
                if not isinstance(row, dict):
                    continue
                row_ns = row.get("namespace")
                row_svc = row.get("service_name")
                if row_ns and not namespace:
                    namespace = row_ns
                if row_svc and not k8s_service:
                    k8s_service = row_svc
                for p in row.get("pods") or []:
                    if isinstance(p, dict) and p.get("name"):
                        pod_names.append(str(p["name"]))
                        pns = p.get("namespace")
                        if pns and not namespace:
                            namespace = str(pns)

        istio = state.get("istio_context") or {}
        if isinstance(istio, dict):
            if istio.get("namespace") and not namespace:
                namespace = istio.get("namespace")
            if istio.get("service_name") and not k8s_service:
                k8s_service = str(istio["service_name"])
            for p in istio.get("pods") or []:
                if isinstance(p, dict) and p.get("name"):
                    pod_names.append(str(p["name"]))

        seen: Dict[str, None] = {}
        unique_pods: List[str] = []
        for name in pod_names:
            if name not in seen:
                seen[name] = None
                unique_pods.append(name)
        pod_names = unique_pods[:8]

        deployment = k8s_service
        additional_ctx = state.get("additional_context", {}) if isinstance(state.get("additional_context"), dict) else {}
        kubernetes_ctx = additional_ctx.get("kubernetes", {}) if isinstance(additional_ctx.get("kubernetes"), dict) else {}
        dependency_k8s = (
            additional_ctx.get("dependency_kubernetes_context", {})
            if isinstance(additional_ctx.get("dependency_kubernetes_context"), dict)
            else {}
        )
        workloads = kubernetes_ctx.get("workloads", []) if isinstance(kubernetes_ctx.get("workloads"), list) else []
        runtime = kubernetes_ctx.get("runtime", {}) if isinstance(kubernetes_ctx.get("runtime"), dict) else {}
        for workload in workloads[:40]:
            if not isinstance(workload, dict):
                continue
            w_name = workload.get("name")
            w_ns = workload.get("namespace")
            if isinstance(w_ns, str) and w_ns and not namespace:
                namespace = w_ns
            if isinstance(w_name, str) and w_name:
                if workload.get("kind") in ("Deployment", "StatefulSet") and (not deployment or deployment == k8s_service):
                    deployment = w_name
                if workload.get("kind") == "Pod":
                    pod_names.append(w_name)
        for pod in runtime.get("pods", []) if isinstance(runtime.get("pods"), list) else []:
            if not isinstance(pod, dict):
                continue
            name = pod.get("name")
            pns = pod.get("namespace")
            if isinstance(name, str) and name:
                pod_names.append(name)
            if isinstance(pns, str) and pns and not namespace:
                namespace = pns
        for dep_ctx in dependency_k8s.values():
            if not isinstance(dep_ctx, dict):
                continue
            dep_ns = dep_ctx.get("namespace")
            if isinstance(dep_ns, str) and dep_ns and not namespace:
                namespace = dep_ns
            dep_workloads = dep_ctx.get("workloads", [])
            if isinstance(dep_workloads, list):
                for workload in dep_workloads[:20]:
                    if not isinstance(workload, dict):
                        continue
                    w_name = workload.get("name")
                    if workload.get("kind") in ("Deployment", "StatefulSet") and isinstance(w_name, str) and w_name and (not deployment or deployment == k8s_service):
                        deployment = w_name
                    if workload.get("kind") == "Pod" and isinstance(w_name, str) and w_name:
                        pod_names.append(w_name)
            dep_runtime = dep_ctx.get("runtime", {})
            if isinstance(dep_runtime, dict):
                for pod in dep_runtime.get("pods", []) if isinstance(dep_runtime.get("pods"), list) else []:
                    if isinstance(pod, dict) and pod.get("name"):
                        pod_names.append(str(pod["name"]))
                    if isinstance(pod, dict) and pod.get("namespace") and not namespace:
                        namespace = str(pod["namespace"])

        seen = set()
        unique_pods = []
        for name in pod_names:
            if name in seen:
                continue
            seen.add(name)
            unique_pods.append(name)
        pod_names = unique_pods[:8]
        return {
            "kubernetes_service_name": k8s_service,
            "namespace": namespace,
            "deployment_name": deployment,
            "pod_names": pod_names,
            "pod_name_example": pod_names[0] if pod_names else None,
            "pod_name_secondary": pod_names[1] if len(pod_names) > 1 else None,
        }

    def _apply_remediation_graph_facts(self, plan: Dict[str, Any], facts: Dict[str, Any]) -> Dict[str, Any]:
        """Replace generic kubectl placeholders when Cartography / Istio provided concrete values."""

        ns = facts.get("namespace")
        deploy = facts.get("deployment_name") or facts.get("kubernetes_service_name") or ""
        pod_ex = facts.get("pod_name_example")
        pod2 = facts.get("pod_name_secondary")
        svc = facts.get("kubernetes_service_name") or ""
        mongodb_host = ""
        dep_sources: List[str] = []
        for key in ("commands", "step_by_step_commands", "step_by_step_instructions", "impacted_services"):
            val = plan.get(key)
            if isinstance(val, list):
                dep_sources.extend([str(v) for v in val if isinstance(v, str)])
            elif isinstance(val, str):
                dep_sources.append(val)
        for line in dep_sources[:80]:
            match = re.search(r"([a-z0-9.-]+(?:mongo|mongodb)[a-z0-9.-]*)", line.lower())
            if match:
                mongodb_host = match.group(1)
                break

        def _repl(text: str) -> str:
            if not isinstance(text, str):
                return text
            out = text
            if ns:
                out = out.replace("<namespace>", ns)
                out = out.replace("<NAMESPACE>", ns)
            if pod_ex:
                out = out.replace("<pod_name>", pod_ex)
                out = out.replace("<pod-name>", pod_ex)
                out = out.replace("<POD_NAME>", pod_ex)
            if pod2:
                out = out.replace("<another_running_pod>", pod2)
                out = out.replace("<another_pod>", pod2)
            if deploy:
                out = out.replace("<deployment_name>", deploy)
                out = out.replace("<deployment>", deploy)
                out = out.replace("<DEPLOYMENT>", deploy)
            if svc:
                out = out.replace("<service_name>", svc)
                out = out.replace("<service>", svc)
                if "rabbit" in svc.lower():
                    out = out.replace("<rabbitmq_service_name>", svc)
            if ns:
                out = out.replace("<rabbitmq_namespace>", ns)
            if mongodb_host:
                out = out.replace("<mongodb_hostname>", mongodb_host)
            return out

        list_keys = (
            "commands",
            "step_by_step_commands",
            "step_by_step_instructions",
            "immediate_mitigation",
            "long_term_fix",
            "preventative_measures",
            "preventative_actions",
            "rollback_plan",
            "impacted_services",
        )
        for key in list_keys:
            val = plan.get(key)
            if isinstance(val, list):
                plan[key] = [_repl(x) if isinstance(x, str) else x for x in val]
            elif isinstance(val, str):
                plan[key] = _repl(val)

        ra = plan.get("risk_assessment")
        if isinstance(ra, str):
            plan["risk_assessment"] = _repl(ra)

        return plan

    def _build_terminal_remediation_template(
        self, state: SREMultiAgentState, facts: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Deterministic remediation for conclusively diagnosed failure classes."""
        category = str(state.get("root_cause_category", "")).strip().upper()
        ns = facts.get("namespace")
        deploy = facts.get("deployment_name") or facts.get("kubernetes_service_name") or "<deployment>"
        if ns:
            restart_cmd = f"kubectl rollout restart deployment/{deploy} -n {ns}"
            status_cmd = f"kubectl rollout status deployment/{deploy} -n {ns} --timeout=180s"
            rollback_cmd = f"kubectl rollout undo deployment/{deploy} -n {ns}"
        else:
            restart_cmd = f"kubectl rollout restart deployment/{deploy} -n <namespace>"
            status_cmd = f"kubectl rollout status deployment/{deploy} -n <namespace> --timeout=180s"
            rollback_cmd = f"kubectl rollout undo deployment/{deploy} -n <namespace>"

        impacted_services = [str(state.get("target_service") or ""), str(state.get("failing_service") or "")]
        impacted_services = [svc for svc in dict.fromkeys(impacted_services) if svc]

        if category == "DNS_RESOURCE_MISSING":
            dependency_host = str(state.get("terminal_dependency") or "").strip()
            env_key = "DEPENDENCY_ENDPOINT"
            if ns:
                set_env_cmd = f"kubectl set env deployment/{deploy} -n {ns} {env_key}=<valid-endpoint-hostname>"
            else:
                set_env_cmd = (
                    f"kubectl set env deployment/{deploy} -n <namespace> "
                    f"{env_key}=<valid-endpoint-hostname>"
                )

            immediate_mitigation = [
                f"Replace the invalid endpoint hostname for {env_key} in the workload configuration.",
                "Restart the workload so new endpoint configuration is applied.",
            ]
            if dependency_host:
                immediate_mitigation.insert(
                    0,
                    f"Treat '{dependency_host}' as invalid/missing and remove it from active configuration.",
                )

            return {
                "immediate_mitigation": immediate_mitigation,
                "long_term_fix": [
                    "Restore the missing dependency endpoint through infrastructure-as-code and DNS automation.",
                    "Bind application configuration to managed service discovery outputs instead of hard-coded hostnames.",
                    "Add CI/CD validation that blocks deployments referencing non-existent dependency endpoints.",
                ],
                "preventative_actions": [
                    "Add an RCA terminality rule: inventory missing + DNS failure should short-circuit further investigation.",
                    "Continuously reconcile graph inventory with cloud resources and alert on drift for dependency endpoints.",
                    "Add startup synthetic checks that resolve dependency endpoints before pod readiness.",
                ],
                "step_by_step_instructions": [
                    f"Update {env_key} to a valid dependency endpoint from approved config/secret source.",
                    "Roll out the deployment to apply the fixed endpoint.",
                    "Confirm rollout completes and service returns to healthy state.",
                ],
                "commands": [set_env_cmd, restart_cmd, status_cmd],
                "step_by_step_commands": [set_env_cmd, restart_cmd, status_cmd],
                "impacted_services": impacted_services,
                "rollback_plan": [
                    "Undo deployment rollout if errors persist after endpoint correction.",
                    rollback_cmd,
                ],
                "risk_assessment": (
                    "Primary risk is continued service outage if endpoint remains invalid. "
                    "Secondary risk is applying an incorrect replacement hostname; use approved source-of-truth."
                ),
            }

        if category == "RUNTIME_FAILURE":
            config_key = str(
                ((state.get("additional_context") or {}).get("runtime_required_config_key"))
                or "REQUIRED_CONFIG_KEY"
            )
            if ns:
                set_env_cmd = (
                    f"kubectl set env deployment/{deploy} -n {ns} "
                    f"{config_key}=<value-from-approved-secret-source>"
                )
            else:
                set_env_cmd = (
                    f"kubectl set env deployment/{deploy} -n <namespace> "
                    f"{config_key}=<value-from-approved-secret-source>"
                )
            return {
                "immediate_mitigation": [
                    f"Restore required runtime configuration `{config_key}` from the approved secret/config source.",
                    "Roll back to the last known-good revision if the correct value cannot be restored immediately.",
                ],
                "long_term_fix": [
                    f"Move `{config_key}` to managed secret/config delivery with deployment-time validation.",
                    "Add startup contract tests that fail build/deploy when required runtime config is missing.",
                    "Make required configuration keys explicit in runtime bootstrap validation and service runbook.",
                ],
                "preventative_actions": [
                    "Gate deployments on required env/config presence checks in CI/CD.",
                    "Add pre-start validation that emits deterministic error code for missing required config.",
                    "Document emergency rollback and secret rotation procedure for startup auth/config failures.",
                ],
                "step_by_step_instructions": [
                    f"Set `{config_key}` from source-of-truth secret/config for the target deployment.",
                    "Roll out the deployment with corrected configuration.",
                    "Confirm rollout reaches a healthy state.",
                ],
                "commands": [set_env_cmd, restart_cmd, status_cmd],
                "step_by_step_commands": [set_env_cmd, restart_cmd, status_cmd],
                "impacted_services": impacted_services,
                "rollback_plan": [
                    "Rollback deployment immediately if corrected config cannot be applied safely.",
                    rollback_cmd,
                ],
                "risk_assessment": (
                    "Main risk is prolonged outage if required runtime configuration remains unset or invalid. "
                    "Secondary risk is accidental credential exposure during emergency fixes; use secret-safe delivery paths."
                ),
            }

        return None

    def _strip_investigative_actions_for_terminal(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """Remove exploratory/debugging actions when root cause is already conclusive."""
        if not isinstance(plan, dict):
            return plan

        def _is_investigative(text: str) -> bool:
            lower = str(text or "").lower()
            return any(token in lower for token in _INVESTIGATION_TEXT_TOKENS)

        for key in ("commands", "step_by_step_commands", "step_by_step_instructions"):
            value = plan.get(key)
            if not isinstance(value, list):
                continue
            plan[key] = [
                item
                for item in value
                if not (isinstance(item, str) and _is_investigative(item))
            ]
        return plan

    def _build_default_remediation_commands(self, facts: Dict[str, Any]) -> List[str]:
        """Deterministic kubectl hints when the LLM JSON parse fails."""
        svc = facts.get("kubernetes_service_name") or "affected-service"
        ns = facts.get("namespace")
        deploy = facts.get("deployment_name") or svc
        pod_ex = facts.get("pod_name_example")
        if ns:
            lines = [
                f"kubectl get pods -n {ns} | grep {svc}",
                f"kubectl get deployment {deploy} -n {ns} -o wide",
            ]
            if pod_ex:
                lines.append(f"kubectl describe pod {pod_ex} -n {ns}")
            else:
                lines.append(f"kubectl describe deployment {deploy} -n {ns}")
            lines.append(f"kubectl get events -n {ns} --sort-by=.lastTimestamp | tail -30")
            return lines
        return [
            f"kubectl get pods -A | grep {svc}",
            f"kubectl get deployment -A | grep {svc}",
        ]

    @staticmethod
    def _parse_memory_to_mi(value: str) -> Optional[float]:
        if not isinstance(value, str) or not value:
            return None
        token = value.strip().lower()
        try:
            if token.endswith("gi"):
                return float(token[:-2]) * 1024.0
            if token.endswith("mi"):
                return float(token[:-2])
            if token.endswith("ki"):
                return float(token[:-2]) / 1024.0
            if token.endswith("g"):
                return float(token[:-1]) * 953.674
            if token.endswith("m"):
                return float(token[:-1]) / (1024.0 * 1024.0)
            return float(token) / (1024.0 * 1024.0)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_cpu_to_millicores(value: str) -> Optional[float]:
        if not isinstance(value, str) or not value:
            return None
        token = value.strip().lower()
        try:
            if token.endswith("m"):
                return float(token[:-1])
            return float(token) * 1000.0
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _format_mi(value: float) -> str:
        rounded = int((max(64.0, value) + 31) // 32 * 32)
        return f"{rounded}Mi"

    @staticmethod
    def _format_cpu_m(value: float) -> str:
        rounded = int((max(50.0, value) + 24) // 25 * 25)
        return f"{rounded}m"

    def _derive_oom_resource_recommendations(self, state: SREMultiAgentState, facts: Dict[str, Any]) -> Dict[str, Any]:
        metrics = state.get("metrics", {}) if isinstance(state.get("metrics"), dict) else {}
        queries = metrics.get("queries", {}) if isinstance(metrics.get("queries"), dict) else {}
        mem_peak_mi: Optional[float] = None
        cpu_peak_cores: Optional[float] = None

        mem_q = queries.get("memory_working_set_bytes_by_pod_container", {})
        if isinstance(mem_q, dict):
            for series in mem_q.get("series", [])[:20]:
                values = series.get("values", []) if isinstance(series, dict) else []
                for point in values[-20:]:
                    if isinstance(point, list) and len(point) >= 2:
                        try:
                            mem_mi = float(point[1]) / (1024.0 * 1024.0)
                            mem_peak_mi = max(mem_peak_mi or 0.0, mem_mi)
                        except (TypeError, ValueError):
                            continue

        cpu_q = queries.get("cpu_usage_cores_by_pod_container", {})
        if isinstance(cpu_q, dict):
            for series in cpu_q.get("series", [])[:20]:
                values = series.get("values", []) if isinstance(series, dict) else []
                for point in values[-20:]:
                    if isinstance(point, list) and len(point) >= 2:
                        try:
                            cpu_val = float(point[1])
                            cpu_peak_cores = max(cpu_peak_cores or 0.0, cpu_val)
                        except (TypeError, ValueError):
                            continue

        workload_context = (state.get("additional_context") or {}).get("kubernetes", {})
        current_mem_req_mi = None
        current_mem_lim_mi = None
        current_cpu_req_m = None
        current_cpu_lim_m = None
        for workload in workload_context.get("workloads", []) if isinstance(workload_context, dict) else []:
            if not isinstance(workload, dict):
                continue
            for c in workload.get("containers", []) if isinstance(workload.get("containers"), list) else []:
                if not isinstance(c, dict):
                    continue
                req = c.get("requests", {}) if isinstance(c.get("requests"), dict) else {}
                lim = c.get("limits", {}) if isinstance(c.get("limits"), dict) else {}
                mr = self._parse_memory_to_mi(str(req.get("memory", "")))
                ml = self._parse_memory_to_mi(str(lim.get("memory", "")))
                cr = self._parse_cpu_to_millicores(str(req.get("cpu", "")))
                cl = self._parse_cpu_to_millicores(str(lim.get("cpu", "")))
                if mr is not None:
                    current_mem_req_mi = max(current_mem_req_mi or 0.0, mr)
                if ml is not None:
                    current_mem_lim_mi = max(current_mem_lim_mi or 0.0, ml)
                if cr is not None:
                    current_cpu_req_m = max(current_cpu_req_m or 0.0, cr)
                if cl is not None:
                    current_cpu_lim_m = max(current_cpu_lim_m or 0.0, cl)

        rec_mem_req = None
        rec_mem_lim = None
        if mem_peak_mi is not None:
            rec_mem_req = max((mem_peak_mi * 1.25), current_mem_req_mi or 0.0)
            rec_mem_lim = max((mem_peak_mi * 1.60), current_mem_lim_mi or 0.0)

        rec_cpu_req = None
        rec_cpu_lim = None
        if cpu_peak_cores is not None:
            cpu_peak_m = cpu_peak_cores * 1000.0
            rec_cpu_req = max((cpu_peak_m * 1.25), current_cpu_req_m or 0.0)
            rec_cpu_lim = max((cpu_peak_m * 1.75), current_cpu_lim_m or 0.0)

        deployment = facts.get("deployment_name") or facts.get("kubernetes_service_name") or ""
        namespace = facts.get("namespace")
        set_resources_cmd = ""
        if deployment and namespace and rec_mem_req and rec_mem_lim and rec_cpu_req and rec_cpu_lim:
            set_resources_cmd = (
                f"kubectl set resources deployment/{deployment} -n {namespace} "
                f"--requests=cpu={self._format_cpu_m(rec_cpu_req)},memory={self._format_mi(rec_mem_req)} "
                f"--limits=cpu={self._format_cpu_m(rec_cpu_lim)},memory={self._format_mi(rec_mem_lim)}"
            )

        return {
            "detected_oom_signal": "oom" in (state.get("hypothesis", "").lower()),
            "memory_peak_mi": round(mem_peak_mi, 2) if mem_peak_mi is not None else None,
            "cpu_peak_cores": round(cpu_peak_cores, 4) if cpu_peak_cores is not None else None,
            "current_memory_request_mi": round(current_mem_req_mi, 2) if current_mem_req_mi is not None else None,
            "current_memory_limit_mi": round(current_mem_lim_mi, 2) if current_mem_lim_mi is not None else None,
            "recommended_memory_request": self._format_mi(rec_mem_req) if rec_mem_req else None,
            "recommended_memory_limit": self._format_mi(rec_mem_lim) if rec_mem_lim else None,
            "recommended_cpu_request": self._format_cpu_m(rec_cpu_req) if rec_cpu_req else None,
            "recommended_cpu_limit": self._format_cpu_m(rec_cpu_lim) if rec_cpu_lim else None,
            "kubectl_set_resources_command": set_resources_cmd,
        }

    async def _query_servicenow_history(self, target_service: str) -> List[Dict[str, Any]]:
        try:
            query = f"short_descriptionLIKE{target_service}^ORDERBYDESCsys_created_on"
            records = await self.snow.client.get("incident", query=query, limit=5)
            if isinstance(records, list):
                return records
            return [records] if records else []
        except Exception as exc:
            logger.warning("ServiceNow history query failed: %s", exc)
            return []

    async def _rca_agent_node(self, state: SREMultiAgentState) -> SREMultiAgentState:
        state["current_node"] = "rca_agent"
        logs_prompt_view = self._build_logs_prompt_view(state.get("logs", []))
        metrics_prompt_view = self._build_metrics_prompt_view(state.get("metrics", {}))
        log_digest = self._build_log_evidence_digest(state.get("logs", []))
        metrics_digest = self._build_metrics_evidence_digest(state.get("metrics", {}))
        rca = await self._ask_json_from_catalog(
            prompt_key="rca_agent",
            variables={
                "incident_title": state.get("title", ""),
                "incident_description": state.get("description", ""),
                "target_service": state.get("target_service", ""),
                "context_summary": state.get("context_summary", ""),
                "logs_json": json.dumps(logs_prompt_view, default=str),
                "metrics_json": json.dumps(metrics_prompt_view, default=str),
                "log_evidence_digest_json": json.dumps(log_digest, default=str),
                "metrics_evidence_digest_json": json.dumps(metrics_digest, default=str),
                "alerts_json": json.dumps(state.get("alerts", []), default=str)[:3000],
                "rag_docs_json": json.dumps(state.get("rag_results", {}).get("results", []), default=str)[:3000],
                "istio_context_json": json.dumps(state.get("istio_context", {}), default=str)[:2000],
                "graph_context_json": json.dumps(state.get("graph_context", {}), default=str)[:2000],
                "extracted_dependencies_json": json.dumps(state.get("extracted_dependencies", []), default=str)[:3000],
                "metric_anomalies_json": json.dumps(state.get("metric_anomalies", []), default=str)[:3000],
                "observability_missing_json": json.dumps(state.get("observability_missing_signals", []), default=str),
                "dependency_findings_json": json.dumps(
                    (state.get("additional_context") or {}).get("dependency_findings", []),
                    default=str,
                )[:4000],
                "external_dependency_evaluations_json": json.dumps(
                    (state.get("additional_context") or {}).get("external_dependency_evaluations", []),
                    default=str,
                )[:4000],
                "debug_pod_dns_json": json.dumps(
                    (state.get("additional_context") or {}).get("debug_pod_dns_checks", []),
                    default=str,
                )[:4000],
            },
            state=state,
            default={
                "failing_service": state.get("target_service", "unknown"),
                "hypothesis": "Insufficient evidence",
                "evidence": [],
                "anomalies": [],
            },
        )
        state["failing_service"] = rca.get("failing_service", state.get("target_service", "unknown"))
        if not state["failing_service"]:
            state["failing_service"] = rca.get("suspected_component", state.get("target_service", "unknown"))
        root_cause = rca.get("root_cause") or rca.get("root_cause_explanation") or rca.get("hypothesis")
        state["root_cause"] = root_cause or "Insufficient evidence"
        state["hypothesis"] = state["root_cause"]
        raw_confidence = rca.get("confidence", 0.0)
        try:
            state["rca_confidence"] = max(0.0, min(1.0, float(raw_confidence)))
        except (TypeError, ValueError):
            state["rca_confidence"] = 0.0
        state["llm_terminal_candidate"] = bool(rca.get("is_terminal", False))
        state["is_terminal"] = False
        state["requires_more_data"] = True
        state["root_cause_category"] = (
            str(
                rca.get("root_cause_category")
                or rca.get("category")
                or state.get("root_cause_category")
                or "unknown"
            )
        )
        state["terminal_dependency"] = rca.get("terminal_dependency")
        terminal_evidence = rca.get("terminal_evidence", [])
        if isinstance(terminal_evidence, list):
            state["terminal_evidence"] = [str(item) for item in terminal_evidence if str(item).strip()][:10]
        state["evidence"] = (
            rca.get("evidence")
            or rca.get("evidence_sources")
            or rca.get("confidence_indicators")
            or []
        )
        state["anomalies"] = rca.get("anomalies", [])
        if rca.get("dependency_chain"):
            state.setdefault("evidence", [])
            if isinstance(state["evidence"], list):
                state["evidence"].append(f"dependency_chain={rca.get('dependency_chain')}")
        if rca.get("failure_type"):
            state.setdefault("additional_context", {})
            if isinstance(state["additional_context"], dict):
                state["additional_context"]["failure_type"] = rca.get("failure_type")
        self._apply_terminal_conclusion(state)
        self._apply_runtime_failure_guardrail(state)
        await self._persist_state(state)
        return state

    async def _critique_agent_node(self, state: SREMultiAgentState) -> SREMultiAgentState:
        state["current_node"] = "critique_agent"
        log_digest = self._build_log_evidence_digest(state.get("logs", []))
        metrics_digest = self._build_metrics_evidence_digest(state.get("metrics", {}))
        critique = await self._ask_json_from_catalog(
            prompt_key="critique_agent",
            variables={
                "hypothesis": state.get("hypothesis", ""),
                "evidence_json": json.dumps(state.get("evidence", []), default=str),
                "anomalies_json": json.dumps(state.get("anomalies", []), default=str),
                "log_evidence_digest_json": json.dumps(log_digest, default=str),
                "metrics_evidence_digest_json": json.dumps(metrics_digest, default=str),
            },
            state=state,
            default={"critique_feedback": "No critique generated", "alternate_causes": []},
        )
        state["critique_feedback"] = critique.get("critique_feedback") or critique.get("critique_summary", "")
        state["alternate_causes"] = critique.get("alternate_causes") or critique.get("alternative_causes", [])
        await self._persist_state(state)
        return state

    async def _confidence_scoring_node(self, state: SREMultiAgentState) -> SREMultiAgentState:
        state["current_node"] = "confidence_scoring"
        self._apply_terminal_conclusion(state)
        terminal = self._derive_terminal_conclusion(state)
        hard_dependency_failure_signal = self._has_direct_dependency_failure_signal(state.get("logs", []))
        evidence_quality = min(1.0, len(state.get("evidence", [])) / 5.0)
        metric_correlation = (
            1.0
            if state.get("metrics") and state.get("anomalies")
            else 0.7 if hard_dependency_failure_signal else 0.4
        )
        log_matches = min(1.0, len(state.get("alerts", [])) / 10.0)
        rag_scores = [float(item.get("score", 0.0)) for item in state.get("rag_results", {}).get("results", [])]
        kb_similarity = min(1.0, max(rag_scores)) if rag_scores else 0.2
        critique_validation = 0.8 if state.get("critique_feedback") else 0.3
        missing_signals = state.get("observability_missing_signals", [])
        scoring_missing_signals = [
            signal
            for signal in missing_signals
            if not (hard_dependency_failure_signal and signal == "metric_anomalies")
        ]
        coverage_score = max(0.0, 1.0 - (0.12 * len(scoring_missing_signals)))

        deterministic_components = {
            "evidence_quality": round(evidence_quality, 4),
            "metric_correlation": round(metric_correlation, 4),
            "log_matches": round(log_matches, 4),
            "knowledge_base_similarity": round(kb_similarity, 4),
            "critique_validation": round(critique_validation, 4),
            "observability_coverage": round(coverage_score, 4),
            "hard_dependency_failure_signal": 1.0 if hard_dependency_failure_signal else 0.0,
        }
        deterministic_score = (
            deterministic_components["evidence_quality"] * 0.25
            + deterministic_components["metric_correlation"] * 0.20
            + deterministic_components["log_matches"] * 0.20
            + deterministic_components["knowledge_base_similarity"] * 0.15
            + deterministic_components["critique_validation"] * 0.10
            + deterministic_components["observability_coverage"] * 0.10
        )

        if terminal.get("is_terminal"):
            override_score = float(terminal.get("confidence_override", 0.95))
            final_score = round(max(deterministic_score, override_score), 4)
            state["confidence_components"] = {
                "deterministic": deterministic_components,
                "llm_factor_breakdown": {},
                "reasoning": "Deterministic terminal conclusion detected; skipping exploratory confidence scoring.",
                "terminal_override": {
                    "category": terminal.get("root_cause_category"),
                    "dependency": terminal.get("terminal_dependency"),
                    "evidence": terminal.get("terminal_evidence", []),
                    "override_score": final_score,
                },
            }
            state["confidence_score"] = final_score
            state["is_terminal"] = True
            state["requires_more_data"] = False
            await self._persist_state(state)
            return state

        llm_confidence = await self._ask_json_from_catalog(
            prompt_key="confidence_scoring_agent",
            variables={
                "hypothesis": state.get("hypothesis", ""),
                "evidence_json": json.dumps(state.get("evidence", []), default=str),
                "anomalies_json": json.dumps(state.get("anomalies", []), default=str),
                "critique_feedback": state.get("critique_feedback", ""),
                "observability_missing_json": json.dumps(missing_signals, default=str),
                "is_terminal": bool(state.get("is_terminal", False)),
                "root_cause_category": str(state.get("root_cause_category", "unknown")),
                "log_evidence_digest_json": json.dumps(
                    self._build_log_evidence_digest(state.get("logs", [])),
                    default=str,
                ),
                "metrics_evidence_digest_json": json.dumps(
                    self._build_metrics_evidence_digest(state.get("metrics", {})),
                    default=str,
                ),
            },
            state=state,
            default={
                "score": round(deterministic_score, 4),
                "reasoning": "Fallback deterministic weighted scoring used.",
                "factor_breakdown": deterministic_components,
            },
        )

        raw_score = llm_confidence.get("score", deterministic_score)
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            score = float(deterministic_score)
        score = max(0.0, min(1.0, score))

        llm_factors = llm_confidence.get("factor_breakdown", {})
        state["confidence_components"] = {
            "deterministic": deterministic_components,
            "llm_factor_breakdown": llm_factors if isinstance(llm_factors, dict) else {},
            "reasoning": llm_confidence.get("reasoning", ""),
        }
        state["confidence_score"] = round(score, 4)
        self._apply_terminal_conclusion(state)
        if missing_signals:
            logger.info(
                "Confidence reduced due to missing observability signals: %s",
                ",".join(missing_signals),
            )
        await self._persist_state(state)
        return state

    def _route_after_confidence(self, state: SREMultiAgentState) -> Literal["web_search_agent", "remediation_plan"]:
        if bool(state.get("is_terminal", False)):
            return "remediation_plan"
        web_search_runs = int(state.get("web_search_iterations", 0) or 0)
        if float(state.get("confidence_score", 0.0)) < self._confidence_threshold and web_search_runs < 1:
            return "web_search_agent"
        return "remediation_plan"

    def _route_after_remediation_plan(
        self, state: SREMultiAgentState
    ) -> Literal["additional_context_aggregation", "human_approval"]:
        if bool(state.get("is_terminal", False)):
            return "human_approval"
        additional = state.get("additional_context", {}) if isinstance(state.get("additional_context"), dict) else {}
        has_dependency_validation = bool(
            additional.get("dependency_findings")
            or additional.get("external_dependency_evaluations")
            or additional.get("debug_pod_dns_checks")
        )
        iteration = int(state.get("remediation_iteration", 0) or 0)
        max_iterations = max(1, int(state.get("max_remediation_iterations", 2) or 2))
        llm_terminal_candidate = bool(state.get("llm_terminal_candidate", False))
        if llm_terminal_candidate and not has_dependency_validation and iteration < (max_iterations + 1):
            # Ensure at least one explicit dependency validation pass before final approval.
            return "additional_context_aggregation"
        if iteration < max_iterations:
            return "additional_context_aggregation"
        return "human_approval"

    async def _web_search_agent_node(self, state: SREMultiAgentState) -> SREMultiAgentState:
        state["current_node"] = "web_search_agent"
        self._record_prompt_version(state, "web_search_agent")
        findings: List[Dict[str, Any]] = []
        default_vendors, default_clouds, default_region = self._default_web_search_scope()
        vendors = self._normalize_label_list(state.get("vendors")) or default_vendors
        clouds = self._normalize_label_list(state.get("clouds")) or default_clouds
        region = str(state.get("region") or default_region).strip()
        state["vendors"] = vendors
        state["clouds"] = clouds
        state["region"] = region

        web_plan = await self._ask_json_from_catalog(
            prompt_key="web_search_agent",
            variables={
                "target_service": state.get("target_service", ""),
                "incident_title": state.get("title", ""),
                "incident_description": state.get("description", ""),
                "hypothesis": state.get("hypothesis", ""),
                "anomalies_json": json.dumps(state.get("anomalies", []), default=str),
                "log_evidence_digest_json": json.dumps(
                    self._build_log_evidence_digest(state.get("logs", [])),
                    default=str,
                ),
                "metrics_evidence_digest_json": json.dumps(
                    self._build_metrics_evidence_digest(state.get("metrics", {})),
                    default=str,
                ),
                "failure_type": str((state.get("additional_context") or {}).get("failure_type", "")),
                "root_cause_category": str(state.get("root_cause_category", "unknown")),
                "vendors_json": json.dumps(vendors, default=str),
                "clouds_json": json.dumps(clouds, default=str),
                "region": region,
            },
            state=state,
            default={},
        )
        issue_context = self._build_issue_context(state, web_plan)
        github_terms = self._extract_search_terms(web_plan.get("github_issue_terms"))
        cloud_keywords = self._extract_search_terms(web_plan.get("cloud_status_keywords"))
        vendor_topics = self._extract_search_terms(web_plan.get("vendor_doc_topics"))
        if not github_terms:
            log_digest = self._build_log_evidence_digest(state.get("logs", []))
            runtime_signals = log_digest.get("runtime_failure_signals", [])
            if isinstance(runtime_signals, list):
                for signal in runtime_signals[:3]:
                    compact = re.sub(r"\s+", " ", str(signal)).strip()
                    if compact:
                        github_terms.append(compact[:120])
        if str(state.get("root_cause_category", "")).strip().upper() == "RUNTIME_FAILURE":
            cloud_keywords = []

        try:
            findings.extend(await self._search_github_issues(issue_context=issue_context, terms=github_terms))
        except Exception as exc:
            logger.warning("GitHub issue search failed: %s", exc)

        findings.extend(self._build_vendor_doc_findings(vendors=vendors, vendor_topics=vendor_topics))

        try:
            findings.extend(await self._search_cloud_status(clouds=clouds, region=region, keywords=cloud_keywords))
        except Exception as exc:
            logger.warning("Cloud status search failed: %s", exc)

        state["web_findings"] = findings
        state["web_search_iterations"] = int(state.get("web_search_iterations", 0) or 0) + 1
        await self._persist_state(state)
        return state

    async def _additional_context_aggregation_node(self, state: SREMultiAgentState) -> SREMultiAgentState:
        state["current_node"] = "additional_context_aggregation"
        self._record_prompt_version(state, "additional_context_aggregation_agent")

        incident_id = state.get("incident_id", "")
        target = state.get("target_service", "")
        hypothesis = state.get("hypothesis", "")
        critique = state.get("critique_feedback", "")
        dependencies = state.get("extracted_dependencies", [])
        early_logs = (state.get("logs") or [])[:300]
        early_hosts = self._extract_endpoint_host_candidates(
            dependencies=[d for d in dependencies if isinstance(d, dict)],
            logs=early_logs,
        )
        debug_pod_bundle = await self._run_debug_pod_dns_checks(incident_id, early_hosts)
        debug_pod_dns_checks: List[Dict[str, Any]] = debug_pod_bundle.get("results", []) or []
        for hit in debug_pod_bundle.get("mcp_hits", []) or []:
            state.setdefault("mcp_contract_hits", []).append(hit)
        refresh_plan = await self._ask_json_from_catalog(
            prompt_key="additional_context_aggregation_agent",
            variables={
                "hypothesis": hypothesis,
                "critique_feedback": critique,
                "remediation_iteration": int(state.get("remediation_iteration", 0) or 0),
                "web_findings_json": json.dumps(state.get("web_findings", []), default=str),
                "extracted_dependencies_json": json.dumps(dependencies, default=str),
                "graph_context_json": json.dumps(state.get("graph_context", {}), default=str),
                "istio_context_json": json.dumps(state.get("istio_context", {}), default=str),
                "previous_remediation_plan_json": json.dumps(state.get("remediation_plan", {}), default=str),
                "previous_additional_context_json": json.dumps(state.get("additional_context", {}), default=str),
                "debug_pod_dns_json": json.dumps(debug_pod_dns_checks, default=str),
            },
            state=state,
            default={},
        )
        prior_findings: Dict[str, str] = {}
        for item in ((state.get("additional_context") or {}).get("dependency_findings", []) or []):
            if not isinstance(item, dict):
                continue
            dep = self._sanitize_k8s_service_name(str(item.get("dependency", "")))
            status = str(item.get("status", "")).strip().lower()
            if dep and status:
                prior_findings[dep] = status
        selected = [str(item.get("name", "")) for item in dependencies[:5] if isinstance(item, dict)]
        selected.extend([str(s) for s in refresh_plan.get("dependency_services_to_check", []) if isinstance(s, str)])
        selected.extend(
            [
                str(s)
                for s in (state.get("remediation_plan", {}) or {}).get("impacted_services", [])
                if isinstance(s, str)
            ]
        )
        selected = [self._sanitize_k8s_service_name(s) for s in selected]
        target_aliases = set(self._build_service_aliases(target))
        selected = [s for s in selected if s not in target_aliases]
        selected = [s for s in selected if prior_findings.get(s) != "confirmed_healthy"]
        selected = [s for s in dict.fromkeys(selected) if s]
        facts = self._extract_graph_remediation_facts(state)
        fallback_ns = facts.get("namespace")
        log_ns = self._extract_namespace_from_normalized_logs(state.get("logs") or [])
        if log_ns:
            fallback_ns = log_ns

        merged_logs: List[Dict[str, Any]] = []
        dependency_kubernetes_context: Dict[str, Any] = {}
        for svc in selected:
            svc_clean = self._sanitize_k8s_service_name(svc)
            if not svc_clean or svc_clean.lower() == "all":
                continue
            ns = await self._resolve_namespace_for_k8s_logs(incident_id, svc_clean, fallback_ns)
            contracts = [
                {
                    "provider": "kubernetes",
                    "server": "kubernetes-mcp",
                    "tool": "kubernetes_get_pod_logs",
                    "arguments": {"service_name": svc_clean, "namespace": ns, "tail_lines": 200},
                }
            ]
            call = await self.mcp.call_first_available_contract(contracts, session_id=incident_id)
            state.setdefault("mcp_contract_hits", []).append({"capability": "kubernetes_dependency_logs", **call})
            if call.get("status") == "success":
                merged_logs.extend(self._normalize_logs(call.get("response", {}))[:20])
            workload_call = await self.mcp.call_first_available_contract(
                [
                    {
                        "provider": "kubernetes",
                        "server": "kubernetes-mcp",
                        "tool": "kubernetes_list_workloads",
                        "arguments": {"service_name": svc_clean, "namespace": ns, "include_pods": True},
                    }
                ],
                session_id=incident_id,
            )
            state.setdefault("mcp_contract_hits", []).append({"capability": "kubernetes_dependency_workloads", **workload_call})
            runtime_call = await self.mcp.call_first_available_contract(
                [
                    {
                        "provider": "kubernetes",
                        "server": "kubernetes-mcp",
                        "tool": "kubernetes_get_service_runtime_context",
                        "arguments": {"service_name": svc_clean, "namespace": ns},
                    }
                ],
                session_id=incident_id,
            )
            state.setdefault("mcp_contract_hits", []).append({"capability": "kubernetes_dependency_runtime", **runtime_call})
            dependency_kubernetes_context[svc_clean] = {
                "namespace": ns,
                "workloads": (
                    self._normalize_kubernetes_workloads(workload_call.get("response", {}))
                    if workload_call.get("status") == "success"
                    else []
                ),
                "runtime": (
                    self._extract_result_payload(runtime_call.get("response", {}))
                    if runtime_call.get("status") == "success"
                    else {}
                ),
            }

        combined_logs_for_reasoning = (state.get("logs", []) + merged_logs)[:300]
        dependency_hosts = self._extract_endpoint_host_candidates(
            dependencies=[d for d in state.get("extracted_dependencies", []) if isinstance(d, dict)],
            logs=combined_logs_for_reasoning,
        )
        runtime_ctx = ((state.get("additional_context") or {}).get("kubernetes", {}) or {}).get("runtime", {})
        source_ip = ""
        if isinstance(runtime_ctx, dict):
            for pod in runtime_ctx.get("pods", []) if isinstance(runtime_ctx.get("pods"), list) else []:
                if isinstance(pod, dict) and pod.get("pod_ip"):
                    source_ip = str(pod.get("pod_ip"))
                    break
        aws_lbs: List[Dict[str, Any]] = []
        external_dependency_evaluations: List[Dict[str, Any]] = []
        aws_diagnostics = []
        for host in dependency_hosts:
            classification = self._classify_dependency_endpoint(host)
            graph_lookup = await self.mcp.call_tool(
                tool_name="graph_find_resource_by_endpoint",
                arguments={"endpoint": host, "limit": 5},
                server_name="graph-server",
                session_id=incident_id,
            )
            graph_payload = self._extract_result_payload(graph_lookup)
            graph_matches = (
                graph_payload.get("matches", [])
                if isinstance(graph_payload, dict) and isinstance(graph_payload.get("matches"), list)
                else []
            )
            state.setdefault("mcp_contract_hits", []).append(
                {
                    "capability": "graph_dependency_endpoint_lookup",
                    "status": "success" if not graph_lookup.get("error") else "failed",
                    "provider": "graph",
                    "server": "graph-server",
                    "tool": "graph_find_resource_by_endpoint",
                    "response": graph_lookup,
                }
            )

            aws_lookup_result: Dict[str, Any] = {}
            aws_matches_count = 0
            if classification.get("cloud") == "aws":
                tool_name = "aws_list_load_balancers"
                args: Dict[str, Any] = {}
                hint = str(classification.get("resource_hint") or "")
                region = classification.get("region")
                if classification.get("resource_type") == "rds":
                    tool_name = "aws_list_rds_instances"
                    args = {"instance_hint": hint}
                elif classification.get("resource_type") == "elasticache":
                    tool_name = "aws_list_elasticache_clusters"
                    args = {"cluster_hint": hint}
                elif classification.get("resource_type") == "s3":
                    tool_name = "aws_list_s3_buckets"
                    args = {"bucket_hint": hint}
                else:
                    tool_name = "aws_list_load_balancers"
                    args = {"service_name": hint}
                if region:
                    args["region"] = region
                aws_lookup = await self.mcp.call_first_available_contract(
                    [
                        {
                            "provider": "aws",
                            "server": "aws-mcp",
                            "tool": tool_name,
                            "arguments": args,
                        }
                    ],
                    session_id=incident_id,
                )
                state.setdefault("mcp_contract_hits", []).append({"capability": "aws_dependency_lookup", **aws_lookup})
                if aws_lookup.get("status") == "success":
                    aws_lookup_result = self._extract_result_payload(aws_lookup.get("response", {}))
                    aws_context = self._normalize_aws_context(aws_lookup.get("response", {}))
                    aws_matches_count = sum(len(v) for v in aws_context.values() if isinstance(v, list))
                    aws_lbs.extend(aws_context.get("load_balancers", []))

            existence_verdict = "inconclusive"
            if graph_matches or aws_matches_count > 0:
                existence_verdict = "exists"
            elif classification.get("cloud") == "aws":
                existence_verdict = "not_found"
            external_dependency_evaluations.append(
                {
                    "endpoint": host,
                    "classification": classification,
                    "graph_matches_count": len(graph_matches),
                    "graph_matches": graph_matches[:5],
                    "aws_matches_count": aws_matches_count,
                    "aws_lookup": aws_lookup_result,
                    "existence_verdict": existence_verdict,
                }
            )
            diag = await self.mcp.call_first_available_contract(
                [
                    {
                        "provider": "aws",
                        "server": "aws-mcp",
                        "tool": "aws_network_dependency_diagnostics",
                        "arguments": {"dependency_host": host, "source_ip": source_ip},
                    }
                ],
                session_id=incident_id,
            )
            state.setdefault("mcp_contract_hits", []).append({"capability": "aws_network_diagnostics", **diag})
            if diag.get("status") == "success":
                aws_diagnostics.append(self._extract_result_payload(diag.get("response", {})))

        dependency_findings = self._build_dependency_findings(
            services_checked=selected,
            merged_logs=combined_logs_for_reasoning,
            dependency_kubernetes_context=dependency_kubernetes_context,
            aws_diagnostics=aws_diagnostics,
            external_dependency_evaluations=external_dependency_evaluations,
            primary_service=target,
        )
        dependency_findings = self._apply_debug_dns_to_findings(
            dependency_findings,
            debug_pod_dns_checks,
            external_dependency_evaluations,
        )

        additional_deps = self._extract_dependencies_from_logs(merged_logs)
        existing = state.get("extracted_dependencies", [])
        merged_deps = {f"{d.get('type')}:{d.get('name')}": d for d in existing if isinstance(d, dict)}
        for dep in additional_deps:
            merged_deps[f"{dep.get('type')}:{dep.get('name')}"] = dep
        state["extracted_dependencies"] = list(merged_deps.values())[:40]
        if merged_logs:
            state["logs"] = (state.get("logs", []) + merged_logs)[:120]

        merged_additional = state.get("additional_context", {}) if isinstance(state.get("additional_context"), dict) else {}
        merged_additional.update({
            "hypothesis": hypothesis,
            "critique_feedback": critique,
            "dependency_services_checked": selected,
            "new_logs_count": len(merged_logs),
            "aws_load_balancers": aws_lbs[:20],
            "external_dependency_evaluations": external_dependency_evaluations,
            "aws_network_diagnostics": aws_diagnostics,
            "dependency_kubernetes_context": dependency_kubernetes_context,
            "dependency_findings": dependency_findings,
            "new_dependencies_count": len(additional_deps),
            "refresh_plan": refresh_plan,
            "debug_pod_dns_checks": debug_pod_dns_checks,
        })
        state["additional_context"] = merged_additional
        self._apply_terminal_conclusion(state)
        await self._persist_state(state)
        return state

    @staticmethod
    def _sanitize_github_issue_search_fragment(text: str) -> str:
        """Strip characters that break GitHub issue search / Lucene-style parsing (often cause HTTP 422)."""
        if not text:
            return ""
        cleaned = re.sub(r'[\[\](){}<>":#^~\\|`&*?/]', " ", text)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    @staticmethod
    def _extract_search_terms(raw: Any) -> List[str]:
        if not isinstance(raw, list):
            return []
        terms: List[str] = []
        for item in raw:
            if not isinstance(item, str):
                continue
            cleaned = item.strip()
            if cleaned and cleaned not in terms:
                terms.append(cleaned)
        return terms[:8]

    def _build_issue_context(self, state: SREMultiAgentState, web_plan: Dict[str, Any]) -> str:
        probable_issue = str(web_plan.get("probable_issue") or "").strip()
        if probable_issue:
            return probable_issue
        candidates = [
            str(state.get("hypothesis", "")).strip(),
            " ".join([str(x).strip() for x in state.get("anomalies", []) if isinstance(x, str)]),
            str(state.get("description", "")).strip(),
            str(state.get("title", "")).strip(),
        ]
        for candidate in candidates:
            cleaned = self._sanitize_github_issue_search_fragment(candidate)
            if cleaned:
                return cleaned
        return ""

    def _github_issue_search_q_candidates(self, issue_context: str, terms: List[str]) -> List[str]:
        """Build one or more valid issue-focused query strings (each ≤256 chars)."""
        issue = self._sanitize_github_issue_search_fragment(issue_context or "")
        issue_terms = [
            self._sanitize_github_issue_search_fragment(term)
            for term in terms
            if self._sanitize_github_issue_search_fragment(term)
        ]
        suffix = _GITHUB_ISSUE_SEARCH_SUFFIX
        max_keywords = _GITHUB_ISSUE_SEARCH_MAX_Q_LEN - len(suffix)

        def _pack(keywords: str) -> str:
            kw = keywords.strip()
            if not kw:
                return ""
            if len(kw) > max_keywords:
                cut = kw[:max_keywords]
                if " " in cut:
                    cut = cut.rsplit(" ", 1)[0]
                kw = cut.strip()
            if not kw:
                return ""
            return kw + suffix

        out: List[str] = []
        if issue:
            packed = _pack(issue)
            if packed:
                out.append(packed)
        if issue_terms:
            packed = _pack(" ".join(issue_terms[:4]))
            if packed and packed not in out:
                out.append(packed)
        if issue and issue_terms:
            packed = _pack(f"{issue} {' '.join(issue_terms[:2])}")
            if packed and packed not in out:
                out.append(packed)
        # Last resort: broad issue lookup (no in:title,body).
        if issue and len(issue) <= _GITHUB_ISSUE_SEARCH_MAX_Q_LEN and issue not in out:
            out.append(f"is:issue {issue}")
        return out

    async def _search_github_issues(self, issue_context: str, terms: List[str]) -> List[Dict[str, Any]]:
        token = settings.GITHUB_TOKEN
        if not token:
            return []
        queries = self._github_issue_search_q_candidates(issue_context, terms)
        if not queries:
            return []

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "aegisops-sre-multi-agent",
        }
        url = "https://api.github.com/search/issues"
        base_params = {"sort": "updated", "order": "desc", "per_page": 5}

        async with httpx.AsyncClient(timeout=settings.SRE_WEB_SEARCH_TIMEOUT_SECONDS) as client:
            last_error: Optional[str] = None
            for q in queries:
                params = {**base_params, "q": q}
                response = await client.get(url, headers=headers, params=params)
                if response.status_code == 422:
                    try:
                        body = response.json()
                        last_error = json.dumps(body)[:500]
                    except Exception:
                        last_error = response.text[:500]
                    logger.debug(
                        "GitHub issue search query rejected (422), trying fallback. q_len=%s err=%s",
                        len(q),
                        last_error,
                    )
                    continue
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    logger.warning("GitHub issue search HTTP error: %s", exc)
                    return []

                data = response.json()
                items = data.get("items", [])
                return [
                    {
                        "source": "github-issues",
                        "query": q,
                        "title": item.get("title"),
                        "url": item.get("html_url"),
                        "score": item.get("score", 0),
                    }
                    for item in items
                ]

            if last_error:
                logger.warning(
                    "GitHub issue search failed: all query variants returned 422. Last error: %s",
                    last_error,
                )
            return []

    def _build_vendor_doc_findings(self, vendors: List[str], vendor_topics: List[str]) -> List[Dict[str, Any]]:
        findings: List[Dict[str, Any]] = []
        for vendor in vendors:
            if vendor not in _VENDOR_DOC_URLS:
                continue
            findings.append(
                {
                    "source": "vendor-docs",
                    "vendor": vendor,
                    "url": _VENDOR_DOC_URLS[vendor],
                    "topics": vendor_topics[:5],
                }
            )
        return findings

    async def _search_cloud_status(self, clouds: List[str], region: str, keywords: List[str]) -> List[Dict[str, Any]]:
        findings: List[Dict[str, Any]] = []
        if not clouds:
            return findings
        region_lc = region.lower()
        keyword_lc = [kw.lower() for kw in keywords if kw]
        async with httpx.AsyncClient(timeout=settings.SRE_WEB_SEARCH_TIMEOUT_SECONDS) as client:
            for cloud in clouds:
                feed_url = _CLOUD_STATUS_FEEDS.get(cloud)
                status_url = _CLOUD_STATUS_URLS.get(cloud)
                if not feed_url or not status_url:
                    continue
                try:
                    response = await client.get(feed_url)
                    response.raise_for_status()
                    content = response.text
                    matched_snippets = self._extract_cloud_status_matches(
                        cloud=cloud,
                        content=content,
                        region=region_lc,
                        keywords=keyword_lc,
                    )
                    findings.append(
                        {
                            "source": "cloud-status",
                            "cloud": cloud,
                            "region": region,
                            "url": status_url,
                            "feed_url": feed_url,
                            "match_count": len(matched_snippets),
                            "matches": matched_snippets[:5],
                        }
                    )
                except Exception as exc:
                    logger.warning("Cloud status check failed for %s: %s", cloud, exc)
                    findings.append(
                        {
                            "source": "cloud-status",
                            "cloud": cloud,
                            "region": region,
                            "url": status_url,
                            "feed_url": feed_url,
                            "error": str(exc),
                        }
                    )
        return findings

    def _extract_cloud_status_matches(
        self,
        cloud: str,
        content: str,
        region: str,
        keywords: List[str],
    ) -> List[str]:
        if cloud == "gcp":
            try:
                payload = json.loads(content)
            except Exception:
                payload = {}
            incidents = payload.get("incidents", []) if isinstance(payload, dict) else []
            snippets = [
                f"{item.get('begin', '')} {item.get('service_name', '')} {item.get('external_desc', '')}"
                for item in incidents
                if isinstance(item, dict)
            ]
        else:
            # Works for AWS RSS and Azure Atom feeds.
            snippets = re.findall(r"<title>(.*?)</title>|<summary>(.*?)</summary>|<description>(.*?)</description>", content)
            snippets = [" ".join([part for part in row if part]).strip() for row in snippets if any(row)]

        out: List[str] = []
        for snippet in snippets:
            text = re.sub(r"\s+", " ", snippet).strip()
            if not text:
                continue
            text_lc = text.lower()
            region_match = not region or region in text_lc
            keyword_match = any(keyword in text_lc for keyword in keywords) if keywords else True
            if region_match and keyword_match:
                out.append(text[:280])
        return out

    async def _rca_agent_recompute_node(self, state: SREMultiAgentState) -> SREMultiAgentState:
        state["current_node"] = "rca_agent_recompute"
        logs_prompt_view = self._build_logs_prompt_view(state.get("logs", []))
        metrics_prompt_view = self._build_metrics_prompt_view(state.get("metrics", {}))
        log_digest = self._build_log_evidence_digest(state.get("logs", []))
        metrics_digest = self._build_metrics_evidence_digest(state.get("metrics", {}))
        recomputed = await self._ask_json_from_catalog(
            prompt_key="rca_agent_recompute",
            variables={
                "hypothesis": state.get("hypothesis", ""),
                "logs_json": json.dumps(logs_prompt_view, default=str),
                "metrics_json": json.dumps(metrics_prompt_view, default=str),
                "log_evidence_digest_json": json.dumps(log_digest, default=str),
                "metrics_evidence_digest_json": json.dumps(metrics_digest, default=str),
                "web_findings_json": json.dumps(state.get("web_findings", []), default=str),
                "critique_feedback": state.get("critique_feedback", ""),
                "extracted_dependencies_json": json.dumps(state.get("extracted_dependencies", []), default=str),
                "additional_context_json": json.dumps(state.get("additional_context", {}), default=str),
                "dependency_findings_json": json.dumps(
                    (state.get("additional_context") or {}).get("dependency_findings", []),
                    default=str,
                ),
                "graph_context_json": json.dumps(state.get("graph_context", {}), default=str),
                "istio_context_json": json.dumps(state.get("istio_context", {}), default=str),
            },
            state=state,
            default={},
        )
        if recomputed.get("hypothesis") or recomputed.get("root_cause_explanation"):
            state["hypothesis"] = recomputed.get("hypothesis") or recomputed.get("root_cause_explanation")
            state["root_cause"] = state["hypothesis"]
        if recomputed.get("root_cause"):
            state["root_cause"] = recomputed.get("root_cause")
            state["hypothesis"] = state["root_cause"]
        if recomputed.get("evidence") or recomputed.get("evidence_sources") or recomputed.get("confidence_indicators"):
            state["evidence"] = (
                recomputed.get("evidence")
                or recomputed.get("evidence_sources")
                or recomputed.get("confidence_indicators")
            )
        if recomputed.get("anomalies"):
            state["anomalies"] = recomputed["anomalies"]
        if recomputed.get("suspected_component"):
            state["failing_service"] = recomputed["suspected_component"]
        if recomputed.get("dependency_chain"):
            state.setdefault("evidence", [])
            if isinstance(state["evidence"], list):
                state["evidence"].append(f"dependency_chain={recomputed.get('dependency_chain')}")
        if recomputed.get("failure_type"):
            state.setdefault("additional_context", {})
            if isinstance(state["additional_context"], dict):
                state["additional_context"]["failure_type"] = recomputed.get("failure_type")
        raw_rca_confidence = recomputed.get("confidence")
        if raw_rca_confidence is not None:
            try:
                state["rca_confidence"] = max(0.0, min(1.0, float(raw_rca_confidence)))
            except (TypeError, ValueError):
                pass
        state["llm_terminal_candidate"] = bool(
            recomputed.get("is_terminal", state.get("llm_terminal_candidate", False))
        )
        state["is_terminal"] = False
        state["requires_more_data"] = True
        if recomputed.get("root_cause_category") or recomputed.get("category"):
            state["root_cause_category"] = str(
                recomputed.get("root_cause_category") or recomputed.get("category")
            )
        if recomputed.get("terminal_dependency"):
            state["terminal_dependency"] = str(recomputed.get("terminal_dependency"))
        terminal_evidence = recomputed.get("terminal_evidence")
        if isinstance(terminal_evidence, list):
            state["terminal_evidence"] = [str(item) for item in terminal_evidence if str(item).strip()][:10]
        self._apply_terminal_conclusion(state)
        self._apply_runtime_failure_guardrail(state)
        await self._persist_state(state)
        return state

    async def _remediation_plan_node(self, state: SREMultiAgentState) -> SREMultiAgentState:
        state["current_node"] = "remediation_plan"
        state["remediation_iteration"] = int(state.get("remediation_iteration", 0) or 0) + 1
        await self._ensure_graph_context_for_remediation(state)
        facts = self._extract_graph_remediation_facts(state)
        state["graph_remediation_facts"] = facts
        self._apply_terminal_conclusion(state)
        oom_recommendation = self._derive_oom_resource_recommendations(state, facts)

        default_plan = {
            "immediate_mitigation": ["Scale affected service and isolate failing node"],
            "long_term_fix": ["Apply permanent configuration fix and add regression tests"],
            "preventative_measures": ["Add proactive alert thresholds and SLO burn alerts"],
            "step_by_step_commands": self._build_default_remediation_commands(facts),
            "rollback_plan": ["Revert recent deployment", "Restore previous stable configuration"],
        }

        plan = await self._ask_json_from_catalog(
            prompt_key="remediation_plan",
            variables={
                "hypothesis": state.get("hypothesis", ""),
                "evidence_json": json.dumps(state.get("evidence", []), default=str),
                "confidence_score": state.get("confidence_score", ""),
                "target_service": state.get("target_service", ""),
                "failing_service": state.get("failing_service", ""),
                "graph_remediation_facts_json": json.dumps(facts, default=str)[:8000],
                "graph_context_json": json.dumps(state.get("graph_context", {}), default=str)[:8000],
                "istio_context_json": json.dumps(state.get("istio_context", {}), default=str)[:4000],
                "extracted_dependencies_json": json.dumps(state.get("extracted_dependencies", []), default=str)[:4000],
                "failure_type": str((state.get("additional_context") or {}).get("failure_type", "")),
                "kubernetes_workloads_json": json.dumps((state.get("additional_context") or {}).get("kubernetes", {}), default=str)[:8000],
                "dependency_kubernetes_context_json": json.dumps(
                    (state.get("additional_context") or {}).get("dependency_kubernetes_context", {}),
                    default=str,
                )[:8000],
                "dependency_findings_json": json.dumps(
                    (state.get("additional_context") or {}).get("dependency_findings", []),
                    default=str,
                )[:8000],
                "oom_recommendation_json": json.dumps(oom_recommendation, default=str),
                "remediation_iteration": int(state.get("remediation_iteration", 0) or 0),
                "is_terminal": bool(state.get("is_terminal", False)),
                "requires_more_data": bool(state.get("requires_more_data", True)),
                "root_cause_category": str(state.get("root_cause_category", "unknown")),
                "terminal_dependency": str(state.get("terminal_dependency") or ""),
                "terminal_evidence_json": json.dumps(state.get("terminal_evidence", []), default=str),
            },
            state=state,
            default=default_plan,
            max_tokens=4096,
        )
        if "preventative_actions" in plan and "preventative_measures" not in plan:
            plan["preventative_measures"] = plan["preventative_actions"]
        if "step_by_step_instructions" in plan and "step_by_step_commands" not in plan:
            plan["step_by_step_commands"] = plan["step_by_step_instructions"]
        if "commands" in plan:
            existing = plan.get("step_by_step_commands", [])
            if isinstance(existing, list):
                plan["step_by_step_commands"] = existing + [cmd for cmd in plan["commands"] if cmd not in existing]
            else:
                plan["step_by_step_commands"] = plan["commands"]

        terminal_template = None
        if bool(state.get("is_terminal", False)):
            terminal_template = self._build_terminal_remediation_template(state, facts)
        if terminal_template:
            generated_risk = plan.get("risk_assessment") if isinstance(plan, dict) else None
            plan = terminal_template
            if isinstance(generated_risk, str) and generated_risk.strip():
                plan["risk_assessment"] = generated_risk.strip()

        plan = self._apply_remediation_graph_facts(plan, facts)
        # Enforce concrete OOM resource sizing when we have enough data.
        is_oom_case = "oom" in (state.get("hypothesis", "").lower()) or str((state.get("additional_context") or {}).get("failure_type", "")).lower() == "oom"
        set_cmd = oom_recommendation.get("kubectl_set_resources_command")
        if is_oom_case and set_cmd:
            plan.setdefault("immediate_mitigation", [])
            if isinstance(plan["immediate_mitigation"], list):
                plan["immediate_mitigation"].append(
                    "Apply concrete CPU/memory requests and limits derived from observed peak usage."
                )
            plan.setdefault("step_by_step_commands", [])
            if isinstance(plan["step_by_step_commands"], list) and set_cmd not in plan["step_by_step_commands"]:
                plan["step_by_step_commands"].append(set_cmd)
            plan.setdefault("commands", [])
            if isinstance(plan["commands"], list) and set_cmd not in plan["commands"]:
                plan["commands"].append(set_cmd)
        if bool(state.get("is_terminal", False)):
            plan = self._strip_investigative_actions_for_terminal(plan)
        else:
            plan = self._inject_kubernetes_read_steps(plan, state, facts)
        state["remediation_plan"] = plan
        await self._persist_state(state)
        return state

    def _inject_kubernetes_read_steps(
        self, plan: Dict[str, Any], state: SREMultiAgentState, facts: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Append concrete read-only kubectl checks for runtime verification."""
        if not isinstance(plan, dict):
            return plan

        ns = facts.get("namespace")
        deploy = facts.get("deployment_name") or facts.get("kubernetes_service_name")
        pod_ex = facts.get("pod_name_example")

        commands = plan.get("commands")
        if not isinstance(commands, list):
            commands = []
            plan["commands"] = commands
        steps = plan.get("step_by_step_commands")
        if not isinstance(steps, list):
            steps = []
            plan["step_by_step_commands"] = steps

        supplemental: List[str] = []
        if ns and deploy:
            supplemental.append(f"kubectl get deployment {deploy} -n {ns} -o wide")
        if ns and pod_ex:
            supplemental.append(f"kubectl get pod {pod_ex} -n {ns} -o wide")
            supplemental.append(f"kubectl exec -n {ns} {pod_ex} -- cat /etc/resolv.conf")

        dependency_ctx = ((state.get("additional_context") or {}).get("dependency_kubernetes_context", {}) or {})
        findings = ((state.get("additional_context") or {}).get("dependency_findings", []) or [])
        unresolved = {
            self._sanitize_k8s_service_name(str(item.get("dependency", "")))
            for item in findings
            if isinstance(item, dict) and str(item.get("status", "")).strip().lower() != "confirmed_healthy"
        }
        for dep_name in list(unresolved)[:2]:
            dep_ctx = dependency_ctx.get(dep_name)
            if not isinstance(dep_ctx, dict):
                continue
            dep_ns = str(dep_ctx.get("namespace") or "").strip()
            if not dep_ns:
                continue
            workloads = dep_ctx.get("workloads", [])
            if isinstance(workloads, list):
                deploy_name = next(
                    (
                        str(w.get("name"))
                        for w in workloads
                        if isinstance(w, dict) and str(w.get("kind", "")).lower() == "deployment" and w.get("name")
                    ),
                    "",
                )
                if deploy_name:
                    supplemental.append(f"kubectl get deployment {deploy_name} -n {dep_ns} -o wide")

        dependency_hosts: List[str] = []
        for dep in state.get("extracted_dependencies", []) if isinstance(state.get("extracted_dependencies"), list) else []:
            if not isinstance(dep, dict):
                continue
            name = str(dep.get("name", ""))
            if "." in name and any(token in name for token in ("elb.amazonaws.com", "rds.amazonaws.com", "cache.amazonaws.com")):
                dependency_hosts.append(name)
        for host in dependency_hosts[:2]:
            if ns and pod_ex:
                supplemental.append(f"kubectl exec -n {ns} {pod_ex} -- nslookup {host}")

        for cmd in supplemental:
            if cmd not in commands:
                commands.append(cmd)
            if cmd not in steps:
                steps.append(cmd)
        return plan

    async def _human_approval_node(self, state: SREMultiAgentState) -> SREMultiAgentState:
        state["current_node"] = "human_approval"
        approval_payload = await self._ask_json_from_catalog(
            prompt_key="human_approval_agent",
            variables={
                "remediation_plan_json": json.dumps(state.get("remediation_plan", {}), default=str),
            },
            state=state,
            default={
                "approval_status": "pending",
                "user_feedback": "Awaiting explicit user approval before execution.",
            },
        )
        state["approval_presentation"] = approval_payload

        if state.get("approved") is None:
            state["approval_id"] = state.get("approval_id") or f"appr_{uuid.uuid4().hex[:10]}"
            state["approval_requested_at"] = datetime.utcnow().isoformat()
            state["operation_status"] = "waiting_approval"
            await self._emit_event(
                state,
                event_type="approval_required",
                node="human_approval",
                message="Human approval is required before remediation execution.",
                data={
                    "approval_id": state.get("approval_id"),
                    "hypothesis": state.get("hypothesis"),
                    "root_cause": state.get("root_cause"),
                    "approval_presentation": state.get("approval_presentation", {}),
                },
                persist=False,
            )
        await self._persist_state(state)
        return state

    def _route_after_human_approval(
        self, state: SREMultiAgentState
    ) -> Literal["await_approval", "remediation_execution", "manual_remediation_fallback"]:
        if state.get("approved") is None:
            return "await_approval"
        if state.get("approved") is True:
            return "remediation_execution"
        return "manual_remediation_fallback"

    async def _await_approval_node(self, state: SREMultiAgentState) -> SREMultiAgentState:
        state["current_node"] = "await_approval"
        state["operation_status"] = "waiting_approval"
        await self._persist_state(state)
        return state

    async def _remediation_execution_node(self, state: SREMultiAgentState) -> SREMultiAgentState:
        state["current_node"] = "remediation_execution"
        self._record_prompt_version(state, "remediation_execution_agent")
        plan = state.get("remediation_plan", {})
        commands = plan.get("step_by_step_commands", [])

        execution_results: List[Dict[str, Any]] = []
        for command in commands[:10]:
            if not isinstance(command, str) or not command.strip():
                continue
            result = await self.vm_executor.execute_command(
                run_id=state["incident_id"],
                command=command,
                timeout_seconds=120,
                execution_type="local",
            )
            execution_results.append(
                {
                    "command": command,
                    "status": result.status,
                    "exit_code": result.exit_code,
                    "stdout": (result.stdout or "")[:1000],
                    "stderr": (result.stderr or "")[:1000],
                }
            )
        state["execution_results"] = execution_results
        await self._persist_state(state)
        return state

    def _route_after_execution(
        self, state: SREMultiAgentState
    ) -> Literal["servicenow_update", "manual_remediation_fallback"]:
        results = state.get("execution_results", [])
        if not results:
            return "manual_remediation_fallback"
        all_success = all(item.get("exit_code", 1) == 0 for item in results)
        return "servicenow_update" if all_success else "manual_remediation_fallback"

    async def _manual_remediation_fallback_node(self, state: SREMultiAgentState) -> SREMultiAgentState:
        state["current_node"] = "manual_remediation_fallback"
        state["manual_fallback"] = {
            "required": True,
            "reason": "automated remediation failed or approval denied",
            "actions": [
                "Escalate to on-call SRE with RCA evidence",
                "Apply rollback plan manually",
                "Create post-incident review task",
            ],
        }
        await self._persist_state(state)
        return state

    async def _servicenow_update_node(self, state: SREMultiAgentState) -> SREMultiAgentState:
        state["current_node"] = "servicenow_update"
        incident_id = state.get("servicenow_incident_id")
        work_notes = (
            f"[AegisOps SRE-Multi-Agent]\n"
            f"Confidence: {state.get('confidence_score')}\n"
            f"Terminal RCA: {state.get('is_terminal', False)}\n"
            f"RCA Category: {state.get('root_cause_category', 'unknown')}\n"
            f"Hypothesis: {state.get('hypothesis')}\n"
            f"Root cause: {state.get('root_cause', state.get('hypothesis'))}\n"
            f"MCP sources used: {', '.join(state.get('mcp_sources_contributed', []))}\n"
            f"Missing signals: {', '.join(state.get('observability_missing_signals', []))}\n"
            f"Execution results count: {len(state.get('execution_results', []))}\n"
            f"Manual fallback: {bool(state.get('manual_fallback'))}\n"
        )

        try:
            if incident_id:
                updated = await self.snow.client.update_incident(incident_id, {"work_notes": work_notes})
                state["servicenow_update"] = {"status": "updated", "incident": updated.get("number", incident_id)}
            else:
                state["servicenow_update"] = {"status": "skipped", "reason": "no_servicenow_incident_id"}
        except Exception as exc:
            logger.warning("ServiceNow update failed: %s", exc)
            state["servicenow_update"] = {"status": "failed", "error": str(exc)}

        await self._persist_state(state)
        return state

    async def _context_graph_update_node(self, state: SREMultiAgentState) -> SREMultiAgentState:
        state["current_node"] = "context_graph_update"
        summary = ", ".join(state.get("remediation_plan", {}).get("immediate_mitigation", [])[:2])
        graph_intent = await self._ask_json_from_catalog(
            prompt_key="context_graph_update_agent",
            variables={
                "incident_id": state.get("incident_id", ""),
                "service_name": state.get("failing_service", state.get("target_service", "unknown-service")),
                "root_cause": state.get("root_cause", state.get("hypothesis", "unknown root cause")),
                "remediation_summary": summary or "manual remediation",
            },
            state=state,
            default={
                "graph_update_status": "updated",
                "deduplicated_nodes": [],
                "relationships_created": [
                    "Incident->Service",
                    "Service->Root Cause",
                    "Root Cause->Remediation",
                ],
            },
        )

        state["context_graph_update"] = await context_graph_service.upsert_incident_relationships(
            incident_id=state["incident_id"],
            service_name=state.get("failing_service", state.get("target_service", "unknown-service")),
            root_cause=state.get("root_cause", state.get("hypothesis", "unknown root cause")),
            remediation_summary=summary or "manual remediation",
        )
        state["context_graph_update"]["llm_intent"] = graph_intent
        await self._persist_state(state)
        return state

    async def _ask_json_from_catalog(
        self,
        prompt_key: str,
        variables: Dict[str, Any],
        state: SREMultiAgentState,
        default: Dict[str, Any],
        max_tokens: int = 1200,
    ) -> Dict[str, Any]:
        """Render prompt from catalog with version tracking, then query LLM for JSON."""
        try:
            prompt = self.prompts.render(prompt_key, variables)
            state.setdefault("prompt_versions", {})
            state["prompt_versions"][prompt_key] = prompt["version"]
            return await self._ask_json(
                system_prompt=prompt["system"],
                user_prompt=prompt["user"],
                default=default,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            logger.warning("Prompt catalog render failed for %s: %s", prompt_key, exc)
            fallback_user = variables.get("fallback_user_prompt", "")
            return await self._ask_json(
                system_prompt="Return only valid JSON.",
                user_prompt=fallback_user if fallback_user else json.dumps(variables, default=str),
                default=default,
                max_tokens=max_tokens,
            )

    async def _ask_json(
        self,
        system_prompt: str,
        user_prompt: str,
        default: Dict[str, Any],
        max_tokens: int = 1200,
    ) -> Dict[str, Any]:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        try:
            response = await self.llm.chat_completion(messages, max_tokens=max_tokens)
            raw = response.get("content", "")
            text = raw.strip() if isinstance(raw, str) else str(raw).strip()
            blob = _extract_json_blob(text)
            if not blob:
                logger.warning(
                    "LLM returned no JSON object (using default). finish_reason=%s preview=%r",
                    response.get("finish_reason"),
                    text[:800],
                )
                return default
            return json.loads(blob)
        except json.JSONDecodeError as exc:
            logger.warning(
                "JSON parse via LLM failed: %s; finish_reason=%s preview=%r",
                exc,
                response.get("finish_reason"),
                text[:800],
            )
            return default
        except Exception as exc:
            logger.warning("JSON parse via LLM failed: %s", exc)
            return default


sre_multi_agent = SREMultiAgent()
