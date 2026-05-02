"""Indexing service using Celery for background processing."""
import logging
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import IndexingJob
from app.workers.indexing_tasks import full_reindex_task, incremental_refresh_task

logger = logging.getLogger(__name__)


class IndexingService:
    """Service for managing document indexing jobs via Celery."""
    
    async def full_reindex(self, session: AsyncSession) -> str:
        """
        Trigger full reindex job via Celery.
        
        Args:
            session: Database session
            
        Returns:
            Job ID
        """
        try:
            # Create job record
            job_id = str(uuid.uuid4())
            job = IndexingJob(
                id=job_id,
                job_type="full",
                status="pending",
                started_at=datetime.utcnow()
            )
            session.add(job)
            await session.commit()
            
            # Dispatch Celery task
            full_reindex_task.delay(job_id)
            
            logger.info(f"Full reindex job {job_id} dispatched to Celery")
            return job_id
            
        except Exception as e:
            logger.error(f"Failed to start full reindex: {e}")
            raise
    
    async def incremental_refresh(self, session: AsyncSession) -> str:
        """
        Trigger incremental refresh job via Celery.
        
        Args:
            session: Database session
            
        Returns:
            Job ID
        """
        try:
            # Create job record
            job_id = str(uuid.uuid4())
            job = IndexingJob(
                id=job_id,
                job_type="incremental",
                status="pending",
                started_at=datetime.utcnow()
            )
            session.add(job)
            await session.commit()
            
            # Dispatch Celery task
            incremental_refresh_task.delay(job_id)
            
            logger.info(f"Incremental refresh job {job_id} dispatched to Celery")
            return job_id
            
        except Exception as e:
            logger.error(f"Failed to start incremental refresh: {e}")
            raise


# Singleton instance
indexing_service = IndexingService()
