#!/usr/bin/env python3
"""Limited Google Drive indexing for testing - process only first 5 files."""
import asyncio
import logging
import sys
from datetime import datetime

# Set up logging to see progress
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

from app.core.database import AsyncSessionLocal
from app.services.gdrive import gdrive_service
from app.services.embeddings import embedding_service
from app.services.cache import cache_manager
from app.models.models import Document
from app.core.config import settings


async def index_limited_google_drive_documents(max_files=5):
    """Index only the first few documents from Google Drive for testing."""
    logger.info(f"Starting limited Google Drive indexing (max {max_files} files)...")
    
    try:
        # Connect to cache (Redis)
        try:
            await cache_manager.connect()
            logger.info("✓ Connected to Redis cache")
        except Exception as e:
            logger.warning(f"Cache connection failed, continuing without cache: {e}")
        
        # Authenticate with Google Drive
        gdrive_service.authenticate()
        logger.info("✓ Google Drive authentication successful")
        
        # Load embedding model
        embedding_service.load_model()
        logger.info("✓ Embedding model loaded")
        
        # List files (limited)
        all_files = gdrive_service.list_files()
        files = all_files[:max_files]  # Limit to first N files
        logger.info(f"✓ Processing {len(files)} files out of {len(all_files)} total")
        
        if not files:
            logger.warning("No files found in Google Drive folder")
            return
        
        # Process each file
        total_chunks = 0
        processed = 0
        failed = 0
        
        for i, file_meta in enumerate(files, 1):
            try:
                logger.info(f"Processing file {i}/{len(files)}: {file_meta['name']}")
                
                # Download file content
                mime_type = file_meta.get("mimeType", "")
                content = gdrive_service.download_file(file_m