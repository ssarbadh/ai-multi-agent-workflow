"""API router for indexing endpoints."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.indexing import indexing_service
from app.models.models import IndexingJob
from app.models.schemas import ReindexRequest, ReindexResponse, JobStatus

router = APIRouter(prefix="/reindex", tags=["indexing"])


@router.post("", response_model=ReindexResponse)
async def reindex(
    request: ReindexRequest,
    session: AsyncSession = Depends(get_db)
):
    """Trigger reindexing from Google Drive."""
    try:
        if request.job_type == "full":
            job_id = await indexing_service.full_reindex(session)
        elif request.job_type == "incremental":
            job_id = await indexing_service.incremental_refresh(session)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid job_type. Must be 'full' or 'incremental'"
            )
        
        return ReindexResponse(
            job_id=job_id,
            job_type=request.job_type,
            status="running",
            message=f"Reindex job {job_id} started"
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Reindex failed: {str(e)}"
        )


@router.get("/status/{job_id}", response_model=JobStatus)
async def get_job_status(
    job_id: str,
    session: AsyncSession = Depends(get_db)
):
    """Get status of an indexing job."""
    stmt = select(IndexingJob).where(IndexingJob.id == job_id)
    result = await session.execute(stmt)
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found"
        )
    
    return JobStatus(
        job_id=job.id,
        job_type=job.job_type,
        status=job.status,
        total_files=job.total_files or 0,
        processed_files=job.processed_files or 0,
        failed_files=job.failed_files or 0,
        total_chunks=job.total_chunks or 0,
        started_at=job.started_at,
        completed_at=job.completed_at,
        duration_seconds=job.duration_seconds,
        error_message=job.error_message
    )
