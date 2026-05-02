#!/bin/bash
# Quick start script for RAG service

echo "🚀 Starting RAG Service..."

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python -m venv venv
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source venv/bin/activate || . venv/Scripts/activate

# Install dependencies
echo "📥 Installing dependencies..."
pip install -r requirements.txt

# Check for Google service account file
if [ ! -f "google-service-account.json" ]; then
    echo "⚠️  Warning: google-service-account.json not found!"
    echo "   Please add your Google service account credentials."
fi

# Check database connection
echo "🗄️  Checking database connection..."
python -c "
import asyncio
from app.core.database import check_db_connection

async def check():
    result = await check_db_connection()
    if result:
        print('✅ Database connection successful')
    else:
        print('❌ Database connection failed')
        exit(1)

asyncio.run(check())
"

# Start the service
echo "🎯 Starting FastAPI server..."
python -m app.main
