Previous hypothesis: {hypothesis}
Logs (normalized): {logs_json}
Log evidence digest: {log_evidence_digest_json}
Metrics: {metrics_json}
Metrics evidence digest: {metrics_evidence_digest_json}
Web findings: {web_findings_json}
Critique feedback: {critique_feedback}
Extracted dependencies: {extracted_dependencies_json}
Additional refreshed context: {additional_context_json}
Dependency findings (confirmed_failed/confirmed_healthy/inconclusive): {dependency_findings_json}
Graph context: {graph_context_json}
Istio context: {istio_context_json}

Set `requires_more_data=false` whenever `is_terminal=true`.
For terminal `RUNTIME_FAILURE`, include concrete `terminal_evidence` from runtime exception/config error logs.

Return:
{
  "root_cause": "...",
  "root_cause_category": "DNS_RESOURCE_MISSING|DEPENDENCY_UNAVAILABLE|RUNTIME_FAILURE|RESOURCE_EXHAUSTION|unknown",
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
