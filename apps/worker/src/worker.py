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
    is_cancel_requested,
    mark_job,
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
        await asyncio.sleep(1)


def main():
    try:
        asyncio.run(_poll_loop())
    except KeyboardInterrupt:
        logger.info("Worker stopped")


if __name__ == "__main__":
    main()
