"""Independent worker process — consumes queue, not API request thread.

Run: `uv run python -m src.worker`  (or `uv run src/worker.py`)
Separate from `uvicorn src.main:app` so API stays snappy and GPU tasks scale.

Consumes Redis when configured; otherwise polls the `generation_jobs` DB table
(set QUEUE_BACKEND=db so the API persists jobs instead of running them inline).
"""

import asyncio
import logging
from pathlib import Path

from .config import settings
from .database import init_db
from .queue import claim_next_job, mark_job, queue_depth
from .services.video_service import run_video_generation, video_tasks

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [worker] %(levelname)s %(message)s")


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

    depth = await queue_depth()
    logger.info(f"Worker picked {task_id} title={req.title} backend={backend} depth={depth}")

    # run_video_generation is sync and creates its own loop; run it in a thread
    # so it never conflicts with this worker's event loop.
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, run_video_generation, task_id, req, task_dir)

    info = video_tasks.get(task_id, {})
    if backend == "db":
        if info.get("status") == "completed":
            await mark_job(task_id, "completed")
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
