"""Independent worker process — consumes queue, not API request thread.

Run: `uv run python -m src.worker`  (or `uv run src/worker.py`)
Separate from `uvicorn src.main:app` so API stays snappy and GPU tasks scale.
"""

import asyncio
import json
import logging
import time
from pathlib import Path

from .config import settings
from .database import init_db
from .queue import dequeue, queue_depth
from .services.video_service import run_video_generation, video_tasks
from .core.task_logger import TaskLogger

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [worker] %(levelname)s %(message)s")


async def _handle_job(job: dict):
    task_id = job.get("task_id")
    task_dir = Path(job.get("task_dir")) if job.get("task_dir") else settings.output_dir / job.get("task_uuid", task_id)
    # Rehydrate request object from job payload
    from .routes.videos import VideoGenerateRequest

    try:
        req = VideoGenerateRequest.model_validate(job.get("request"))
    except Exception as e:
        logger.error(f"Invalid job payload {task_id}: {e}")
        return
    # Ensure task entry exists
    if task_id not in video_tasks:
        video_tasks[task_id] = {"id": task_id, "status": "pending", "task_dir": str(task_dir)}
    logger.info(f"Worker picked {task_id} title={req.title} depth={queue_depth()}")
    # run_video_generation is sync + creates its own loop; call directly
    run_video_generation(task_id, req, task_dir)


async def _poll_loop():
    await init_db()
    logger.info("Worker ready, polling queue (Redis or DB fallback)...")
    while True:
        job = dequeue(block=True, timeout=5)
        if job:
            try:
                await _handle_job(job)
            except Exception as e:
                logger.error(f"Job failed {job.get('task_id')}: {e}", exc_info=True)
            continue
        # DB fallback: find pending video_tasks not yet started (no log file yet)
        # This covers dev without Redis where enqueue returned False and task sits pending
        pending = [tid for tid, v in list(video_tasks.items()) if v.get("status") == "pending" and not (Path(v.get("task_dir", "")) / "status.json").exists()]
        # Actually status.json is created at init, so we use a marker: check if worker already handled
        # For now just sleep; real DB jobs would be fetched from DB table in future
        await asyncio.sleep(2)


def main():
    try:
        asyncio.run(_poll_loop())
    except KeyboardInterrupt:
        logger.info("Worker stopped")


if __name__ == "__main__":
    main()
