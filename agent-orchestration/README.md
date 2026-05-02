# Agent Orchestration Service

LangGraph-based multi-agent orchestration backend for Infrastructure & Platform Service/Change Requests and Incident/Problem Resolution.

## Features

- **Multi-Agent Topology**: Specialized agents for routing, SR/CR, incidents, dependencies, provisioning, remediation, and more
- **LangGraph Orchestration**: State-driven graph execution with checkpoints and replay
- **ServiceNow Integration**: Automatic ticket creation, updates, and stakeholder notifications
- **VM Execution**: Sandbox command execution with streaming output
- **Human-in-the-Loop**: Approval gates and password prompts with timeout handling
- **RAG Integration**: Decision matrix and knowledge base for diagnostics
- **Real-time Streaming**: SSE for tokens, analysis, references, and confidentiality scores
- **Infrastructure SDKs**: VMware, AWS, Azure, GCP, Kubernetes integrations
- **DevOps Integration**: GitHub for PR, reviews, and GitOps workflows
- **Observability**: OpenTelemetry tracing, Prometheus metrics, structured logging
- **Security**: Secret masking, RBAC, audit trails

## Architecture

```
┌─────────────────┐
│  User Request   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Router Agent   │ ──▶ Classify: SR/CR vs Incident
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
┌────────┐ ┌──────────┐
│ SR/CR  │ │ Incident │
│  Path  │ │   Path   │
└────┬───┘ └────┬─────┘
     │          │
     ▼          ▼
┌─────────────────────┐
│  Dependency Agent   │
│  Telemetry Agent    │
│  Decision Agent     │
│  Provisioner Agent  │
│  Remediator Agent   │
│  SNOW Agent         │
│  Notification Agent │
│  VM Exec Agent      │
│  DevOps Agent       │
└─────────────────────┘
```

## Project Structure

```
Agent Orchestration/
├── app/
│   ├── agents/              # LangGraph agents
│   │   ├── router_agent.py
│   │   ├── sr_cr_agent.py
│   │   ├── incident_agent.py
│   │   └── ...
│   ├── api/                 # FastAPI endpoints
│   │   ├── health.py
│   │   ├── orchestration.py
│   │   ├── streaming.py
│   │   ├── approvals.py
│   │   ├── vm_console.py
│   │   ├── snow.py
│   │   └── notifications.py
│   ├── core/                # Core configuration
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── redis_client.py
│   │   └── observability.py
│   ├── models/              # Data models
│   │   ├── models.py        # SQLAlchemy ORM
│   │   └── schemas.py       # Pydantic schemas
│   ├── services/            # Business logic
│   │   ├── orchestrator.py
│   │   ├── approval_service.py
│   │   ├── vm_executor.py
│   │   ├── snow_client.py
│   │   └── notification_service.py
│   └── main.py              # Application entry point
├── tests/
│   ├── conftest.py
│   └── test_master.py       # Comprehensive E2E tests
├── scripts/
│   ├── init_database.py
│   ├── start.sh
│   ├── start_dev.sh
│   └── start_dev.bat
├── .env                     # Environment configuration
├── requirements.txt
├── docker-compose.yml
├── Dockerfile
└── README.md
```

## Prerequisites

1. **Python 3.11+**
2. **PostgreSQL 14+** (for persistent storage)
3. **Redis 6/7** (for caching and pub/sub)
4. **Context Management Service** (running on port 8000)
5. **RAG Service** (running on port 8001)
6. **ServiceNow Instance** (with API credentials)
7. **Infrastructure Access**:
   - VMware vCenter credentials
   - AWS/Azure/GCP credentials
   - Kubernetes kubeconfig
   - GitHub token
8. **Email/SMTP** (for notifications)

## Installation

### Local Development

```bash
# Navigate to directory
cd "Agent Orchestration"

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your credentials

# Initialize database
python scripts/init_database.py

# Start the service
python -m app.main
```

### Docker Compose

```bash
docker-compose up -d
```

This starts:
- Agent Orchestration API (port 8002)
- PostgreSQL database (port 5434)
- Redis (port 6381)
- Prometheus metrics (port 9002)

## Configuration

Key environment variables in `.env`:

### Required Services
```env
CONTEXT_MGMT_URL=http://localhost:8000
RAG_SERVICE_URL=http://localhost:8001
```

### LLM Configuration
```env
LLM_PROVIDER=openrouter
LLM_MODEL=x-ai/grok-beta
LLM_API_KEY=your_api_key
```

### ServiceNow
```env
SNOW_INSTANCE_URL=https://your-instance.service-now.com
SNOW_USERNAME=your_username
SNOW_PASSWORD=your_password
```

### Infrastructure
```env
# VMware
VMWARE_HOST=vcenter.yourcompany.com
VMWARE_USERNAME=administrator@vsphere.local
VMWARE_PASSWORD=your_password

# AWS
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret

# Azure
AZURE_SUBSCRIPTION_ID=your_subscription
AZURE_TENANT_ID=your_tenant
AZURE_CLIENT_ID=your_client
AZURE_CLIENT_SECRET=your_secret

# GCP
GCP_PROJECT_ID=your_project
GCP_CREDENTIALS_PATH=./gcp-credentials.json

# Kubernetes
K8S_CONFIG_PATH=~/.kube/config
K8S_CONTEXT=default

# GitHub
GITHUB_TOKEN=your_token
GITHUB_ORG=your_org
GITHUB_REPO=your_repo
```

## Usage

### Start Orchestration

```bash
curl -X POST http://localhost:8002/api/v1/orchestrate \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "sess_123",
    "user_id": "user_456",
    "message": "Create a new VM with 4 CPUs and 8GB RAM in production",
    "priority": "medium"
  }'
```

Response:
```json
{
  "id": "run_abc123",
  "session_id": "sess_123",
  "user_id": "user_456",
  "status": "pending",
  "request_type": "service_request",
  ...
}
```

### Stream Progress (SSE)

```bash
curl -N http://localhost:8002/api/v1/runs/run_abc123/stream
```

Events:
- `token`: LLM token output
- `node`: Agent node transition
- `analysis`: Reasoning summary
- `reference`: External citations
- `confidentiality`: Score update
- `tool`: Tool call
- `approval`: Approval request
- `vm_output`: VM command output
- `status`: Status change
- `complete`: Run completed
- `error`: Error occurred

### Get Run Status

```bash
curl http://localhost:8002/api/v1/runs/run_abc123
```

### List Runs

```bash
curl "http://localhost:8002/api/v1/runs?session_id=sess_123&limit=10"
```

### Respond to Approval

```bash
curl -X POST http://localhost:8002/api/v1/approvals/appr_789/respond \
  -H "Content-Type: application/json" \
  -d '{
    "approval_id": "appr_789",
    "approved": true,
    "comment": "Approved for production deployment"
  }'
```

### Cancel Run

```bash
curl -X POST http://localhost:8002/api/v1/runs/run_abc123/cancel
```

### Get Statistics

```bash
curl http://localhost:8002/api/v1/stats
```

## API Documentation

Once running, visit:
- **Swagger UI**: http://localhost:8002/api/docs
- **ReDoc**: http://localhost:8002/api/redoc

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=app --cov-report=html

# Run master E2E test
pytest tests/test_master.py -v

# Run specific test class
pytest tests/test_master.py::TestOrchestration -v
```

## Monitoring

### Prometheus Metrics

Available at `http://localhost:9002`:

- `agent_runs_total` - Total agent runs by type and status
- `agent_run_duration_seconds` - Run duration histogram
- `agent_node_duration_seconds` - Node execution duration
- `tool_calls_total` - Tool calls by name and outcome
- `tool_call_duration_seconds` - Tool call duration
- `approval_wait_time_seconds` - Approval wait time
- `vm_exec_total` - VM executions by outcome
- `snow_operations_total` - ServiceNow operations
- `sse_connections_active` - Active SSE connections
- `tokens_streamed_total` - Total tokens streamed

### Structured Logging

Logs include:
- `run_id`, `session_id`, `user_id`
- Node transitions
- Tool calls with parameters hash
- Approval requests and responses
- VM command execution (with secret masking)
- ServiceNow operations
- Error traces

### OpenTelemetry Tracing

Distributed traces with spans for:
- HTTP requests
- Database queries
- Redis operations
- Agent nodes
- Tool calls
- External API calls

## Agent Workflows

### Service/Change Request Path

1. **Router Agent**: Classify as SR/CR
2. **SR/CR Agent**: Normalize requirements to JSON
3. **Dependency Agent**: Discover infra dependencies
4. **SNOW Agent**: Create ServiceNow ticket
5. **Provisioner Agent**: Execute workflow with approval gates
6. **Notification Agent**: Email stakeholders
7. **SNOW Agent**: Update ticket and close

### Incident Path

1. **Router Agent**: Classify as Incident
2. **Incident Agent**: Triage (true/false positive, severity)
3. **Telemetry Agent**: Collect logs/metrics
4. **Decision Agent**: Apply RAG decision matrix
5. **Remediator Agent**: Propose fix
6. **Approval Agent**: Request approval
7. **VM Exec Agent**: Execute remediation
8. **SNOW Agent**: Update incident
9. **Notification Agent**: Notify stakeholders

## Performance Targets

Based on HLD requirements:

- **First Token**: <1.5s (P50)
- **Stream Cadence**: ≤300ms
- **Dependency Discovery**: <30s (P50)
- **Concurrent Runs**: 100+
- **Checkpoint Resume**: <5s
- **SSE Reconnection**: Automatic with Last-Event-ID

## Security

- **Secret Masking**: Automatic redaction of passwords, tokens, keys
- **RBAC**: Role-based access control (viewer/operator/admin)
- **Audit Logs**: Immutable trail of all actions
- **Approval Gates**: Required for sensitive operations
- **TLS**: Encrypted communication
- **Vault Integration**: Secure secret storage

## Troubleshooting

### Database Connection Issues
```bash
# Test PostgreSQL connection
psql "postgresql://user:password@localhost:5432/agent_orchestration"
```

### Redis Connection Issues
```bash
# Test Redis connection
redis-cli -h localhost -p 6379 ping
```

### Service Dependencies
```bash
# Check Context Management service
curl http://localhost:8000/api/v1/health

# Check RAG service
curl http://localhost:8001/health
```

### View Logs
```bash
# Docker logs
docker-compose logs -f agent-orchestration

# Local logs
tail -f logs/agent-orchestration.log
```

## Development

### Code Formatting
```bash
black . --line-length 100
ruff check . --fix
```

### Type Checking
```bash
mypy app/ --ignore-missing-imports
```

### Pre-commit Hooks
```bash
pre-commit install
pre-commit run --all-files
```

## License

Proprietary

## Support

For issues and questions:
- Check logs in `./logs`
- Review error traces in Sentry
- Check Prometheus metrics
- Verify environment variables
- Ensure all dependencies are running

