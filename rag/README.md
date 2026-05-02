# RAG Service

Privacy-safe, updatable RAG (Retrieval-Augmented Generation) system with Google Drive integration, built with **FastAPI + Haystack + Celery** and industry-standard architecture.

## Features

- **Google Drive Integration**: Automatic ingestion from Google Drive folders
- **Haystack Pipelines**: Production-grade document processing and query pipelines
- **Celery Workers**: Background task processing for indexing and embeddings
- **Hybrid Search**: Combines vector similarity (pgvector) and BM25 lexical search
- **Reranking**: Cross-encoder reranking for improved relevance
- **Streaming Responses**: Real-time answer generation via SSE
- **Privacy Controls**: Confidentiality levels and content redaction
- **Redis Caching**: High-performance caching for embeddings and results
- **Evaluation**: Built-in metrics (Recall@k, Precision@k, MRR, Faithfulness, Hallucination Rate)
- **OpenRouter LLM**: Uses OpenRouter API with configurable models
- **Modular Architecture**: Industry-standard directory structure for maintainability
- **Production Ready**: Docker Compose with Celery workers, Redis, and Flower monitoring

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ Google Drive │────▶│   Celery     │────▶│  PostgreSQL  │
│   (Source)   │     │  Indexing    │     │  + pgvector  │
└──────────────┘     │   Workers    │     └──────────────┘
                     └──────────────┘              │
                            │                      │
                            ▼                      ▼
                     ┌──────────────┐     ┌──────────────┐
                     │   Haystack   │     │     Redis    │
                     │  Embeddings  │────▶│  (Cache +    │
                     │   Pipeline   │     │   Broker)    │
                     └──────────────┘     └──────────────┘
                            │
         ┌──────────────────┼──────────────────┐
         ▼                  ▼                   ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│   Haystack   │   │   Haystack   │   │    Celery    │
│    Vector    │   │     BM25     │   │  Embedding   │
│  Retriever   │   │  Retriever   │   │   Workers    │
└──────────────┘   └──────────────┘   └──────────────┘
         │                  │
         └──────────┬───────┘
                    ▼
            ┌──────────────┐
            │   Haystack   │
            │   Reranker   │
            └──────────────┘
                    │
                    ▼
            ┌──────────────┐
            │ LLM Generate │
            │ (OpenRouter) │
            └──────────────┘
```

## Project Structure

```
RAG/
├── app/ elery_app.py        # Celery configuration
│   ├── core/                # Core functionality
│   │   ├── __init__.py
│   │   ├── config.py        # Pydantic settings management
│   │   └── database.py      # SQLAlchemy + pgvector setup
│   ├── models/              # Data models
│   │   ├── __init__.py
│   │   ├── models.py        # SQLAlchemy ORM models
│   │   └── schemas.py       # Pydantic API schemas
│   ├── services/            # Business logic layer
│   │   ├── __init__.py
│   │   ├── cache.py         # Redis caching
│   │   ├── embeddings.py    # Sentence transformers
│   │   ├── gdrive.py        # Google Drive integration
│   │   ├── indexing.py      # Celery job dispatch
│   │   ├── llm.py           # OpenRouter LLM
│   │   ├── evaluation.py    # RAG metrics
│   │   ├── haystack_pipeline.py  # Haystack indexing pipeline
│   │   ├── haystack_query.py     # Haystack query pipeline
│   │   └── haystack_store.py     # Haystack document store
│   ├── workers/             # Celery workers
│   │   ├── __init__.py
│   │   ├── indexing_tasks.py    # Document indexing tasks
│   │   └── embedding_tasks.py   # Batch embedding tasks
│   └── api/                 # API route handlers
│       ├── __init__.py
│       ├── system.py        # System endpoints (health, stats)
│       ├── search.py        # Search endpoint
│       ├── ask.py           # Q&A endpoints
│       ├── indexing.py      # Indexing management
│       └── eval.py          # Evaluation endpoints
├── tests/                   # Test suite
│   ├── __init__.py
│   └── test_rag.py         # Comprehensive tests
├── scripts/                 # Utility scripts
│   ├── start.sh            # Quick start script
│   ├── start_celery_indexing.sh   # Celery indexing worker
│   ├── start_celery_embedding.sh  # Celery embedding worker
│   └── start_flower.sh     # Flower monitoring
├── eval/                    # Evaluation datasets
│   └── eval_dataset.json   # Example evaluation data
├── .env                     # Environment configuration
├── requirements.txt         # Python dependencies
├── Dockerfile              # Container definition
├── docker-compose.yml      # Multi-container setup (FastAPI + Celery + Redis + Flower)ation
├── requirements.txt         # Python dependencies
├── Dockerfile              # Container definition
├── docker-compose.yml      # Multi-container setup
└── README.md               # This file
```

## Prerequisites

1. **PostgreSQL with pgvector**
   - Neon database with pgvector extension enabled

2. **Redis**
   - Upstash Redis instance

3. **Google Drive API**
   - Service account JSON file
   - Drive folder ID with read permissions

4. **OpenRouter API Key**
   - Account at openrouter.ai

## Installation

1. **Clone and navigate to RAG directory**
```bash
cd RAG
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

3. **Add Google Service Account JSON**
```bash
# Place your google-service-account.json in the RAG directory
cp /path/to/your/credentials.json ./google-service-account.json
```

4. **Verify .env configuration**
- All required environment variables are already in `.env`
- Update `GOOGLE_DRIVE_FOLDER_ID` if needed

## Usage

### Start the Full Stack (Recommended)

```bash
docker-compose up -d
```

This starts:
- FastAPI application (port 8000)
- Redis (port 6379)
- Celery indexing worker (2 concurrent tasks)
- Celery embedding worker (4 concurrent tasks, thread pool)
- Flower monitoring UI (port 5555)

### Start Individual Components (Development)

**1. Start Redis** (required for Celery):
```bash
docker run -d -p 6379:6379 redis:7-alpine
```

**2. Start FastAPI application**:
```bash
python -m app.main
```

**3. Start Celery indexing worker**:
```bash
bash scripts/start_celery_indexing.sh
# Or manually:
celery -A app.celery_app worker --loglevel=info --queues=indexing --concurrency=2
```

**4. Start Celery embedding worker**:
```bash
bash scripts/start_celery_embedding.sh
# Or manually:
celery -A app.celery_app worker --loglevel=info --queues=embedding --concurrency=4 --pool=threads
```

**5. Start Flower monitoring** (optional):
```bash
bash scripts/start_flower.sh
# Access at: http://localhost:5555/flower
```

The service will start on `http://localhost:8000`

### API Endpoints

#### Health Check
```bash
curl http://localhost:8000/health
```

#### Search Documents
```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "kubernetes deployment",
    "top_k": 10,
    "use_hybrid": true,
    "use_reranker": true
  }'
```

#### Ask Question
```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{
    "query": "How do I configure VMware vCenter?",
    "top_k": 10
  }'
```

#### Streaming Answer
```bash
curl -X POST http://localhost:8000/ask/stream \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Explain Kubernetes RBAC",
    "stream": true
  }'
```

#### Trigger Full Reindex
```bash
curl -X POST http://localhost:8000/reindex \
  -H "Content-Type: application/json" \
  -d '{
    "job_type": "full"
  }'
```

#### Check Indexing Job Status
```bash
curl http://localhost:8000/reindex/status/{job_id}
```

#### Get Statistics
```bash
curl http://localhost:8000/stats
```

#### Clear Cache
```bash
curl -X POST http://localhost:8000/cache/clear
```

## Configuration

Key configuration options in `.env`:

### Embedding Model
```env
RAG_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
RAG_EMBEDDING_DIM=768
RAG_BATCH_SIZE=32
```

### LLM Model
```env
RAG_LLM_MODEL=x-ai/grok-beta
RAG_LLM_TEMPERATURE=0.7
RAG_LLM_MAX_TOKENS=1024
```

### Retrieval
```env
RAG_TOP_K=20
RAG_RERANK_TOP_K=5
RAG_USE_HYBRID_SEARCH=true
RAG_SIMILARITY_THRESHOLD=0.7
```

### Chunking
```env
RAG_CHUNK_SIZE=512
RAG_CHUNK_OVERLAP=50
```

## Testing

Run comprehensive tests:
```bash
pytest tests/ -v --cov=app
```

## Performance

Expected latencies (P50):
- Vector search: < 200ms
- Hybrid search: < 500ms
- Reranking: < 300ms
- LLM generation: 2-5s
- End-to-end answer: < 8s

## Monitoring

### Metrics
- Total documents indexed
- Query latency (retrieval, reranking, generation)
- Cache hit rates
- Embedding model load

### Logs
Structured logs include:
- Query patterns
- Retrieval performance
- Error traces
- Confidentiality filtering

## Privacy & Security

- **Confidentiality Levels**: Automatic detection (low/medium/high)
- **Pattern Redaction**: Configurable sensitive patterns
- **Citation Tracking**: Full source attribution
- **Audit Logs**: Query and access tracking

## Troubleshooting

### Database Connection Issues
```bash
# Test PostgreSQL connection
psql "postgresql://neondb_owner:npg_k7cAvr5QyBES@ep-solitary-sky-a161os9o-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
```

### Redis Connection Issues
```bash
# Test Redis connection
redis-cli -u "rediss://default:ATRFAAIncDJiYTU2NWFmYWZiNDU0N2IyOTQ4YjIwYjlkOGY2ODk2YnAyMTMzODE@deep-fowl-13381.upstash.io:6379"
```

### Embedding Model Not Loading
- Check available disk space
- Verify internet connectivity
- Try CPU mode if GPU unavailable

### Google Drive Authentication Failed
- Verify service account JSON is correct
- Check folder ID permissions
- Enable Google Drive API in GCP console

## Development

### Code Formatting
```bash
black . --line-length 100
ruff check . --fix
```

### Type Checking
```bash
mypy . --ignore-missing-imports
```

## License

MIT License

## Support

For issues and questions:
- Check logs in `./logs`
- Review error traces
- Verify environment variables
