# AegisOps Observability Service

Centralized observability service for the AegisOps platform providing metrics collection, evaluation, alerting, dashboards, logging, and distributed tracing.

## Features

- **Agent Evaluation Metrics**: Resolution rate, time-to-resolution, rollback rate, user satisfaction
- **RAG Evaluation Metrics**: Recall@k, faithfulness, hallucination rate, retrieval latency
- **Alerting**: SLO-based alerts with Prometheus Alertmanager integration
- **Dashboards**: Executive, RAG, Serving, Graph, Pipelines, Infrastructure
- **Structured Logging**: HLD-compliant log envelope with correlation IDs
- **Distributed Tracing**: OpenTelemetry integration

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the service
uvicorn app.main:app --host 0.0.0.0 --port 8003 --reload
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check |
| `GET /metrics/agent/evaluation` | Agent evaluation metrics |
| `GET /metrics/rag/evaluation` | RAG evaluation metrics |
| `GET /metrics/health` | System health status |
| `GET /alerts/` | Active alerts |
| `GET /alerts/rules` | Alert rules |
| `GET /dashboards/` | List dashboards |
| `GET /dashboards/{id}` | Dashboard with data |
| `POST /logs/ingest` | Ingest logs |
| `GET /logs/search` | Search logs |
| `GET /traces/` | List traces |

## Docker

```bash
docker-compose up -d
```

Services:
- Observability API: http://localhost:8003
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3001 (admin/admin)
- Alertmanager: http://localhost:9093

## Configuration

See `.env` for configuration options including:
- Database and Redis connections
- Prometheus/Grafana URLs
- Service endpoints to monitor
- Alerting webhooks

## Testing

```bash
pytest tests/test_master.py -v
```
