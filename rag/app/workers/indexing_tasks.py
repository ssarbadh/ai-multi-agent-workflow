"""Celery tasks for document indexing."""
import logging
from typing import Dict, Any, List
from datetime import datetime

from app.celery_app import celery_app
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.models import IndexingJob, Document
from app.services.gdrive import gdrive_service
from app.services.haystack_pipeline import indexing_pipeline

logger = logging.getLogger(__name__)


@celery_app.task(name="indexing.full_reindex", bind=True)
def full_reindex_task(self, job_id: str) -> Dict[str, Any]:
    """
    Celery task for full reindexing from Google Drive.
    
    Args:
        job_id: Unique job identifier
        
    Returns:
        Job result dictionary
    """
    import asyncio
    return asyncio.run(_execute_full_reindex(self, job_id))


@celery_app.task(name="indexing.incremental_refresh", bind=True)
def incremental_refresh_task(self, job_id: str) -> Dict[str, Any]:
    """
    Celery task for incremental refresh.
    
    Args:
        job_id: Unique job identifier
        
    Returns:
        Job result dictionary
    """
    import asyncio
    return asyncio.run(_execute_incremental_refresh(self, job_id))


@celery_app.task(name="indexing.index_single_file", bind=True)
def index_single_file_task(self, file_id: str, file_metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Celery task for indexing a single file.
    
    Args:
        file_id: Google Drive file ID
        file_metadata: File metadata dictionary
        
    Returns:
        Indexing result
    """
    import asyncio
    return asyncio.run(_execute_index_single_file(self, file_id, file_metadata))


async def _execute_full_reindex(task, job_id: str) -> Dict[str, Any]:
    """Execute full reindex operation."""
    async with AsyncSessionLocal() as session:
        try:
            # Update job status
            job = await session.get(IndexingJob, job_id)
            if not job:
                raise ValueError(f"Job {job_id} not found")
            
            job.status = "running"
            await session.commit()
            
            # Fetch files from Google Drive
            logger.info(f"[Job {job_id}] Fetching files from Google Drive...")
            files = gdrive_service.list_files()
            job.total_files = len(files)
            await session.commit()
            
            # Index files using Haystack pipeline
            total_chunks = 0
            processed = 0
            failed = 0
            
            for file_meta in files:
                try:
                    # Update progress
                    task.update_state(
                        state="PROGRESS",
                        meta={
                            "job_id": job_id,
                            "processed": processed,
                            "total": len(files),
                            "current_file": file_meta.get("name")
                        }
                    )
                    
                    # Process file through Haystack
                    result = await indexing_pipeline.run_async(
                        file_id=file_meta["id"],
                        file_metadata=file_meta
                    )
                    
                    total_chunks += result.get("chunks_created", 0)
                    processed += 1
                    
                except Exception as e:
                    logger.error(f"[Job {job_id}] Failed to index file {file_meta.get('name')}: {e}")
                    failed += 1
                
                # Update job progress
                job.processed_files = processed
                job.failed_files = failed
                job.total_chunks = total_chunks
                await session.commit()
            
            # Complete job
            job.status = "completed"
            job.completed_at = datetime.utcnow()
            job.duration_seconds = (job.completed_at - job.started_at).total_seconds()
            await session.commit()
            
            logger.info(f"[Job {job_id}] Completed: {processed} files, {total_chunks} chunks")
            
            return {
                "job_id": job_id,
                "status": "completed",
                "processed_files": processed,
                "failed_files": failed,
                "total_chunks": total_chunks
            }
            
        except Exception as e:
            logger.error(f"[Job {job_id}] Full reindex failed: {e}")
            if job:
                job.status = "failed"
                job.error_message = str(e)
                job.completed_at = datetime.utcnow()
                await session.commit()
            raise


async def _execute_incremental_refresh(task, job_id: str) -> Dict[str, Any]:
    """Execute incremental refresh operation."""
    async with AsyncSessionLocal() as session:
        try:
            job = await session.get(IndexingJob, job_id)
            if not job:
                raise ValueError(f"Job {job_id} not found")
            
            job.status = "running"
            await session.commit()
            
            # Fetch changed files since last index
            logger.info(f"[Job {job_id}] Fetching changed files...")
            changed_files = gdrive_service.get_changed_files()
            job.total_files = len(changed_files)
            await session.commit()
            
            total_chunks = 0
            processed = 0
            failed = 0
            
            for file_meta in changed_files:
                try:
                    task.update_state(
                        state="PROGRESS",
                        meta={
                            "job_id": job_id,
                            "processed": processed,
                            "total": len(changed_files),
                            "current_file": file_meta.get("name")
                        }
                    )
                    
                    # Check if file was deleted
                    if file_meta.get("trashed", False):
                        # Mark documents as deleted
                        await session.execute(
                            Document.__table__.update()
                            .where(Document.file_id == file_meta["id"])
                            .values(is_deleted=True, modified_at=datetime.utcnow())
                        )
                    else:
                        # Reindex file
                        result = await indexing_pipeline.run_async(
                            file_id=file_meta["id"],
                            file_metadata=file_meta
                        )
                        total_chunks += result.get("chunks_created", 0)
                    
                    processed += 1
                    
                except Exception as e:
                    logger.error(f"[Job {job_id}] Failed to process file {file_meta.get('name')}: {e}")
                    failed += 1
                
                job.processed_files = processed
                job.failed_files = failed
                job.total_chunks = total_chunks
                await session.commit()
            
            job.status = "completed"
            job.completed_at = datetime.utcnow()
            job.duration_seconds = (job.completed_at - job.started_at).total_seconds()
            await session.commit()
            
            logger.info(f"[Job {job_id}] Incremental refresh completed")
            
            return {
                "job_id": job_id,
                "status": "completed",
                "processed_files": processed,
                "failed_files": failed,
                "total_chunks": total_chunks
            }
            
        except Exception as e:
            logger.error(f"[Job {job_id}] Incremental refresh failed: {e}")
            if job:
                job.status = "failed"
                job.error_message = str(e)
                job.completed_at = datetime.utcnow()
                await session.commit()
            raise


async def _execute_index_single_file(task, file_id: str, file_metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Index a single file."""
    try:
        result = await indexing_pipeline.run_async(
            file_id=file_id,
            file_metadata=file_metadata
        )
        return result
    except Exception as e:
        logger.error(f"Failed to index file {file_id}: {e}")
        raise
