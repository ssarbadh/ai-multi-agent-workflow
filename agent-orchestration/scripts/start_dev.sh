#!/bin/bash
# Development startup script (Linux/Mac)

set -e

echo "Starting Agent Orchestration Service (Development Mode)..."

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Start with auto-reload
uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload --log-level info
