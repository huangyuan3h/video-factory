"""Task queue abstraction — Redis if available, else in-memory + DB poll.

API keeps POST /api/videos/generate fast (enqueue <50ms).
Worker is a separate process: `uv run python -m src.worker` or `celery`-like loop.
For lambda-absent GPU tasks, always prefer dedicated worker.

Backends (settings.queue_backend / QUEUE_BACKEND):
  * "auto" (default): Redis when reachable, otherwise run inline via
    FastAPI BackgroundTasks (no worker process required).
  * "db": Redis when reachable, otherwise persist jobs to the DB and let a
    separate `python -m src.worker` process consume them.
  * "redis": Redis only; if unreachable the caller falls back to inline.
"""

import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

_redis_client = None

QUEUE_KEY = "video_factory:jobs"


def _get_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    url = os.getenv("REDIS_URL") or os.getenv("REDIS_TLS_URL") or ""
    if not url:
        # Try Settings
        try:
            from .config import settings
            url = getattr(settings, "redis_url", "") or ""
        except Exception:
            url = ""
    if not url:
        return None
    try:
        import redis  # type: ignore

        _redis_client = redis.from_url(url, decode_responses=True)
        _redis_client.ping()
        logger.info(f"Queue: Redis at {url.split('@')[-1]}")
        return _redis_client
    except Exception as e:
        logger.warning(f"Redis unavailable ({e}), fallback to memory/DB")
        return None


def redis_available() -> bool:
    return _get_redis() is not None


def _queue_backend() -> str:
    try:
        from .config import settings

        return (getattr(settings, "queue_backend", "auto") or "auto").lower()
    except Exception:
        return "auto"


async def enqueue(job: dict) -> str:
    """Enqueue a job. Returns the backend used: 'redis' | 'db' | '' (inline fallback)."""
    r = _get_redis()
    if r:
        try:
            r.lpush(QUEUE_KEY, json.dumps(job, ensure_ascii=False))
            return "redis"
        except Exception as e:
            logger.warning(f"Redis enqueue failed: {e}")

    if _queue_backend() == "db":
        return await _enqueue_db(job)
    return ""


async def _enqueue_db(job: dict) -> str:
    from .database import async_session_maker
    from .models import GenerationJob

    try:
        async with async_session_maker() as session:
            session.add(
                GenerationJob(
                    id=job["task_id"],
                    task_uuid=job.get("task_uuid"),
                    series_id=job.get("series_id"),
                    task_dir=job.get("task_dir", ""),
                    request_json=json.dumps(job.get("request", {}), ensure_ascii=False),
                    status="pending",
                )
            )
            await session.commit()
        return "db"
    except Exception as e:
        logger.warning(f"DB enqueue failed: {e}")
        return ""


async def claim_next_job(timeout: int = 5) -> dict | None:
    """Claim the next job from Redis, else from the DB queue."""
    r = _get_redis()
    if r:
        try:
            res = r.brpop(QUEUE_KEY, timeout=timeout)
            if res:
                _, data = res
                return json.loads(data)
            return None
        except Exception as e:
            logger.warning(f"Redis dequeue failed: {e}")
    return await _claim_db_job()


async def _claim_db_job() -> dict | None:
    from sqlalchemy import select

    from .database import async_session_maker
    from .models import GenerationJob

    try:
        async with async_session_maker() as session:
            result = await session.execute(
                select(GenerationJob)
                .where(GenerationJob.status == "pending")
                .where(GenerationJob.cancel_requested.is_(False))
                .order_by(GenerationJob.created_at)
                .limit(1)
            )
            row = result.scalars().first()
            if not row:
                return None
            row.status = "processing"
            row.started_at = datetime.now()
            await session.commit()
            try:
                request = json.loads(row.request_json) if row.request_json else {}
            except Exception:
                request = {}
            return {
                "task_id": row.id,
                "task_uuid": row.task_uuid,
                "series_id": row.series_id,
                "task_dir": row.task_dir,
                "request": request,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "backend": "db",
            }
    except Exception as e:
        logger.warning(f"DB claim failed: {e}")
        return None


async def mark_job(task_id: str, status: str, error: str | None = None) -> None:
    """Update a DB-backed job status (no-op when the job is not in the DB)."""
    from .database import async_session_maker
    from .models import GenerationJob

    try:
        async with async_session_maker() as session:
            row = await session.get(GenerationJob, task_id)
            if not row:
                return
            row.status = status
            row.error = error
            row.ended_at = datetime.now()
            await session.commit()
    except Exception as e:
        logger.warning(f"DB mark_job failed: {e}")


async def update_job_progress(
    task_id: str,
    progress: float | None = None,
    current_step: int | None = None,
    message: str | None = None,
) -> None:
    """Mirror generation progress onto the DB-backed job (no-op for inline/Redis)."""
    from .database import async_session_maker
    from .models import GenerationJob

    try:
        async with async_session_maker() as session:
            row = await session.get(GenerationJob, task_id)
            if not row:
                return
            if progress is not None:
                row.progress = progress
            if current_step is not None:
                row.current_step = current_step
            if message is not None:
                row.message = message
            await session.commit()
    except Exception as e:
        logger.debug(f"DB update_job_progress failed: {e}")


async def request_cancel(task_id: str) -> bool:
    """Flag a job for cancellation. Pending jobs are marked cancelled immediately."""
    from .database import async_session_maker
    from .models import GenerationJob

    try:
        async with async_session_maker() as session:
            row = await session.get(GenerationJob, task_id)
            if not row:
                return False
            row.cancel_requested = True
            if row.status == "pending":
                row.status = "cancelled"
                row.message = "任务已取消"
                row.ended_at = datetime.now()
            await session.commit()
        return True
    except Exception as e:
        logger.warning(f"DB request_cancel failed: {e}")
        return False


async def is_cancel_requested(task_id: str) -> bool:
    from .database import async_session_maker
    from .models import GenerationJob

    try:
        async with async_session_maker() as session:
            row = await session.get(GenerationJob, task_id)
            return bool(row and row.cancel_requested)
    except Exception:
        return False


async def enqueue_publish_jobs(jobs: list[dict]) -> int:
    """Persist a batch of publish jobs. Returns how many were created."""
    from .database import async_session_maker
    from .models import PublishJob

    created = 0
    try:
        async with async_session_maker() as session:
            for job in jobs:
                session.add(
                    PublishJob(
                        id=job["id"],
                        task_id=job["task_id"],
                        series_id=job.get("series_id"),
                        video_path=job.get("video_path"),
                        task_dir=job.get("task_dir"),
                        account_id=job.get("account_id"),
                        platform=job["platform"],
                        title=job.get("title"),
                        description=job.get("description"),
                        tags_json=job.get("tags_json"),
                        folder_id=job.get("folder_id"),
                        privacy=job.get("privacy"),
                        status="pending",
                    )
                )
                created += 1
            await session.commit()
    except Exception as e:
        logger.warning(f"enqueue_publish_jobs failed: {e}")
        return 0
    return created


async def claim_next_publish_job() -> dict | None:
    from sqlalchemy import select

    from .database import async_session_maker
    from .models import PublishJob

    try:
        async with async_session_maker() as session:
            result = await session.execute(
                select(PublishJob)
                .where(PublishJob.status == "pending")
                .order_by(PublishJob.created_at)
                .limit(1)
            )
            row = result.scalars().first()
            if not row:
                return None
            row.status = "processing"
            row.attempts = (row.attempts or 0) + 1
            row.started_at = datetime.now()
            await session.commit()
            return {
                "id": row.id,
                "task_id": row.task_id,
                "series_id": row.series_id,
                "video_path": row.video_path,
                "task_dir": row.task_dir,
                "account_id": row.account_id,
                "platform": row.platform,
                "title": row.title,
                "description": row.description,
                "tags": json.loads(row.tags_json) if row.tags_json else [],
                "folder_id": row.folder_id,
                "privacy": row.privacy,
                "attempts": row.attempts,
            }
    except Exception as e:
        logger.warning(f"claim_next_publish_job failed: {e}")
        return None


async def mark_publish_job(
    job_id: str,
    status: str,
    post_url: str | None = None,
    post_id: str | None = None,
    error: str | None = None,
) -> None:
    from .database import async_session_maker
    from .models import PublishJob

    try:
        async with async_session_maker() as session:
            row = await session.get(PublishJob, job_id)
            if not row:
                return
            row.status = status
            if post_url:
                row.post_url = post_url
            if post_id:
                row.post_id = post_id
            if error:
                row.error = error
            row.ended_at = datetime.now()
            await session.commit()
    except Exception as e:
        logger.warning(f"mark_publish_job failed: {e}")


async def retry_publish_job(job_id: str) -> bool:
    from .database import async_session_maker
    from .models import PublishJob

    try:
        async with async_session_maker() as session:
            row = await session.get(PublishJob, job_id)
            if not row:
                return False
            row.status = "pending"
            row.error = None
            row.started_at = None
            row.ended_at = None
            await session.commit()
        return True
    except Exception as e:
        logger.warning(f"retry_publish_job failed: {e}")
        return False


async def publish_queue_depth() -> int:
    from sqlalchemy import func, select

    from .database import async_session_maker
    from .models import PublishJob

    try:
        async with async_session_maker() as session:
            result = await session.execute(
                select(func.count()).select_from(PublishJob).where(PublishJob.status == "pending")
            )
            return int(result.scalar() or 0)
    except Exception:
        return 0


async def queue_depth() -> int:
    """Number of pending jobs (Redis priority, else DB)."""
    r = _get_redis()
    if r:
        try:
            return int(r.llen(QUEUE_KEY))
        except Exception:
            pass
    try:
        from sqlalchemy import func, select

        from .database import async_session_maker
        from .models import GenerationJob

        async with async_session_maker() as session:
            result = await session.execute(
                select(func.count())
                .select_from(GenerationJob)
                .where(GenerationJob.status == "pending")
            )
            return int(result.scalar() or 0)
    except Exception:
        return 0
