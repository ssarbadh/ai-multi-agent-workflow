#!/bin/bash
# Quick start script for Agent Orchestration service

set -e

echo "Starting Agent Orchestration Service..."

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Initialize database
echo "Initializing database..."
python scripts/init_database.py

# Start the service
echo "Starting FastAPI server..."
python -m app.main
