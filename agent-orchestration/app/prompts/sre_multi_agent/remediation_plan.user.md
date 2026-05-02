Hypothesis: {hypothesis}
Evidence: {evidence_json}
Confidence score: {confidence_score}
Remediation iteration: {remediation_iteration}

Target service (from incident): {target_service}
Failing component (RCA): {failing_service}

**Cartography / graph MCP facts (use for concrete kubectl -n and resource names):**
{graph_remediation_facts_json}

**Full graph context (dependencies from Neo4j / Cartography):**
{graph_context_json}

**Istio workload context (namespace, pods, if collected):**
{istio_context_json}

**Dependencies extracted from logs (fallback when graph is sparse):**
{extracted_dependencies_json}

Detected failure type: {failure_type}
Terminal RCA: {is_terminal}
Requires more data: {requires_more_data}
Root cause category: {root_cause_category}
Terminal dependency endpoint: {terminal_dependency}
Terminal evidence: {terminal_evidence_json}

**Kubernetes workload specs (requests/limits if available):**
{kubernetes_workloads_json}

**Dependency Kubernetes runtime/workload context (fresh from MCP):**
{dependency_kubernetes_context_json}

**Dependency findings synthesized from refreshed MCP evidence:**
{dependency_findings_json}

**OOM sizing recommendation (derived from metrics and workload specs):**
{oom_recommendation_json}

Return:
{
  "immediate_mitigation": ["..."],
  "long_term_fix": ["..."],
  "preventative_actions": ["..."],
  "step_by_step_instructions": ["..."],
  "commands": ["..."],
  "impacted_services": ["..."],
  "rollback_plan": ["..."],
  "risk_assessment": "..."
}
