# Observability Service - Quick Start

## Prerequisites

- Python 3.11+
- Docker & Docker Compose (for full stack)
- PostgreSQL 15+ (optional for persistence)
- Redis 7+ (optional for caching)

## Local Development

```bash
cd Observability

# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Run service
uvicorn app.main:app --host 0.0.0.0 --port 8003 --reload
```

## Docker Stack

```bash
# Start full observability stack
docker-compose up -d

# View logs
docker-compose logs -f observability
```

## Verify Installation

```bash
# Health check
curl http://localhost:8003/health

# Agent metrics
curl http://localhost:8003/metrics/agent/evaluation

# RAG metrics
curl http://localhost:8003/metrics/rag/evaluation

# Dashboards
curl http://localhost:8003/dashboards/

# Alerts
curl http://localhost:8003/alerts/rules
```

## Access UIs

- API Docs: http://localhost:8003/docs
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3001 (admin/admin)
- Alertmanager: http://localhost:9093

## Run Tests

```bash
pytest tests/test_master.py -v
```
