Hypothesis: {hypothesis}
Critique feedback: {critique_feedback}
Remediation iteration: {remediation_iteration}
Web findings: {web_findings_json}
Extracted dependencies: {extracted_dependencies_json}
Current graph context: {graph_context_json}
Current istio context: {istio_context_json}
Previous remediation plan: {previous_remediation_plan_json}
Previous additional context: {previous_additional_context_json}
Optional in-cluster DNS probes (debug pod): {debug_pod_dns_json}

Return:
{
  "dependency_services_to_check": ["..."],
  "secondary_signals": ["..."],
  "new_dependencies": [{"type":"...","name":"...","source":"..."}],
  "failure_type_candidates": ["DNS","timeout","connection_refused","other"],
  "recommended_followup_queries": ["..."],
  "dependency_findings_summary": [
    {
      "dependency": "...",
      "verdict": "confirmed_failed|confirmed_healthy|inconclusive",
      "failure_type": "...",
      "evidence": "..."
    }
  ]
}
