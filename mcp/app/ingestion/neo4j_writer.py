"""Neo4j writer for graph enrichment - Database, Anomaly, ErrorPattern, Incident, CALLS.

Uses MERGE for deduplication. Does not overwrite Cartography infrastructure data.
Links to existing Service, Pod nodes from Cartography.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

from app.core.logging import logger


class Neo4jWriter:
    """Writes enrichment nodes (Anomaly, ErrorPattern, Incident) to Neo4j."""

    def __init__(self, driver: Any, database: str = "neo4j") -> None:
        self._driver = driver
        self._database = database

    def write_databases(
        self,
        databases: List[Dict[str, Any]],
        service_uses: List[Dict[str, str]],
    ) -> int:
        """
        Create (:Database {name, type}) and (Service)-[:USES]->(Database).
        databases: [{"name": "rds-main", "type": "RDS"}, ...]
        service_uses: [{"service": "checkout", "database": "rds-main"}, ...]
        """
        written = 0
        now = datetime.now(timezone.utc).isoformat()
        for db in databases:
            name = db.get("name")
            db_type = db.get("type", "unknown")
            if not name:
                continue
            try:
                with self._driver.session(database=self._database) as session:
                    session.run(
                        """
                        MERGE (d:Database {name: $name})
                        ON CREATE SET d.type = $type, d.created_at = $now, d.last_seen = $now
                        ON MATCH SET d.type = $type, d.last_seen = $now
                        """,
                        {"name": name, "type": db_type, "now": now},
                    )
                    written += 1
            except Exception as exc:
                logger.warning("Failed to write database", database=name, exc=str(exc))

        for su in service_uses:
            svc = su.get("service")
            db_name = su.get("database")
            if not svc or not db_name:
                continue
            try:
                with self._driver.session(database=self._database) as session:
                    session.run(
                        """
                        MATCH (s) WHERE (s:KubernetesService OR s:Service) AND s.name = $svc
                        MATCH (d:Database {name: $db})
                        MERGE (s)-[r:USES]->(d)
                        ON CREATE SET r.created_at = $now, r.last_seen = $now
                        ON MATCH SET r.last_seen = $now
                        """,
                        {"svc": svc, "db": db_name, "now": now},
                    )
            except Exception as exc:
                logger.warning("Failed to link USES", service=svc, database=db_name, exc=str(exc))
        return written

    def write_istio_calls(
        self,
        calls: List[Dict[str, Any]],
    ) -> int:
        """
        Create (Service|Database)-[:CALLS {request_rate, latency}]->(Service|Database).
        calls: [{"caller": "api-gateway", "callee": "checkout", "request_rate": 150.0, "latency_ms": 45.0}, ...]
        """
        written = 0
        now = datetime.now(timezone.utc).isoformat()
        for c in calls:
            caller = c.get("caller")
            callee = c.get("callee")
            if not caller or not callee:
                continue
            req_rate = c.get("request_rate")
            latency = c.get("latency_ms")
            try:
                with self._driver.session(database=self._database) as session:
                    session.run(
                        """
                        MATCH (a) WHERE (a:KubernetesService OR a:Service OR a:Database) AND a.name = $caller
                        WITH a
                        MATCH (b) WHERE (b:KubernetesService OR b:Service OR b:Database) AND b.name = $callee
                        MERGE (a)-[r:CALLS]->(b)
                        ON CREATE SET r.request_rate = $req_rate, r.latency_ms = $latency,
                                       r.created_at = $now, r.last_seen = $now
                        ON MATCH SET r.request_rate = COALESCE($req_rate, r.request_rate),
                                     r.latency_ms = COALESCE($latency, r.latency_ms),
                                     r.last_seen = $now
                        """,
                        {
                            "caller": caller,
                            "callee": callee,
                            "req_rate": float(req_rate) if req_rate is not None else None,
                            "latency": float(latency) if latency is not None else None,
                            "now": now,
                        },
                    )
                    written += 1
            except Exception as exc:
                logger.warning("Failed to write CALLS", caller=caller, callee=callee, exc=str(exc))
        return written

    def write_istio_calls_batch(self, calls: List[Dict[str, Any]]) -> Tuple[int, int]:
        """
        Batch write CALLS. Returns (relationships_merged, skipped_no_endpoint).
        Skipped when caller or callee does not exist as KubernetesService, Service, or Database.
        """
        if not calls:
            return (0, 0)
        now = datetime.now(timezone.utc).isoformat()
        written = 0
        skipped = 0
        try:
            with self._driver.session(database=self._database) as session:
                for c in calls:
                    caller = c.get("caller")
                    callee = c.get("callee")
                    if not caller or not callee:
                        skipped += 1
                        continue
                    result = session.run(
                        """
                        MATCH (a) WHERE (a:KubernetesService OR a:Service OR a:Database) AND a.name = $caller
                        WITH a
                        MATCH (b) WHERE (b:KubernetesService OR b:Service OR b:Database) AND b.name = $callee
                        MERGE (a)-[r:CALLS]->(b)
                        ON CREATE SET r.request_rate = $req_rate, r.latency_ms = $latency,
                                       r.created_at = $now, r.last_seen = $now
                        ON MATCH SET r.request_rate = COALESCE($req_rate, r.request_rate),
                                     r.latency_ms = COALESCE($latency, r.latency_ms),
                                     r.last_seen = $now
                        RETURN 1 AS ok
                        """,
                        {
                            "caller": caller,
                            "callee": callee,
                            "req_rate": float(c.get("request_rate")) if c.get("request_rate") is not None else None,
                            "latency": float(c.get("latency_ms")) if c.get("latency_ms") is not None else None,
                            "now": now,
                        },
                    )
                    if result.single():
                        written += 1
                    else:
                        skipped += 1
        except Exception as exc:
            logger.warning("Failed batch write CALLS", exc=str(exc))
        return (written, skipped)

    def write_anomalies(
        self,
        anomalies: List[Dict[str, Any]],
        source_name: str,
        source_type: Literal["service", "database"] = "service",
        namespace: Optional[str] = None,
    ) -> int:
        """
        Create Anomaly nodes and (Service|Database)-[:HAS_ANOMALY]->(Anomaly).
        Uses MERGE on (type, value, timestamp) to deduplicate.
        source_type: "service" -> match KubernetesService/Service; "database" -> match Database
        """
        if not anomalies:
            return 0
        written = 0
        now = datetime.now(timezone.utc).isoformat()
        if source_type == "database":
            match_clause = "MATCH (s:Database {name: $source_name})\nWITH s"
        else:
            match_clause = """MATCH (s) WHERE (s:KubernetesService OR s:Service) AND s.name = $source_name
WITH s LIMIT 1"""
        for a in anomalies:
            a_type = a.get("type") or "unknown"
            value = a.get("value")
            ts = a.get("timestamp")
            if value is None or ts is None:
                continue
            query = f"""
            {match_clause}
            MERGE (anom:Anomaly {{type: $type, value: $value, timestamp: $timestamp}})
            ON CREATE SET anom.created_at = $now, anom.last_seen = $now
            ON MATCH SET anom.last_seen = $now
            WITH s, anom
            MERGE (s)-[:HAS_ANOMALY]->(anom)
            """
            params: Dict[str, Any] = {
                "source_name": source_name,
                "type": a_type,
                "value": float(value) if isinstance(value, (int, float)) else str(value),
                "timestamp": int(ts) if isinstance(ts, (int, float)) else ts,
                "now": now,
            }
            try:
                with self._driver.session(database=self._database) as session:
                    session.run(query, params)
                    written += 1
            except Exception as exc:
                logger.warning("Failed to write anomaly", anomaly=a, exc=str(exc))
        return written

    def write_error_patterns(
        self,
        patterns: List[Dict[str, Any]],
        pod_name: str,
        namespace: Optional[str] = None,
        service_name: Optional[str] = None,
    ) -> int:
        """
        Create ErrorPattern nodes and (Pod)-[:GENERATED]->(ErrorPattern).
        Falls back to (Service)-[:GENERATED]->(ErrorPattern) if no pod matches.
        Uses MERGE on signature to deduplicate.
        """
        if not patterns:
            return 0
        written = 0
        for p in patterns:
            sig = p.get("signature")
            count = p.get("count", 1)
            if not sig:
                continue
            query = """
            MERGE (ep:ErrorPattern {signature: $signature})
            ON CREATE SET ep.count = $count, ep.created_at = $now, ep.last_seen = $now
            ON MATCH SET ep.count = ep.count + $count, ep.last_seen = $now
            WITH ep
            MATCH (pod:KubernetesPod) WHERE pod.name = $pod_name
            WITH ep, pod LIMIT 1
            MERGE (pod)-[:GENERATED]->(ep)
            RETURN 1 AS c
            """
            params: Dict[str, Any] = {
                "pod_name": pod_name,
                "service_name": service_name or (pod_name.split("-")[0] if pod_name else "unknown"),
                "signature": sig[:500],
                "count": int(count),
                "now": datetime.now(timezone.utc).isoformat(),
            }
            try:
                with self._driver.session(database=self._database) as session:
                    result = session.run(query, params)
                    rec = result.single()
                    if rec and rec.get("c", 0) > 0:
                        written += 1
                    elif not rec:
                        fallback_query = """
                        MERGE (ep:ErrorPattern {signature: $signature})
                        ON CREATE SET ep.count = $count, ep.created_at = $now, ep.last_seen = $now
                        ON MATCH SET ep.count = ep.count + $count, ep.last_seen = $now
                        WITH ep
                        MATCH (svc)
                        WHERE (svc:KubernetesService AND svc.name = $service_name)
                           OR (svc:Service AND svc.name = $service_name)
                        WITH ep, svc LIMIT 1
                        MERGE (svc)-[:GENERATED]->(ep)
                        RETURN 1 AS c
                        """
                        result2 = session.run(fallback_query, params)
                        rec2 = result2.single()
                        if rec2 and rec2.get("c", 0) > 0:
                            written += 1
            except Exception as exc:
                logger.warning("Failed to write error pattern", pattern=p, exc=str(exc))
        return written

    def write_external_dependencies(
        self,
        dependencies: List[Dict[str, Any]],
    ) -> int:
        """
        Create dependencies inferred from logs:
        (Service)-[:USES]->(ExternalService|Database)
        """
        if not dependencies:
            return 0
        written = 0
        now = datetime.now(timezone.utc).isoformat()
        for dep in dependencies:
            service_name = dep.get("service_name")
            dependency_name = dep.get("dependency_name")
            dep_label = dep.get("dependency_label", "ExternalService")
            dep_type = dep.get("dependency_type", "unknown")
            evidence = dep.get("evidence", "")
            if not service_name or not dependency_name:
                continue
            if dep_label not in {"ExternalService", "Database"}:
                dep_label = "ExternalService"
            query = f"""
            MATCH (s) WHERE (s:KubernetesService OR s:Service) AND s.name = $service_name
            WITH s LIMIT 1
            MERGE (d:{dep_label} {{name: $dependency_name}})
            ON CREATE SET d.type = $dependency_type, d.created_at = $now, d.last_seen = $now
            ON MATCH SET d.type = COALESCE(d.type, $dependency_type), d.last_seen = $now
            MERGE (s)-[r:USES]->(d)
            ON CREATE SET r.created_at = $now, r.last_seen = $now, r.source = 'logs'
            ON MATCH SET r.last_seen = $now, r.source = 'logs'
            SET r.evidence = $evidence
            """
            try:
                with self._driver.session(database=self._database) as session:
                    session.run(
                        query,
                        {
                            "service_name": service_name,
                            "dependency_name": dependency_name,
                            "dependency_type": dep_type,
                            "evidence": evidence,
                            "now": now,
                        },
                    )
                    written += 1
            except Exception as exc:
                logger.warning(
                    "Failed to write dependency relationship",
                    service=service_name,
                    dependency=dependency_name,
                    exc=str(exc),
                )
        return written

    def write_incident(
        self,
        incident_id: str,
        summary: str,
        impacted_services: List[str],
        anomaly_ids: Optional[List[str]] = None,
        error_pattern_signatures: Optional[List[str]] = None,
        severity: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> bool:
        """
        Create Incident and link:
        (Incident)-[:IMPACTS]->(Service)
        (Incident)-[:TRIGGERED_BY]->(Anomaly)
        (Incident)-[:EVIDENCED_BY]->(ErrorPattern)
        """
        now = datetime.now(timezone.utc).isoformat()
        ts = timestamp or now
        sev = severity or "medium"
        query = """
        MERGE (i:Incident {id: $incident_id})
        ON CREATE SET i.summary = $summary, i.severity = $severity, i.timestamp = $ts,
                       i.created_at = $now, i.updated_at = $now
        ON MATCH SET i.summary = $summary, i.severity = $severity, i.timestamp = $ts,
                     i.updated_at = $now
        """
        params: Dict[str, Any] = {
            "incident_id": incident_id,
            "summary": summary,
            "severity": sev,
            "ts": ts,
            "now": now,
        }
        # Link to services
        for svc in impacted_services[:20]:
            link_query = """
            MATCH (i:Incident {id: $incident_id})
            MATCH (s) WHERE (s:KubernetesService AND s.name = $svc) OR (s:Service AND s.name = $svc)
            MERGE (i)-[:IMPACTS]->(s)
            """
            try:
                with self._driver.session(database=self._database) as session:
                    session.run(link_query, {"incident_id": incident_id, "svc": svc})
            except Exception as exc:
                logger.warning("Failed to link incident to service", service=svc, exc=str(exc))

        # Link to anomalies (by type+value+timestamp as id substitute)
        if anomaly_ids:
            for aid in anomaly_ids[:20]:
                link_q = """
                MATCH (i:Incident {id: $incident_id})
                MATCH (a:Anomaly) WHERE a.timestamp = $aid OR toString(a.timestamp) = $aid
                MERGE (i)-[:TRIGGERED_BY]->(a)
                """
                try:
                    with self._driver.session(database=self._database) as session:
                        session.run(link_q, {"incident_id": incident_id, "aid": aid})
                except Exception as exc:
                    logger.warning("Failed to link incident to anomaly", exc=str(exc))

        # Link to error patterns
        if error_pattern_signatures:
            for sig in error_pattern_signatures[:20]:
                link_q = """
                MATCH (i:Incident {id: $incident_id})
                MATCH (ep:ErrorPattern {signature: $sig})
                MERGE (i)-[:EVIDENCED_BY]->(ep)
                """
                try:
                    with self._driver.session(database=self._database) as session:
                        session.run(link_q, {"incident_id": incident_id, "sig": sig[:500]})
                except Exception as exc:
                    logger.warning("Failed to link incident to error pattern", exc=str(exc))

        try:
            with self._driver.session(database=self._database) as session:
                session.run(query, params)
            return True
        except Exception as exc:
            logger.warning("Failed to write incident", incident_id=incident_id, exc=str(exc))
            return False
