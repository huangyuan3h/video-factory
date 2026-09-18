"""Publishing job management routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models import PublishJob
from ..queue import publish_queue_depth, retry_publish_job

router = APIRouter()


def _to_dict(job: PublishJob) -> dict:
    return {
        "id": job.id,
        "task_id": job.task_id,
        "series_id": job.series_id,
        "account_id": job.account_id,
        "platform": job.platform,
        "title": job.title,
        "folder_id": job.folder_id,
        "privacy": job.privacy,
        "status": job.status,
        "attempts": job.attempts,
        "post_url": job.post_url,
        "post_id": job.post_id,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "ended_at": job.ended_at.isoformat() if job.ended_at else None,
    }


@router.get("/jobs")
async def list_publish_jobs(status: str | None = None, session: AsyncSession = Depends(get_session)):
    """List publish jobs, optionally filtered by status."""
    query = select(PublishJob)
    if status:
        query = query.where(PublishJob.status == status)
    query = query.order_by(PublishJob.created_at.desc()).limit(200)
    result = await session.execute(query)
    jobs = [_to_dict(j) for j in result.scalars().all()]
    return {"success": True, "data": jobs, "depth": await publish_queue_depth()}


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str):
    """Re-queue a failed publish job."""
    ok = await retry_publish_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Publish job not found")
    return {"success": True, "data": {"id": job_id, "status": "pending"}}
