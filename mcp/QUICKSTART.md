# MCP Service - Quick Start

## Prerequisites

- Python 3.11+
- Redis (Upstash configured in .env)
- Other AegisOps services running (optional, for full functionality)

## Installation

```bash
cd mcp
pip install -r requirements.txt
```

## Run the Service

```bash
python -m app.main
```

Or with uvicorn:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8005 --reload
```

## Verify Installation

```bash
# Health check
curl http://localhost:8005/api/v1/health

# List servers
curl http://localhost:8005/api/v1/servers

# List all tools
curl http://localhost:8005/api/v1/tools
```

## Call a Tool

```bash
# Search via RAG
curl -X POST http://localhost:8005/api/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "name": "rag_search",
    "arguments": {
      "query": "kubernetes deployment",
      "top_k": 5
    }
  }'

# List K8s pods
curl -X POST http://localhost:8005/api/v1/tools/k8s_list_pods/call \
  -H "Content-Type: application/json" \
  -d '{"namespace": "default"}'
```

## Create a Session

```bash
curl -X POST http://localhost:8005/api/v1/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "server_id": "rag-server",
    "client_id": "my-client"
  }'
```

## Connect via SSE

```bash
curl -N http://localhost:8005/api/v1/sse/rag-server
```

## API Documentation

- Swagger UI: http://localhost:8005/api/docs
- ReDoc: http://localhost:8005/api/redoc

## Docker

```bash
docker-compose up -d
```

## Run Tests

```bash
pytest tests/test_master.py -v
```
