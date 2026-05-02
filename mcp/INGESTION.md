# Graph Enrichment Ingestion

Enriches the Neo4j graph (populated by Cartography) with runtime signals:

- **Database** → `(:Database {name, type})`, `(Service)-[:USES]->(Database)`
- **Istio** → `(Service)-[:CALLS {request_rate, latency}]->(Service|Database)`
- **Prometheus** → anomalies → `(Service|Database)-[:HAS_ANOMALY]->(Anomaly)`
- **Logs** → `(Pod|Service)-[:GENERATED]->(ErrorPattern)`
- **Incident** → `(Incident)-[:IMPACTS]->(Service)`, `[:TRIGGERED_BY]->(Anomaly)`, `[:EVIDENCED_BY]->(ErrorPattern)`

## Triggers

### 1. Load endpoint (recommended)

```bash
curl -X POST http://localhost:8005/api/v1/graph/load \
  -H "Content-Type: application/json" \
  -d '{"use_simulated": true, "create_incident": true, "ingest_databases": true, "ingest_istio": true}'
```

**Istio-only ingestion** (requires Istio MCP and GRAPH_ENRICHMENT_MCP_URL):

```bash
curl -X POST http://localhost:8005/api/v1/graph/load \
  -H "Content-Type: application/json" \
  -d '{"services": ["ems-api-gateway", "ems-user-svc"], "use_simulated": false, "ingest_istio": true}'
```

Schedule via cron:

```
*/15 * * * * curl -s -X POST http://mcp:8005/api/v1/graph/load -H "Content-Type: application/json" -d '{"use_simulated": false}'
```

### 2. CLI script (requires mcp deps: `pip install -r mcp/requirements.txt`)

```bash
cd aegisops-prod/mcp
PYTHONPATH=. python ../scripts/run_graph_ingestion.py --create-incident
```

With Istio and databases:

```bash
PYTHONPATH=. python ../scripts/run_graph_ingestion.py --create-incident
# Skip Istio or databases: --no-istio, --no-databases
```

Or inside MCP container:

```bash
docker compose exec mcp python -c "
from app.ingestion.runner import run_enrichment
print(run_enrichment(use_simulated=True, ingest_databases=True, ingest_istio=True))
"
```

### 3. Cartography (infrastructure only)

Cartography runs once and exits. Schedule separately:

```bash
# Cron (e.g. hourly)
0 * * * * cd /path/to/aegisops-prod && docker compose run --rm cartography
```

## Istio auth and namespace

- **In-process tools**: `POST /api/v1/graph/load` uses the gateway with an internal admin-equivalent user so enrichment does not depend on `curl` API keys or anonymous `viewer` role (which cannot execute tools).
- **Namespace**: Set `GRAPH_ENRICHMENT_ISTIO_NAMESPACE` to one or more namespaces (comma-separated), e.g. `flights,activity`, so both mesh config and Neo4j `KubernetesService` names can align. Cartography may ingest services from `activity` while VirtualServices live in `flights`.
- **Cluster-wide**: `GRAPH_ENRICHMENT_ISTIO_CLUSTER_WIDE=true` lists all VirtualServices in the cluster (needs `list` on `virtualservices.networking.istio.io` at cluster scope).
- **Kubernetes 401 inside Docker**: The `(401) Reason: Unauthorized` in logs is the **Kubernetes API**, not MCP. Refresh credentials in the mounted kubeconfig (exec auth / GKE token often fails in minimal containers), use `ISTIO_MCP_IN_CLUSTER=true` with a service account that can list Istio CRs, or run MCP where `kubectl` works.
- **CLI / HTTP fallback**: If you call tools over HTTP, set `GRAPH_ENRICHMENT_MCP_API_KEY` to a valid key from `API_KEYS` (same as `MCP_API_KEY` in compose).

## Modules

- `app/ingestion/istio_processor.py` – fetches Istio call graph via MCP, builds CALLS
- `app/ingestion/internal_mcp_tools.py` – in-process tool execution for enrichment
- `app/ingestion/prometheus_processor.py` – fetches metrics (service + database), detects anomalies
- `app/ingestion/logs_processor.py` – parses logs, extracts error patterns
- `app/ingestion/neo4j_writer.py` – writes with MERGE (Database, CALLS, Anomaly, ErrorPattern, Incident)

## Sample simulated data

See `scripts/sample_simulated_data.json` for Istio calls, databases, anomalies, and error patterns.

## Example Cypher queries

See `scripts/cypher_examples.md`.

## Graph MCP tools

- `graph_get_service_dependencies(service)`
- `graph_get_impacted_services(service, direction)`
- `graph_get_recent_anomalies(service)`
- `graph_get_incident_root_cause(incident_id)`
