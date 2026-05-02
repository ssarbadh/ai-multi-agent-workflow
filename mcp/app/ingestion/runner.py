"""Orchestrator for graph enrichment - Prometheus + Logs + Istio + Databases -> Neo4j."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List, Optional

from neo4j import GraphDatabase

from app.core.config import settings
from app.core.logging import logger
from app.ingestion.prometheus_processor import PrometheusProcessor
from app.ingestion.logs_processor import LogsProcessor
from app.ingestion.neo4j_writer import Neo4jWriter
from app.ingestion.istio_processor import IstioProcessor


# Default databases and service->database mapping for enrichment
DEFAULT_DATABASES: List[Dict[str, Any]] = [
    {"name": "ems-rds-main", "type": "RDS"},
    {"name": "ems-mongodb", "type": "Mongo"},
    {"name": "ems-redis-cache", "type": "Redis"},
]
DEFAULT_SERVICE_USES: List[Dict[str, str]] = [
    {"service": "ems-user-svc", "database": "ems-mongodb"},
    {"service": "ems-orchestration-svc", "database": "ems-rds-main"},
    {"service": "ems-api-gateway", "database": "ems-redis-cache"},
]


async def run_enrichment_async(
    *,
    services: Optional[List[str]] = None,
    use_simulated: bool = False,
    create_incident: bool = False,
    ingest_databases: bool = True,
    ingest_istio: bool = True,
) -> Dict[str, Any]:
    """
    Async enrichment pipeline (use from FastAPI). Istio uses in-process gateway
    with admin permissions instead of HTTP /tools/call (which denies viewer role).
    """
    result: Dict[str, Any] = {
        "anomalies_written": 0,
        "error_patterns_written": 0,
        "dependencies_written": 0,
        "incidents_created": 0,
        "databases_written": 0,
        "istio_calls_written": 0,
        "istio_call_edges_discovered": 0,
        "errors": [],
        "services_processed": [],
    }
    neo4j_uri = getattr(settings, "GRAPH_MCP_NEO4J_URI", "") or ""
    if not neo4j_uri:
        result["errors"].append("GRAPH_MCP_NEO4J_URI not configured")
        return result

    driver = None
    try:
        driver = GraphDatabase.driver(
            neo4j_uri,
            auth=(
                getattr(settings, "GRAPH_MCP_NEO4J_USER", "neo4j"),
                getattr(settings, "GRAPH_MCP_NEO4J_PASSWORD", ""),
            ),
        )
        driver.verify_connectivity()
    except Exception as exc:
        result["errors"].append(f"Neo4j connection failed: {exc}")
        return result

    database = getattr(settings, "GRAPH_MCP_NEO4J_DATABASE", "neo4j") or "neo4j"
    istio_namespace = getattr(settings, "GRAPH_ENRICHMENT_ISTIO_NAMESPACE", "default") or "default"

    prom = PrometheusProcessor()
    logs_proc = LogsProcessor()
    writer = Neo4jWriter(driver, database=database)

    if not services:
        try:
            with driver.session(database=database) as session:
                r = session.run(
                    "MATCH (s) WHERE s:KubernetesService OR s:Service RETURN s.name AS n LIMIT 20"
                )
                services = [rec["n"] for rec in r if rec.get("n")]
        except Exception:
            pass
        if not services:
            services = ["checkout", "payment", "api-gateway", "ems-api-gateway", "ems-user-svc", "ems-orchestration-svc"]

    if ingest_databases:
        try:
            dbs = getattr(settings, "GRAPH_ENRICHMENT_DATABASES", None) or DEFAULT_DATABASES
            uses = getattr(settings, "GRAPH_ENRICHMENT_SERVICE_USES", None) or DEFAULT_SERVICE_USES
            result["databases_written"] = writer.write_databases(
                dbs if isinstance(dbs, list) else list(dbs),
                uses if isinstance(uses, list) else list(uses),
            )
        except Exception as exc:
            result["errors"].append(f"Database ingestion: {exc}")

    if ingest_istio:
        try:
            istio = IstioProcessor()
            calls = await istio.process_services_async(
                services,
                istio_namespace,
                use_simulated=use_simulated,
                use_internal_gateway=True,
            )
            result["istio_call_edges_discovered"] = len(calls)
            written, skipped = writer.write_istio_calls_batch(calls)
            result["istio_calls_written"] = written
            if skipped and not use_simulated:
                logger.info(
                    "Istio CALLS edges skipped (no matching Neo4j endpoints)",
                    skipped=skipped,
                    discovered=len(calls),
                    namespace=istio_namespace,
                )
            istio.close()
        except Exception as exc:
            result["errors"].append(f"Istio ingestion: {exc}")
            logger.warning("Istio ingestion failed", exc=str(exc))

    all_anomalies: List[Dict[str, Any]] = []
    all_patterns: List[Dict[str, Any]] = []
    pattern_signatures: List[str] = []

    for svc in services[:20]:
        try:
            anomalies = prom.process_service(svc, use_simulated=use_simulated)
            for a in anomalies:
                a["_service"] = svc
                all_anomalies.append(a)
            written_a = writer.write_anomalies(anomalies, svc, source_type="service")
            result["anomalies_written"] += written_a
            result["services_processed"].append(svc)

            logs = logs_proc.get_logs_simulated(svc) if use_simulated else []
            if not logs and not use_simulated:
                logs = logs_proc.get_logs_simulated(svc)
            patterns = logs_proc.extract_error_patterns(logs)
            dependencies = logs_proc.extract_dependencies_from_logs(logs, svc)
            pod_name = f"{svc}-xxxx"
            for p in patterns:
                pattern_signatures.append(p.get("signature", ""))
            written_p = 0
            for p in patterns:
                written_p += writer.write_error_patterns([p], pod_name, service_name=svc)
            result["error_patterns_written"] += written_p
            result["dependencies_written"] += writer.write_external_dependencies(dependencies)
        except Exception as exc:
            result["errors"].append(f"{svc}: {exc}")
            logger.warning("Enrichment failed for service", service=svc, exc=str(exc))

    if ingest_databases:
        dbs = getattr(settings, "GRAPH_ENRICHMENT_DATABASES", None) or DEFAULT_DATABASES
        for db in (dbs if isinstance(dbs, list) else [])[:10]:
            name = db.get("name")
            db_type = db.get("type", "RDS")
            if not name:
                continue
            try:
                db_anomalies = prom.process_database(name, db_type, use_simulated=use_simulated)
                for a in db_anomalies:
                    a["_database"] = name
                    all_anomalies.append(a)
                result["anomalies_written"] += writer.write_anomalies(
                    db_anomalies, name, source_type="database"
                )
            except Exception as exc:
                result["errors"].append(f"Database anomaly {name}: {exc}")

    prom.close()

    if create_incident and (all_anomalies or all_patterns):
        inc_id = f"inc_{uuid.uuid4().hex[:12]}"
        summary = "Auto-created incident from enrichment run"
        impacted = list(set(s.get("_service") for s in all_anomalies if s.get("_service")))
        if not impacted:
            impacted = services[:5]
        anomaly_ids = [str(a.get("timestamp", "")) for a in all_anomalies[:10]]
        ok = writer.write_incident(
            inc_id,
            summary,
            impacted,
            anomaly_ids=anomaly_ids[:5] if anomaly_ids else None,
            error_pattern_signatures=pattern_signatures[:5] or None,
            severity="medium",
            timestamp=None,
        )
        if ok:
            result["incidents_created"] = 1
            result["incident_id"] = inc_id

    if driver:
        driver.close()
    return result


def run_enrichment(
    *,
    services: Optional[List[str]] = None,
    use_simulated: bool = False,
    create_incident: bool = False,
    ingest_databases: bool = True,
    ingest_istio: bool = True,
) -> Dict[str, Any]:
    """
    Sync wrapper for CLI/scripts. Uses asyncio.run (not valid inside a running event loop).
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            run_enrichment_async(
                services=services,
                use_simulated=use_simulated,
                create_incident=create_incident,
                ingest_databases=ingest_databases,
                ingest_istio=ingest_istio,
            )
        )
    raise RuntimeError("run_enrichment() cannot be called from async code; use await run_enrichment_async()")
