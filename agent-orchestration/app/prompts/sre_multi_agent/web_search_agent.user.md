Target service: {target_service}
Incident title: {incident_title}
Incident description: {incident_description}
Current hypothesis: {hypothesis}
Anomalies: {anomalies_json}
Log evidence digest: {log_evidence_digest_json}
Metrics evidence digest: {metrics_evidence_digest_json}
Failure type: {failure_type}
Root cause category: {root_cause_category}
Vendors: {vendors_json}
Clouds: {clouds_json}
Region: {region}

Generate focused web-research inputs for the probable issue.

Return JSON only in this format:
{
  "probable_issue": "...",
  "github_issue_terms": ["..."],
  "vendor_doc_topics": ["..."],
  "cloud_status_keywords": ["..."]
}
