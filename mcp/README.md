# MCP Service

Model Context Protocol (MCP) service for AegisOps - exposes tools, resources, and prompts for AI agents.

## Features

- **MCP Servers**: Built-in servers for Infrastructure, RAG, and Context Management
- **Tool Execution**: Execute tools across all registered servers via gateway
- **Resource Access**: Read resources from any server
- **Prompt Templates**: Get prompt templates with arguments
- **Session Management**: Create and manage client sessions
- **OpenAPI Bridge**: Convert OpenAPI specs to MCP tools
- **SSE Transport**: Real-time streaming via Server-Sent Events
- **RBAC**: Role-based access control for tools and resources
- **Audit Logging**: Full audit trail for all tool calls

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      MCP Gateway                             │
│  (Routing, Auth, Rate Limiting, Audit)                      │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│ Infra Server  │   │  RAG Server   │   │Context Server │
│               │   │               │   │               │
│ - VMware      │   │ - Search      │   │ - Sessions    │
│ - AWS         │   │ - Ask         │   │ - Memory      │
│ - K8s         │   │ - Reindex     │   │ - Prompts     │
└───────────────┘   └───────────────┘   └───────────────┘
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│    Agent      │   │     RAG       │   │   Context     │
│ Orchestration │   │   Service     │   │  Management   │
│   (8002)      │   │   (8001)      │   │   (8000)      │
└───────────────┘   └───────────────┘   └───────────────┘
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the service
python -m app.main

# Or with uvicorn
uvicorn app.main:app --host 0.0.0.0 --port 8005 --reload
```

Service runs on http://localhost:8005

## API Endpoints

### Health
- `GET /api/v1/health` - Health check
- `GET /api/v1/ready` - Readiness check
- `GET /api/v1/metrics` - Basic metrics

### Servers
- `GET /api/v1/servers` - List all servers
- `GET /api/v1/servers/{id}` - Get server details
- `GET /api/v1/servers/{id}/tools` - List server tools

### Tools
- `GET /api/v1/tools` - List all tools
- `GET /api/v1/tools/{name}` - Get tool details
- `POST /api/v1/tools/call` - Call a tool
- `POST /api/v1/tools/{name}/call` - Call tool by name

### Resources
- `GET /api/v1/resources` - List all resources
- `GET /api/v1/resources/read?uri=...` - Read a resource

### Prompts
- `GET /api/v1/prompts` - List all prompts
- `POST /api/v1/prompts/get` - Get prompt with arguments

### Sessions
- `POST /api/v1/sessions` - Create session
- `GET /api/v1/sessions` - List sessions
- `GET /api/v1/sessions/{id}` - Get session
- `POST /api/v1/sessions/{id}/close` - Close session

### SSE Transport
- `GET /api/v1/sse/{server_id}` - Connect via SSE

### OpenAPI Bridge
- `GET /api/v1/openapi/specs` - List loaded specs
- `POST /api/v1/openapi/convert` - Convert spec to tools

## Built-in Tools

### Infrastructure Server
- `vmware_list_vms` - List VMware VMs
- `vmware_vm_power` - Control VM power state
- `aws_list_ec2` - List EC2 instances
- `aws_ec2_action` - Control EC2 instances
- `k8s_list_pods` - List Kubernetes pods
- `k8s_scale_deployment` - Scale deployments

### RAG Server
- `rag_search` - Search documents
- `rag_ask` - Ask questions with citations
- `rag_reindex` - Trigger reindexing
- `rag_stats` - Get RAG statistics

### Context Server
- `context_create_session` - Create session
- `context_get_session` - Get session details
- `context_get_memory` - Get session memory
- `context_add_memory` - Add memory entry
- `context_get_prompt` - Get prompt template
- `context_submit_feedback` - Submit feedback

### Prometheus Server (optional external adapter)
- `prometheus_execute_query` - Execute instant PromQL query
- `prometheus_execute_range_query` - Execute range PromQL query
- `prometheus_list_metrics` - List metric names
- `prometheus_get_metric_metadata` - Get metric metadata
- `prometheus_get_targets` - List scrape targets
- `prometheus_health_check` - Validate upstream MCP connectivity

### New Relic Server (optional external adapter)
- `newrelic_query_logs` - Query logs for services/incidents
- `newrelic_nrql_query` - Execute NRQL queries
- `newrelic_list_alert_violations` - List active violations

### Alertmanager Server (optional external adapter)
- `alertmanager_get_alerts` - List alerts with pagination filters
- `alertmanager_get_alert_groups` - List grouped alerts

### ServiceNow Server (optional direct adapter)
- `servicenow_search_incidents` - Search incidents using encoded query

## External Prometheus MCP Integration

This service can proxy tools from a public Prometheus MCP server (for example
`ghcr.io/pab1it0/prometheus-mcp-server:latest`) into the AegisOps MCP gateway.

Set these environment variables on the `mcp` service:

- `PROMETHEUS_MCP_ENABLED=true`
- `PROMETHEUS_MCP_URL=http://prometheus-mcp:8080`
- `PROMETHEUS_MCP_TIMEOUT_SECONDS=30`
- `PROMETHEUS_MCP_BEARER_TOKEN=<optional token>`

When enabled, the registry adds `prometheus-server` and exposes the prefixed
Prometheus tools above via normal `/api/v1/tools` discovery and `/api/v1/tools/call`.

## External New Relic / Alertmanager / ServiceNow Integration

Set these environment variables on the `mcp` service as needed:

- New Relic:
  - `NEWRELIC_MCP_ENABLED=true`
  - `NEWRELIC_MCP_URL=https://mcp.newrelic.com`
  - `NEWRELIC_MCP_TIMEOUT_SECONDS=30`
  - `NEWRELIC_MCP_BEARER_TOKEN=<token>`
- Alertmanager:
  - `ALERTMANAGER_MCP_ENABLED=true`
  - `ALERTMANAGER_MCP_URL=http://alertmanager-mcp:8008`
  - `ALERTMANAGER_MCP_TIMEOUT_SECONDS=30`
  - `ALERTMANAGER_MCP_BEARER_TOKEN=<optional token>`
  - `ALERTMANAGER_MCP_USERNAME=<optional user>`
  - `ALERTMANAGER_MCP_PASSWORD=<optional password>`
- ServiceNow:
  - `SERVICENOW_MCP_ENABLED=true`
  - `SNOW_INSTANCE_URL=https://<instance>.service-now.com`
  - `SNOW_USERNAME=<username>`
  - `SNOW_PASSWORD=<password>`

Server IDs used by tool discovery:
- `prometheus-server`
- `newrelic-mcp`
- `alertmanager-mcp`
- `servicenow-mcp`

## Authentication

The service supports:
- **API Keys**: Via `X-API-Key` header
- **JWT Tokens**: Via `Authorization: Bearer <token>` header

In development mode with no keys configured, anonymous access is allowed with viewer permissions.

## Configuration

See `.env` for all configuration options:
- Service settings (port, debug, etc.)
- Database and Redis connections
- Service endpoints for proxying
- Security settings (API keys, JWT)
- Rate limiting
- Audit logging

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=app --cov-report=html
```

## Docker

```bash
# Build and run
docker-compose up -d

# View logs
docker-compose logs -f mcp
```

## Port

- MCP Service: 8005
- MCP Gateway: 8006 (optional)
