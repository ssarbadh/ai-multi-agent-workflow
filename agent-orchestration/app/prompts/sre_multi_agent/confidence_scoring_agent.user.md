RCA hypothesis: {hypothesis}
Evidence: {evidence_json}
Anomalies: {anomalies_json}
Critique feedback: {critique_feedback}
Missing observability signals: {observability_missing_json}
Terminal RCA: {is_terminal}
Root cause category: {root_cause_category}
Log evidence digest: {log_evidence_digest_json}
Metrics evidence digest: {metrics_evidence_digest_json}

Return:
{
  "score": 0.0,
  "reasoning": "...",
  "factor_breakdown": {
    "evidence_quality": 0.0,
    "metric_correlation": 0.0,
    "log_matches": 0.0,
    "knowledge_base_similarity": 0.0,
    "critique_validation": 0.0
  }
}
