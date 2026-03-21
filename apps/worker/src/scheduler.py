"""APScheduler-based task scheduler."""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import async_session_maker
from .models import Run, Task

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def execute_task(task_id: str):
    """Execute a task and create a run record."""
    async with async_session_maker() as session:
        # Get task
        result = await session.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            logger.error(f"Task {task_id} not found")
            return

        # Create run record
        import hashlib
        run_id = hashlib.md5(f"{task_id}{datetime.now().isoformat()}".encode()).hexdigest()[:16]
        run = Run(
            id=run_id,
            task_id=task_id,
            status="processing",
            started_at=datetime.now(),
        )
        session.add(run)
        await session.commit()

        try:
            logger.info(f"Executing task {task.name} ({task_id})")

            # TODO: Implement actual task execution
            # 1. Fetch content from source
            # 2. Generate script with AI
            # 3. Generate video
            # 4. Publish to platforms

            # Simulate execution
            await asyncio.sleep(5)

            run.status = "completed"
            run.ended_at = datetime.now()
            logger.info(f"Task {task.name} completed")

        except Exception as e:
            logger.error(f"Task {task.name} failed: {e}")
            run.status = "failed"
            run.error = str(e)
            run.ended_at = datetime.now()

        await session.commit()


async def add_task(task: Task):
    """Add a task to the scheduler."""
    if not task.enabled:
        return

    job_id = f"task_{task.id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    try:
        trigger = CronTrigger.from_crontab(task.schedule)
        scheduler.add_job(
            execute_task,
            trigger=trigger,
            id=job_id,
            args=[task.id],
            replace_existing=True,
        )
        logger.info(f"Scheduled task {task.name} with schedule {task.schedule}")
    except Exception as e:
        logger.error(f"Failed to schedule task {task.name}: {e}")


async def remove_task(task_id: str):
    """Remove a task from the scheduler."""
    job_id = f"task_{task_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info(f"Removed task {task_id}")


async def update_task(task: Task):
    """Update a task in the scheduler."""
    await remove_task(task.id)
    if task.enabled:
        await add_task(task)


async def trigger_task(task_id: str) -> str:
    """Manually trigger a task execution."""
    import hashlib
    run_id = hashlib.md5(f"{task_id}{datetime.now().isoformat()}".encode()).hexdigest()[:16]

    # Execute immediately
    asyncio.create_task(execute_task(task_id))

    return run_id


async def init_scheduler():
    """Initialize scheduler and load all enabled tasks."""
    async with async_session_maker() as session:
        result = await session.execute(select(Task).where(Task.enabled == True))
        tasks = result.scalars().all()

        for task in tasks:
            await add_task(task)

    scheduler.start()
    logger.info("Scheduler started")


async def shutdown_scheduler():
    """Shutdown the scheduler."""
    scheduler.shutdown()
    logger.info("Scheduler shutdown")