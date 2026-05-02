# Example Cypher Queries for Graph Enrichment

Use these in Neo4j Browser or any Neo4j client against the enriched graph.

## Database and USES

```cypher
// List all databases and their types
MATCH (d:Database) RETURN d.name, d.type, d.last_seen ORDER BY d.name;

// Services that use each database
MATCH (s)-[:USES]->(d:Database)
RETURN s.name AS service, d.name AS database, d.type ORDER BY service;

// Databases used by a specific service
MATCH (s)-[:USES]->(d:Database)
WHERE s.name = 'ems-user-svc'
RETURN d.name, d.type;
```

## Istio CALLS (service call graph)

```cypher
// Full call graph with request rate and latency
MATCH (a)-[r:CALLS]->(b)
RETURN a.name AS caller, b.name AS callee, r.request_rate, r.latency_ms
ORDER BY r.request_rate DESC;

// Downstream dependencies of a service
MATCH path = (a)-[:CALLS*1..3]->(b)
WHERE a.name = 'ems-api-gateway'
RETURN path;

// Services calling a specific database
MATCH (s)-[r:CALLS]->(d:Database)
WHERE d.name = 'ems-mongodb'
RETURN s.name, r.request_rate, r.latency_ms;
```

## Anomalies

```cypher
// Recent anomalies on services
MATCH (s)-[:HAS_ANOMALY]->(a:Anomaly)
RETURN s.name, a.type, a.value, a.timestamp, a.last_seen
ORDER BY a.timestamp DESC LIMIT 20;

// Database anomalies
MATCH (d:Database)-[:HAS_ANOMALY]->(a:Anomaly)
RETURN d.name, d.type, a.type, a.value, a.timestamp;

// Services with the most anomalies
MATCH (s)-[:HAS_ANOMALY]->(a:Anomaly)
RETURN s.name, count(a) AS anomaly_count ORDER BY anomaly_count DESC LIMIT 10;
```

## Error patterns

```cypher
// Error patterns by service
MATCH (s)-[:GENERATED]->(ep:ErrorPattern)
RETURN s.name, ep.signature, ep.count ORDER BY ep.count DESC;

// Error patterns from pods
MATCH (p:KubernetesPod)-[:GENERATED]->(ep:ErrorPattern)
RETURN p.name, ep.signature, ep.count LIMIT 20;
```

## Incidents and root cause

```cypher
// Incidents with severity and timestamp
MATCH (i:Incident) RETURN i.id, i.summary, i.severity, i.timestamp, i.updated_at ORDER BY i.timestamp DESC;

// Full incident context
MATCH (i:Incident)-[:IMPACTS]->(s)
OPTIONAL MATCH (i)-[:TRIGGERED_BY]->(a:Anomaly)
OPTIONAL MATCH (i)-[:EVIDENCED_BY]->(ep:ErrorPattern)
WHERE i.id = 'inc_xxx'
RETURN i, collect(DISTINCT s) AS impacted, collect(DISTINCT a) AS anomalies, collect(DISTINCT ep) AS error_patterns;

// Impact chain: Incident -> Service -> CALLS -> downstream
MATCH (i:Incident)-[:IMPACTS]->(s)-[r:CALLS]->(t)
RETURN i.id, s.name AS impacted_service, t.name AS downstream, r.request_rate
ORDER BY i.timestamp DESC;
```

## Combined exploration

```cypher
// Service dependency + anomalies (one-hop)
MATCH (s)-[:CALLS]->(d)
OPTIONAL MATCH (s)-[:HAS_ANOMALY]->(a:Anomaly)
WHERE s.name = 'ems-api-gateway'
RETURN s, d, a;

// Blast radius: service and all downstream services/databases
MATCH path = (s)-[:CALLS*0..5]->(node)
WHERE s.name = 'ems-user-svc'
RETURN path;
```

## Troubleshooting CALLS missing after graph/load

1. Check the API response: `istio_call_edges_discovered` vs `istio_calls_written`. If discovered is high but written is zero, Istio returned routes but Neo4j has no `KubernetesService`/`Service`/`Database` nodes whose `name` exactly matches the caller/callee host prefix (run Cartography sync, or align enrichment DB names with mesh hosts).
2. Set `GRAPH_ENRICHMENT_ISTIO_NAMESPACE` to the namespace that contains your VirtualServices (often not `default`).
3. Enrichment uses in-process MCP calls with full tool permissions; HTTP `curl` without `X-API-Key` still gets `viewer` and cannot execute tools — that does not affect `POST /api/v1/graph/load`.
