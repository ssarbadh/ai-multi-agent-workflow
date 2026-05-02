#!/bin/bash
# Start Celery Flower for monitoring

echo "🌸 Starting Celery Flower monitoring..."

# Activate virtual environment if exists
if [ -d "venv" ]; then
    source venv/bin/activate || . venv/Scripts/activate
fi

# Start Flower
celery -A app.celery_app flower \
    --port=5555 \
    --url_prefix=flower \
    --basic_auth=admin:${FLOWER_PASSWORD:-admin123}
