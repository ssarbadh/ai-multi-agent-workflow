Incident ID: {incident_id}
Service: {service_name}
Root cause: {root_cause}
Remediation summary: {remediation_summary}

Return:
{
  "graph_update_status": "updated|skipped|failed",
  "deduplicated_nodes": ["..."],
  "relationships_created": ["Incident->Service", "Service->Root Cause", "Root Cause->Remediation"]
}
