"""Neo4j graph repository for dependency and incident queries.

Supports both Cartography schema (KubernetesService, KubernetesPod) and
AegisOps context graph (Service, Incident, RootCause).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.logging import logger


class GraphRepository:
    """Repository for Neo4j graph queries."""

    def __init__(self, driver: Any, database: str = "neo4j") -> None:
        self._driver = driver
        self._database = database

    def get_service_dependencies(
        self,
        service_name: str,
        namespace: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Get services and pods that a service depends on or targets.

        Cartography: KubernetesService -[:TARGETS]-> KubernetesPod
        Also matches Service name across namespaces.
        """
        params: Dict[str, Any] = {
            "service_name": service_name,
            "service_name_lower": service_name.lower(),
            "limit": limit,
            "namespace": namespace,
        }
        query = """
        MATCH (s)
        WHERE (s:KubernetesService OR s:Service)
          AND (
            toLower(s.name) = $service_name_lower
            OR toLower(replace(replace(s.name, '-service', ''), '-deployment', '')) = $service_name_lower
            OR toLower($service_name) CONTAINS toLower(s.name)
            OR toLower(s.name) CONTAINS $service_name_lower
          )
          AND ($namespace IS NULL OR $namespace = '' OR s.namespace = $namespace)
        WITH s LIMIT 1
        OPTIONAL MATCH (s)-[:TARGETS]->(pod)
        OPTIONAL MATCH (s)-[:DEPENDS_ON|CALLS|USES]->(dep)
        WITH s,
             collect(DISTINCT {type: 'pod', name: pod.name, namespace: pod.namespace}) AS pods,
             collect(
               DISTINCT {
                 type: CASE
                   WHEN dep:Database THEN 'database'
                   WHEN dep:ExternalService THEN 'external_service'
                   ELSE 'service'
                 END,
                 name: dep.name,
                 namespace: dep.namespace
               }
             ) AS deps
        RETURN s.name AS service_name,
               s.namespace AS namespace,
               [p IN pods WHERE p.name IS NOT NULL | p] AS pods,
               [d IN deps WHERE d.name IS NOT NULL | d] AS dependencies
        LIMIT 1
        """
        rows = self._run_query(query, params)
        if rows:
            return rows
        # Fallback: return a synthetic row for direct dependency nodes if service node wasn't matched.
        fallback_query = """
        MATCH (dep)
        WHERE (dep:Database OR dep:ExternalService OR dep:Service OR dep:KubernetesService)
          AND toLower(dep.name) CONTAINS $service_name_lower
        RETURN $service_name AS service_name,
               $namespace AS namespace,
               [] AS pods,
               collect(DISTINCT {
                 type: CASE
                   WHEN dep:Database THEN 'database'
                   WHEN dep:ExternalService THEN 'external_service'
                   ELSE 'service'
                 END,
                 name: dep.name,
                 namespace: dep.namespace
               }) AS dependencies
        LIMIT 1
        """
        return self._run_query(fallback_query, params)

    def get_upstream_services(
        self,
        service_name: str,
        namespace: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Find services that route to or depend on the given service.
        Cartography: reverse TARGETS, or RESOURCE from cluster.
        """
        query = """
        MATCH (upstream)-[r:TARGETS|DEPENDS_ON|ROUTES_TO]->(s)
        WHERE (s:KubernetesService AND s.name = $service_name)
           OR (s:Service AND s.name = $service_name)
        RETURN DISTINCT upstream.name AS upstream_service,
               type(r) AS relationship
        LIMIT $limit
        """
        params: Dict[str, Any] = {
            "service_name": service_name,
            "limit": limit,
        }
        if namespace:
            params["namespace"] = namespace
        return self._run_query(query, params)

    def trace_dependency_path(
        self,
        service_name: str,
        direction: str = "downstream",
        max_depth: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Trace dependency path from a service (downstream or upstream).
        direction: 'downstream' = what this service targets, 'upstream' = what targets this
        """
        depth = min(max_depth, 5)
        if direction == "upstream":
            query = """
            MATCH path = (start)<-[:TARGETS|DEPENDS_ON|ROUTES_TO*1..%d]-(node)
            WHERE (start:KubernetesService AND start.name = $service_name)
               OR (start:Service AND start.name = $service_name)
            WITH nodes(path) AS path_nodes
            UNWIND path_nodes AS n
            RETURN labels(n)[0] AS node_type, n.name AS name, n.namespace AS namespace
            """ % depth
        else:
            query = """
            MATCH path = (start)-[:TARGETS|DEPENDS_ON|ROUTES_TO*1..%d]->(node)
            WHERE (start:KubernetesService AND start.name = $service_name)
               OR (start:Service AND start.name = $service_name)
            WITH nodes(path) AS path_nodes
            UNWIND path_nodes AS n
            RETURN labels(n)[0] AS node_type, n.name AS name, n.namespace AS namespace
            """ % depth
        return self._run_query(query, {"service_name": service_name})

    def get_incident_root_cause(self, incident_id: str) -> List[Dict[str, Any]]:
        """Get root cause and remediation for an incident from context graph."""
        query = """
        MATCH (i:Incident {id: $incident_id})-[:AFFECTS]->(s:Service)
        OPTIONAL MATCH (s)-[:HAS_ROOT_CAUSE]->(rc:RootCause)
        OPTIONAL MATCH (rc)-[:HAS_REMEDIATION]->(r:Remediation)
        RETURN i.id AS incident_id,
               i.summary AS incident_summary,
               s.name AS service,
               rc.name AS root_cause,
               r.summary AS remediation
        """
        return self._run_query(query, {"incident_id": incident_id})

    def get_recent_incidents(
        self,
        service_name: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Get recent incidents affecting a service."""
        query = """
        MATCH (i:Incident)-[:AFFECTS]->(s)
        WHERE (s:Service AND s.name = $service_name)
           OR (s:KubernetesService AND s.name = $service_name)
        OPTIONAL MATCH (s)-[:HAS_ROOT_CAUSE]->(rc:RootCause)
        RETURN i.id AS incident_id,
               i.summary AS incident_summary,
               i.updated_at AS updated_at,
               s.name AS service,
               rc.name AS root_cause
        ORDER BY i.updated_at DESC
        LIMIT $limit
        """
        return self._run_query(query, {"service_name": service_name, "limit": limit})

    def get_recent_anomalies(
        self,
        service_name: str,
        namespace: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Get recent anomalies for a service from the graph."""
        query = """
        MATCH (s)-[:HAS_ANOMALY]->(a:Anomaly)
        WHERE (s:KubernetesService AND s.name = $service_name)
           OR (s:Service AND s.name = $service_name)
        RETURN a.type AS type, a.value AS value, a.timestamp AS timestamp, a.last_seen AS last_seen
        ORDER BY a.timestamp DESC
        LIMIT $limit
        """
        params: Dict[str, Any] = {"service_name": service_name, "limit": limit}
        if namespace:
            params["namespace"] = namespace
        return self._run_query(query, params)

    def get_impacted_services(
        self,
        service_name: str,
        direction: str = "downstream",
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Get services impacted when the given service has issues.
        downstream = services that depend on this one.
        upstream = services this one depends on.
        """
        if direction == "upstream":
            query = """
            MATCH path = (start)<-[:TARGETS|DEPENDS_ON|ROUTES_TO*1..3]-(node)
            WHERE (start:KubernetesService AND start.name = $service_name)
               OR (start:Service AND start.name = $service_name)
            WITH DISTINCT node
            WHERE node:KubernetesService OR node:Service
            RETURN node.name AS name, node.namespace AS namespace
            LIMIT $limit
            """
        else:
            query = """
            MATCH path = (start)-[:TARGETS|DEPENDS_ON|ROUTES_TO*1..3]->(node)
            WHERE (start:KubernetesService AND start.name = $service_name)
               OR (start:Service AND start.name = $service_name)
            WITH DISTINCT node
            WHERE node:KubernetesService OR node:Service
            RETURN node.name AS name, node.namespace AS namespace
            LIMIT $limit
            """
        return self._run_query(query, {"service_name": service_name, "limit": limit})

    def get_incident_root_cause_extended(self, incident_id: str) -> List[Dict[str, Any]]:
        """Get root cause including anomalies and error patterns linked to incident."""
        query = """
        MATCH (i:Incident {id: $incident_id})
        OPTIONAL MATCH (i)-[:IMPACTS]->(s)
        OPTIONAL MATCH (i)-[:TRIGGERED_BY]->(a:Anomaly)
        OPTIONAL MATCH (i)-[:EVIDENCED_BY]->(ep:ErrorPattern)
        RETURN i.id AS incident_id,
               i.summary AS summary,
               collect(DISTINCT s.name) AS impacted_services,
               collect(DISTINCT {type: a.type, value: a.value, timestamp: a.timestamp}) AS anomalies,
               collect(DISTINCT {signature: ep.signature, count: ep.count}) AS error_patterns
        """
        return self._run_query(query, {"incident_id": incident_id})

    def resolve_kubernetes_service(self, name_hint: str) -> Optional[Dict[str, Any]]:
        """Resolve a Kubernetes service name to graph name + namespace (Cartography / context graph).

        Uses case-insensitive exact match first, then substring match — avoids relying on
        list_services + arbitrary LIMIT ordering.
        """
        hint = (name_hint or "").strip()
        if not hint:
            return None
        exact = """
            MATCH (s)
            WHERE (s:KubernetesService OR s:Service)
              AND toLower(s.name) = toLower($hint)
            RETURN s.name AS name, s.namespace AS namespace
            LIMIT 5
            """
        rows = self._run_query(exact, {"hint": hint})
        if rows:
            r0 = rows[0]
            return {
                "name": r0.get("name"),
                "namespace": r0.get("namespace"),
            }
        contains = """
            MATCH (s)
            WHERE (s:KubernetesService OR s:Service)
              AND toLower(s.name) CONTAINS toLower($hint)
            RETURN s.name AS name, s.namespace AS namespace
            LIMIT 5
            """
        rows = self._run_query(contains, {"hint": hint})
        if rows:
            r0 = rows[0]
            return {
                "name": r0.get("name"),
                "namespace": r0.get("namespace"),
            }
        return None

    def find_resource_by_endpoint(self, endpoint: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Find infrastructure resources by endpoint/DNS-like identifier in Cartography graph."""
        needle = (endpoint or "").strip().lower()
        if not needle:
            return []
        params = {"needle": needle, "limit": max(1, min(limit, 50))}
        query = """
        MATCH (n)
        WHERE any(label IN labels(n) WHERE label IN [
            'AWSLoadBalancer','AWSRDSInstance','AWSRDSCluster','AWSElastiCacheCluster','S3Bucket',
            'ExternalService','Database','KubernetesService','Service'
        ])
          AND (
            toLower(coalesce(n.dnsname, '')) CONTAINS $needle OR
            toLower(coalesce(n.dns_name, '')) CONTAINS $needle OR
            toLower(coalesce(n.endpoint, '')) CONTAINS $needle OR
            toLower(coalesce(n.address, '')) CONTAINS $needle OR
            toLower(coalesce(n.hostname, '')) CONTAINS $needle OR
            toLower(coalesce(n.host, '')) CONTAINS $needle OR
            toLower(coalesce(n.name, '')) CONTAINS $needle OR
            toLower(coalesce(n.id, '')) CONTAINS $needle OR
            toLower(coalesce(n.arn, '')) CONTAINS $needle
          )
        RETURN labels(n) AS labels,
               n.name AS name,
               n.id AS id,
               n.namespace AS namespace,
               n.arn AS arn,
               n.region AS region,
               coalesce(n.dnsname, n.dns_name, n.endpoint, n.address, n.hostname, n.host) AS endpoint
        LIMIT $limit
        """
        return self._run_query(query, params)

    def list_services(self, namespace: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """List services from Cartography or context graph."""
        if namespace:
            query = """
            MATCH (s)
            WHERE (s:KubernetesService AND s.namespace = $namespace)
               OR (s:Service)
            RETURN DISTINCT s.name AS name, s.namespace AS namespace
            LIMIT $limit
            """
            params: Dict[str, Any] = {"namespace": namespace, "limit": limit}
        else:
            query = """
            MATCH (s)
            WHERE s:KubernetesService OR s:Service
            RETURN DISTINCT s.name AS name, s.namespace AS namespace
            LIMIT $limit
            """
            params = {"limit": limit}
        return self._run_query(query, params)

    def _run_query(self, query: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Execute Cypher and return list of record dicts."""
        if not self._driver:
            return []
        try:
            with self._driver.session(database=self._database) as session:
                result = session.run(query, params)
                return [dict(record) for record in result]
        except Exception as exc:
            logger.warning("Graph query failed", query=query[:100], exc=str(exc))
            return []
