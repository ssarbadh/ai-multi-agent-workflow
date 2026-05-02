# Quick Start Guide

Get the Agent Orchestration service running in 5 minutes.

## Prerequisites

- Python 3.11+
- PostgreSQL (or use Docker Compose)
- Redis (or use Docker Compose)
- Context Management service running on port 8000
- RAG service running on port 8001

## Option 1: Docker Compose (Recommended)

```bash
# Navigate to directory
cd "Agent Orchestration"

# Start all services
docker-compose up -d

# Check logs
docker-compose logs -f agent-orchestration

# Service will be available at:
# - API: http://localhost:8002
# - Metrics: http://localhost:9002
# - Docs: http://localhost:8002/api/docs
```

## Option 2: Local Development

### 1. Install Dependencies

```bash
# Create virtual environment
python -m venv venv

# Activate (Linux/Mac)
source venv/bin/activate

# Activate (Windows)
venv\Scripts\activate

# Install packages
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
# Copy example env file
cp .env.example .env

# Edit .env with your credentials
# At minimum, set:
# - DATABASE_URL
# - REDIS_URL
# - LLM_API_KEY
# - SNOW_INSTANCE_URL, SNOW_USERNAME, SNOW_PASSWORD
# - SMTP credentials
```

### 3. Initialize Database

```bash
python scripts/init_database.py
```

### 4. Start the Service

```bash
# Development mode (with auto-reload)
bash scripts/start_dev.sh

# Or directly
python -m app.main
```

## Verify Installation

### 1. Health Check

```bash
curl http://localhost:8002/api/v1/health
```

Expected response:
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "environment": "development",
  "components": {
    "database": true,
    "redis": true,
    "context_mgmt": true,
    "rag": true
  }
}
```

### 2. API Documentation

Open in browser:
- Swagger UI: http://localhost:8002/api/docs
- ReDoc: http://localhost:8002/api/redoc

### 3. Prometheus Metrics

```bash
curl http://localhost:9002
```

## First Orchestration Run

### 1. Start a Service Request

```bash
curl -X POST http://localhost:8002/api/v1/orchestrate \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "test_session_1",
    "user_id": "test_user_1",
    "message": "Create a new VM with 4 CPUs and 8GB RAM",
    "priority": "medium"
  }'
```

Response:
```json
{
  "id": "run_abc123",
  "session_id": "test_session_1",
  "status": "pending",
  ...
}
```

### 2. Stream Progress

```bash
# In a new terminal
curl -N http://localhost:8002/api/v1/runs/run_abc123/stream
```

You'll see SSE events:
```
event: connected
data: {"run_id":"run_abc123"}

event: status
data: {"status":"running","message":"Starting orchestration..."}

event: node
data: {"node":"router","message":"Analyzing request type..."}

event: token
data: {"content":"Creating VM..."}

event: complete
data: {"status":"completed","duration_seconds":5.2}
```

### 3. Check Run Status

```bash
curl http://localhost:8002/api/v1/runs/run_abc123
```

## Run Tests

```bash
# Run all tests
pytest tests/ -v

# Run master E2E test
pytest tests/test_master.py -v

# With coverage
pytest tests/ --cov=app --cov-report=html
```

## Common Issues

### Database Connection Failed

```bash
# Check PostgreSQL is running
psql -h localhost -p 5432 -U postgres -d agent_orchestration

# Or use Docker
docker-compose up -d postgres
```

### Redis Connection Failed

```bash
# Check Redis is running
redis-cli ping

# Or use Docker
docker-compose up -d redis
```

### Context Management/RAG Service Not Available

```bash
# Start Context Management service
cd "../Context Management"
python -m app.main

# Start RAG service
cd "../RAG"
python -m app.main
```

### Import Errors

```bash
# Reinstall dependencies
pip install -r requirements.txt --force-reinstall
```

## Next Steps

1. **Configure Infrastructure Access**:
   - Add VMware vCenter credentials
   - Configure AWS/Azure/GCP credentials
   - Set up Kubernetes kubeconfig
   - Add GitHub token

2. **Set Up ServiceNow**:
   - Configure SNOW instance URL
   - Add API credentials
   - Test ticket creation

3. **Configure Notifications**:
   - Set up SMTP for email
   - Configure stakeholder lists

4. **Review Agent Logic**:
   - Customize routing rules in `app/agents/router_agent.py`
   - Adjust decision matrix in `app/agents/decision_agent.py`
   - Configure approval policies

5. **Set Up Monitoring**:
   - Configure Prometheus scraping
   - Set up Grafana dashboards
   - Configure alerting rules

6. **Production Deployment**:
   - Review security settings
   - Configure TLS/SSL
   - Set up load balancing
   - Configure backup and recovery

## Documentation

- Full README: [README.md](README.md)
- API Documentation: http://localhost:8002/api/docs
- Architecture: See HLD document

## Support

For issues:
1. Check logs: `docker-compose logs -f` or `tail -f logs/*.log`
2. Verify environment variables in `.env`
3. Check service dependencies are running
4. Review error traces in Sentry (if configured)
