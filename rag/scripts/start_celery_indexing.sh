#!/bin/bash
# Start Celery worker for RAG indexing tasks

echo "🚀 Starting Celery worker for indexing..."

# Activate virtual environment if exists
if [ -d "venv" ]; then
    source venv/bin/activate || . venv/Scripts/activate
fi

# Start Celery worker for indexing queue
celery -A app.celery_app worker \
    --loglevel=info \
    --queues=indexing \
    --concurrency=2 \
    --max-tasks-per-child=100 \
    --task-events \
    --without-gossip \
    --without-mingle \
    --without-heartbeat
