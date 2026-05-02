"""Neo4j-backed context graph service for incident relationships."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class ContextGraphService:
    """Service for querying and updating incident context graph in Neo4j."""

    def __init__(self) -> None:
        self._driver = None
        self._enabled = False
        self._init_driver()

    def _init_driver(self) -> None:
        if not settings.NEO4J_URI:
            logger.info("Neo4j URI not configured; context graph updates disabled")
            return

        try:
            from neo4j import GraphDatabase  # Lazy import to keep optional dependency

            self._driver = GraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
            )
            self._enabled = True
            logger.info("Context graph service initialized")
        except Exception as exc:
            logger.warning("Neo4j initialization failed: %s", exc)
            self._enabled = False

    @property
    def is_enabled(self) -> bool:
        return self._enabled and self._driver is not None

    async def query_related_context(self, service_name: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Return recent incidents/root-causes connected to a service."""
        if not self.is_enabled or not service_name:
            return []

        query = """
        MATCH (s {name: $service_name})
        OPTIONAL MATCH (i)-[rel]->(s)
        WHERE type(rel) IN ["AFFECTS", "IMPACTS"]
        OPTIONAL MATCH (s)-[:HAS_ROOT_CAUSE]->(rc)
        OPTIONAL MATCH (rc)-[:HAS_REMEDIATION]->(r)
        RETURN i.id AS incident_id,
               coalesce(i.summary, i.title, i.description, i.id) AS incident_summary,
               coalesce(i.created_at, i.updated_at) AS incident_created_at,
               rc.name AS root_cause,
               r.summary AS remediation
        ORDER BY coalesce(incident_created_at, "") DESC
        LIMIT $limit
        """

        try:
            records: List[Dict[str, Any]] = []
            with self._driver.session(database=settings.NEO4J_DATABASE) as session:
                result = session.run(query, service_name=service_name, limit=limit)
                for row in result:
                    records.append(dict(row))
            return records
        except Exception as exc:
            logger.warning("Failed querying context graph: %s", exc)
            return []

    async def upsert_incident_relationships(
        self,
        incident_id: str,
        service_name: str,
        root_cause: str,
        remediation_summary: str,
    ) -> Dict[str, Any]:
        """Persist Incident -> Service -> RootCause -> Remediation relationships."""
        if not self.is_enabled:
            return {"status": "skipped", "reason": "neo4j_not_configured"}

        query = """
        MERGE (i:Incident {id: $incident_id})
        SET i.updated_at = datetime(), i.summary = coalesce(i.summary, $incident_id)
        MERGE (s:Service:KubernetesService {name: $service_name})
        MERGE (rc:RootCause {name: $root_cause})
        MERGE (r:Remediation {summary: $remediation_summary})
        MERGE (i)-[:AFFECTS]->(s)
        MERGE (i)-[:IMPACTS]->(s)
        MERGE (s)-[:HAS_ROOT_CAUSE]->(rc)
        MERGE (rc)-[:HAS_REMEDIATION]->(r)
        RETURN i.id AS incident_id, s.name AS service, rc.name AS root_cause
        """

        try:
            with self._driver.session(database=settings.NEO4J_DATABASE) as session:
                row = session.run(
                    query,
                    incident_id=incident_id,
                    service_name=service_name or "unknown-service",
                    root_cause=root_cause or "unknown-root-cause",
                    remediation_summary=remediation_summary or "manual remediation",
                ).single()
            return {"status": "updated", "graph_record": dict(row) if row else {}}
        except Exception as exc:
            logger.warning("Failed updating context graph: %s", exc)
            return {"status": "failed", "error": str(exc)}


context_graph_service = ContextGraphService()

