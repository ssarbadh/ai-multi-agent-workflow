#!/bin/bash
# Start Celery worker for RAG embedding tasks

echo "🚀 Starting Celery worker for embeddings..."

# Activate virtual environment if exists
if [ -d "venv" ]; then
    source venv/bin/activate || . venv/Scripts/activate
fi

# Start Celery worker for embedding queue (optimized for GPU/CPU)
celery -A app.celery_app worker \
    --loglevel=info \
    --queues=embedding \
    --concurrency=4 \
    --max-tasks-per-child=50 \
    --task-events \
    --without-gossip \
    --without-mingle \
    --without-heartbeat \
    --pool=threads
