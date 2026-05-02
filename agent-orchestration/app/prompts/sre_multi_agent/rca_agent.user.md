Incident: {incident_title}
Description: {incident_description}
Target service: {target_service}
Context summary: {context_summary}
Logs (normalized): {logs_json}
Log evidence digest: {log_evidence_digest_json}
Metrics: {metrics_json}
Metrics evidence digest: {metrics_evidence_digest_json}
Alerts: {alerts_json}
Knowledge base results: {rag_docs_json}
Istio service mesh context (VirtualServices, DestinationRules, pods): {istio_context_json}
Graph context (service dependencies, recent incidents from Cartography/Neo4j): {graph_context_json}
Extracted dependencies from logs: {extracted_dependencies_json}
Converted metric anomalies: {metric_anomalies_json}
Missing observability signals: {observability_missing_json}
Dependency findings (if available): {dependency_findings_json}
External dependency evaluations (inventory/cloud existence checks): {external_dependency_evaluations_json}
Debug pod DNS checks (if available): {debug_pod_dns_json}

Set `requires_more_data=false` whenever `is_terminal=true`.
For terminal `RUNTIME_FAILURE`, include concrete `terminal_evidence` from runtime exception/config error logs.

Output must include:
{
  "root_cause": "...",
  "category": "DNS_RESOURCE_MISSING|DEPENDENCY_UNAVAILABLE|RUNTIME_FAILURE|RESOURCE_EXHAUSTION|unknown",
  "confidence": 0.0,
  "is_terminal": false,
  "requires_more_data": true,
  "terminal_evidence": ["..."],
  "terminal_dependency": "...",
  "suspected_component": "...",
  "impacted_services": ["..."],
  "evidence_sources": ["..."],
  "root_cause_explanation": "...",
  "confidence_indicators": ["..."],
  "dependency_chain": "service -> dependency -> failure",
  "failure_type": "DNS|timeout|connection_refused|auth|unknown"
}
