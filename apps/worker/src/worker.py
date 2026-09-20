"""Independent worker process — consumes queue, not API request thread.

Run: `uv run python -m src.worker`  (or `uv run src/worker.py`)
Separate from `uvicorn src.main:app` so API stays snappy and GPU tasks scale.

Consumes Redis when configured; otherwise polls the `generation_jobs` DB table
(set QUEUE_BACKEND=db so the API persists jobs instead of running them inline).
"""

import asyncio
import json
import logging
from pathlib import Path

from .config import settings
from .database import init_db
from .queue import (
    claim_next_job,
    claim_next_publish_job,
    is_cancel_requested,
    mark_job,
    mark_publish_job,
    queue_depth,
    update_job_progress,
)
from .services.video_service import run_video_generation, video_tasks

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [worker] %(levelname)s %(message)s")


async def _sync_progress(task_id: str, task_dir: Path, stop: asyncio.Event):
    """Mirror status.json progress onto the DB job every couple of seconds."""
    status_file = task_dir / "status.json"
    while not stop.is_set():
        try:
            if status_file.exists():
                data = json.loads(status_file.read_text(encoding="utf-8"))
                await update_job_progress(
                    task_id,
                    progress=data.get("progress"),
                    current_step=data.get("current_step"),
                    message=data.get("message"),
                )
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=2)
        except asyncio.TimeoutError:
            pass


async def _handle_job(job: dict):
    task_id = job.get("task_id")
    task_dir = Path(job.get("task_dir")) if job.get("task_dir") else settings.output_dir / job.get("task_uuid", task_id)
    backend = job.get("backend", "redis")

    # Rehydrate request object from job payload
    from .routes.videos import VideoGenerateRequest

    try:
        req = VideoGenerateRequest.model_validate(job.get("request"))
    except Exception as e:
        logger.error(f"Invalid job payload {task_id}: {e}")
        if backend == "db":
            await mark_job(task_id, "failed", f"Invalid job payload: {e}")
        return

    # Ensure task entry exists for TaskLogger / status tracking
    if task_id not in video_tasks:
        video_tasks[task_id] = {"id": task_id, "status": "pending", "task_dir": str(task_dir)}
    if job.get("series_id"):
        video_tasks[task_id]["series_id"] = job["series_id"]

    if backend == "db" and await is_cancel_requested(task_id):
        video_tasks[task_id]["status"] = "cancelled"
        await mark_job(task_id, "cancelled", "任务已取消")
        logger.info(f"Job {task_id} was cancelled before start")
        return

    depth = await queue_depth()
    logger.info(f"Worker picked {task_id} title={req.title} backend={backend} depth={depth}")

    # run_video_generation is sync and creates its own loop; run it in a thread
    # so it never conflicts with this worker's event loop.
    loop = asyncio.get_event_loop()
    stop = asyncio.Event()
    sync = asyncio.create_task(_sync_progress(task_id, task_dir, stop)) if backend == "db" else None
    try:
        await loop.run_in_executor(None, run_video_generation, task_id, req, task_dir)
    finally:
        if sync:
            stop.set()
            await sync

    info = video_tasks.get(task_id, {})
    if backend == "db":
        status = info.get("status")
        if status in ("completed", "cancelled", "failed"):
            await mark_job(task_id, status, info.get("error"))
        else:
            await mark_job(task_id, "failed", info.get("error") or "Video generation failed")


async def _poll_loop():
    await init_db()
    logger.info("Worker ready, polling queue (Redis or DB fallback)...")
    while True:
        job = await claim_next_job(timeout=5)
        if job:
            try:
                await _handle_job(job)
            except Exception as e:
                logger.error(f"Job failed {job.get('task_id')}: {e}", exc_info=True)
                if job.get("backend") == "db":
                    await mark_job(job.get("task_id"), "failed", str(e))
            continue

        publish_job = await claim_next_publish_job()
        if publish_job:
            try:
                await _execute_publish_job(publish_job)
            except Exception as e:
                logger.error(f"Publish job failed {publish_job.get('id')}: {e}", exc_info=True)
                await mark_publish_job(publish_job.get("id"), "failed", error=str(e))
            continue

        await asyncio.sleep(1)


async def _execute_publish_job(job: dict):
    """Run one queued publish job through its platform publisher."""
    from .database import async_session_maker
    from .models import PublisherAccount
    from .publishers import get_publisher

    job_id = job["id"]
    platform = job.get("platform") or ""
    video_path = job.get("video_path")
    if video_path and not Path(video_path).exists():
        # Fall back to task output.mp4 if the recorded path is gone
        video_path = str(Path(job.get("task_dir") or "") / "output.mp4")
    if not video_path or not Path(video_path).exists():
        await mark_publish_job(job_id, "failed", error="video file not found")
        logger.warning(f"Publish job {job_id}: video not found")
        return

    account_id = job.get("account_id")
    if not account_id:
        await mark_publish_job(job_id, "failed", error="no publisher account on job")
        return
    async with async_session_maker() as session:
        acc = await session.get(PublisherAccount, account_id)
    if not acc:
        await mark_publish_job(job_id, "failed", error="publisher account not found")
        return

    pub = None
    try:
        pub = get_publisher(
            platform,
            credentials=acc.credentials or acc.cookies,
            cookies=acc.cookies,
            folder_id=acc.folder_id,
        )
        folder = job.get("folder_id") or acc.folder_id
        result = await pub.upload(
            video_path=Path(video_path),
            title=job.get("title") or "Video",
            description=job.get("description"),
            tags=job.get("tags") or [],
            folder_id=folder,
            playlist_id=folder,
            privacy=job.get("privacy") or "private",
            default_language=job.get("language"),
        )
        if result.success:
            await mark_publish_job(job_id, "completed", post_url=result.post_url, post_id=result.post_id)
            logger.info(f"Publish job {job_id} -> {platform}: {result.post_url or result.post_id}")
        else:
            await mark_publish_job(job_id, "failed", error=result.error)
            logger.warning(f"Publish job {job_id} failed: {result.error}")
    finally:
        if pub is not None:
            try:
                await pub.close_browser()
            except Exception:
                pass


def main():
    try:
        asyncio.run(_poll_loop())
    except KeyboardInterrupt:
        logger.info("Worker stopped")


if __name__ == "__main__":
    main()
