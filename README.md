# ai-multi-agent-workflow

Monorepo for **AegisOps** AI-assisted operations: LangGraph-based agent orchestration, an MCP gateway for tool execution, optional RAG and observability stacks, and scripts that tie **Cartography** (infrastructure inventory) and **Neo4j** (graph context) into incident workflows.

---

## What lives here

| Area | Path | Role |
|------|------|------|
| **Agent orchestration** | `agent-orchestration/` | FastAPI + LangGraph multi-agent backend (SR/CR, incidents, SRE workflow). See [`agent-orchestration/README.md`](agent-orchestration/README.md). |
| **MCP service** | `mcp/` | MCP gateway (default **8005**): registers servers/tools, executes `POST /api/v1/tools/call`, graph load/enrichment. See [`mcp/README.md`](mcp/README.md), [`mcp/INGESTION.md`](mcp/INGESTION.md). |
| **RAG** | `rag/` | Document search / ask pipeline (often **8001** in compose). |
| **Observability** | `observability/` | Prometheus, Grafana, OTEL collector samples. |
| **Scripts** | `scripts/` | e.g. graph enrichment CLI [`scripts/run_graph_ingestion.py`](scripts/run_graph_ingestion.py). |

---

## End-to-end flow (high level)

1. **Clients** call Agent Orchestration (e.g. port **8002**) for chat, streaming, or incident automation.
2. **Orchestration** routes work to specialized agents; the **SRE** path uses [`agent-orchestration/app/agents/sre_multi_agent.py`](agent-orchestration/app/agents/sre_multi_agent.py).
3. **MCP** (`MCP_SERVICE_URL`, default `http://localhost:8005`) is the HTTP gateway the orchestrator uses to invoke tools on registered MCP servers (Kubernetes, AWS, graph, logs, metrics, ServiceNow, etc.).
4. **Cartography** (run separately, typically on a schedule) populates **Neo4j** with infrastructure and Kubernetes-oriented nodes/relationships. **Graph enrichment** (inside MCP) adds runtime signals (Istio call graph, DB usage, Prometheus anomalies, log-derived error patterns, incidents). See **Cartography** below.
5. **Neo4j** is queried both through MCP **graph** tools (during SRE context aggregation) and optionally via [`context_graph_service`](agent-orchestration/app/services/context_graph_service.py) for direct upserts/queries when `NEO4J_*` is set.

---

## `sre_multi_agent.py` — SRE LangGraph workflow

File: [`agent-orchestration/app/agents/sre_multi_agent.py`](agent-orchestration/app/agents/sre_multi_agent.py).

### Purpose

Implements a **production-oriented autonomous SRE incident workflow** on top of **LangGraph**: structured state (`SREMultiAgentState`), node wrappers that emit events, and integration with LLM, RAG, ServiceNow, VM execution, **MCP**, and the **context graph**.

### State (abbreviated)

The graph carries incident metadata, aggregated **logs / metrics / alerts**, **RAG** results, **graph** context (dependencies, incidents), **Istio** context, **MCP** provenance (`mcp_sources_contributed`, `mcp_contract_hits`), RCA fields (hypothesis, evidence, root cause, confidence), remediation and approval, and post-steps (ServiceNow update, **context graph** update).

### LangGraph nodes and edges

The main workflow (`_build_workflow`) is roughly:

```text
incident_trigger
  → context_aggregation
  → rca_agent
  → critique_agent
  → confidence_scoring
      ├─→ web_search_agent → rca_agent_recompute ─┐
      └─→ remediation_plan ←─────────────────────┘
            ├─→ additional_context_aggregation → rca_agent (loop for more context)
            └─→ human_approval
                  ├─→ await_approval → END
                  ├─→ remediation_execution → servicenow_update → context_graph_update → END
                  └─→ manual_remediation_fallback → servicenow_update → …
```

A smaller **post-approval** graph (`_build_post_approval_workflow`) reuses remediation, ServiceNow, and context-graph nodes for resumes after approval.

### MCP context aggregation

When `SRE_USE_MCP_FOR_CONTEXT_AGGREGATION` is true (default in [`app/core/config.py`](agent-orchestration/app/core/config.py)), `_collect_context_via_mcp` calls the shared [`mcp_client`](agent-orchestration/app/services/mcp_client.py) using **capability contracts**: ordered lists of `{provider, server, tool}` so the first working integration wins (`call_first_available_contract`).

Default in-code contracts include **logs** (e.g. Quickwit, Elasticsearch, New Relic), **metrics** (Prometheus, NRQL), **alerts** (Alertmanager, New Relic), **incident history** (ServiceNow MCP), **Istio**, **Kubernetes**, **AWS**, and **graph** tools on server `graph-server` such as `graph_get_service_dependencies`, `graph_get_recent_incidents`, etc. Contracts can be overridden or extended via YAML at `SRE_CAPABILITY_CONTRACTS_PATH` (see `.env.example`).

Dependency rows returned by the graph tools are normalized from fields like `dependencies` or **`cartography_rows`** (see `_extract_cartography_dependencies`). If Cartography-backed rows are empty during aggregation, the workflow can **retry** `graph_get_service_dependencies` (see the Cartography section).

---

## Cartography and the graph

**Cartography** is Lyft’s asset inventory sync into a graph database. In this stack it is the **primary way structural K8s/cloud relationships** get into Neo4j (cluster, namespaces, workloads, RBAC, services, ingress, etc.). It is **not** part of this Python package; you run it on its own schedule (for example `docker compose run --rm cartography` as noted in [`mcp/INGESTION.md`](mcp/INGESTION.md)).

**Enrichment** (after Cartography) adds operational semantics documented in [`mcp/INGESTION.md`](mcp/INGESTION.md):

- Databases and `USES` edges  
- Istio **CALLS** edges and metrics  
- Prometheus-driven **Anomaly** nodes  
- Log-derived **ErrorPattern** and `GENERATED` edges  
- **Incident** linkage (`IMPACTS`, `TRIGGERED_BY`, `EVIDENCED_BY`, …)

Trigger enrichment via:

- `POST http://localhost:8005/api/v1/graph/load` (recommended), or  
- [`scripts/run_graph_ingestion.py`](scripts/run_graph_ingestion.py) from the repo root (adds `mcp` to `PYTHONPATH` and calls `app.ingestion.runner.run_enrichment`).

Example Cypher for exploration is in [`scripts/cypher_examples.md`](scripts/cypher_examples.md). The workspace root [`Cartography`](../../Cartography) file (beside `aegisops-prod-local/`) is a scratchpad of sample queries against Kubernetes-style labels and error-pattern analytics—useful for validating what landed in Neo4j.

**Orchestrator-facing graph access:** MCP exposes tools such as `graph_get_service_dependencies`, `graph_get_impacted_services`, `graph_get_recent_anomalies`, `graph_get_recent_incidents`, `graph_get_incident_root_cause`, `graph_list_services`, and `graph_resolve_kubernetes_service`. The SRE agent’s **`graph`** contract group targets these on `graph-server` so RCA and remediation see **service dependencies and incident history** from the same Neo4j model Cartography and enrichment maintain.

---

## MCP (Model Context Protocol) in this repo

- **Service**: [`mcp/`](mcp/) — HTTP API (tools, servers, sessions, optional SSE). Default port **8005**.
- **Client used by orchestration**: [`agent-orchestration/app/services/mcp_client.py`](agent-orchestration/app/services/mcp_client.py) — `list_tools`, `call_tool`, and helpers such as `call_first_available_contract` for resilient multi-provider behavior.
- **Configuration**: `MCP_SERVICE_URL`, `MCP_SERVICE_TIMEOUT`, `MCP_API_KEY` / `MCP_API_KEY_HEADER` in orchestration settings.
- **SRE integration**: All structured infra/observability pulls that go through MCP are governed by the YAML-capable contract lists in `SREMultiAgent` plus `SRE_USE_MCP_FOR_CONTEXT_AGGREGATION`.

Dynamic provisioning workflows can also declare `mcp_client` as a step tool type (see [`agent-orchestration/data/workflows/README.md`](agent-orchestration/data/workflows/README.md)).

---

## Quick usage pointers

- **Run agent orchestration locally**: see **Installation** in [`agent-orchestration/README.md`](agent-orchestration/README.md) (`pip install -r requirements.txt`, `.env` from `.env.example`, `python -m app.main`).
- **Run MCP**: [`mcp/README.md`](mcp/README.md) (`python -m app.main` or uvicorn on **8005**).
- **Populate and enrich the graph**: [`mcp/INGESTION.md`](mcp/INGESTION.md) + Cartography schedule + optional [`scripts/run_graph_ingestion.py`](scripts/run_graph_ingestion.py).

For API details, environment variables, Docker Compose ports, and tests, prefer the per-component READMEs above.
