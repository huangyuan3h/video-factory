"""APScheduler-based task scheduler."""

import asyncio
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .config import settings
from .database import async_session_maker
from .models import PublisherAccount, Run, Source, Task
from .services.video_service import run_video_generation, video_tasks
from .sources import HotTopicsSource, NewsAPISource, RSSSource

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def _build_source(source: Source | None):
    """Build a concrete source instance from a DB Source row."""
    if source is None:
        return None
    keywords: list[str] = []
    if source.keywords:
        try:
            parsed = json.loads(source.keywords)
            if isinstance(parsed, list):
                keywords = [str(k) for k in parsed]
        except Exception:
            keywords = [k.strip() for k in str(source.keywords).split(",") if k.strip()]

    stype = (source.type or "").lower()
    if stype in ("rss", "feed"):
        if not source.url:
            return None
        return RSSSource(name=source.name, url=source.url, keywords=keywords)
    if stype in ("news", "news_api", "newsapi"):
        if not source.api_key:
            return None
        return NewsAPISource(name=source.name, api_key=source.api_key, keywords=keywords)
    if stype in ("hot_topics", "hot", "trending", "hot_topic"):
        platform = "weibo"
        haystack = f"{source.url or ''} {source.name or ''}".lower()
        for candidate in ("weibo", "zhihu", "douyin"):
            if candidate in haystack:
                platform = candidate
                break
        return HotTopicsSource(name=source.name, platform=platform, keywords=keywords)
    logger.warning(f"Unsupported source type: {source.type}")
    return None


async def _enabled_platforms(session) -> list[str]:
    """Distinct platforms with at least one enabled publisher account."""
    result = await session.execute(
        select(PublisherAccount.platform).where(PublisherAccount.enabled == True)
    )
    seen: list[str] = []
    for platform in result.scalars().all():
        key = (platform or "").lower().strip()
        if key and key not in seen:
            seen.append(key)
    return seen


async def execute_task(task_id: str, run_id: str | None = None):
    """Execute a task end-to-end: fetch content -> generate video -> (optional) publish."""
    if not run_id:
        run_id = hashlib.md5(f"{task_id}{datetime.now().isoformat()}".encode()).hexdigest()[:16]

    async with async_session_maker() as session:
        result = await session.execute(
            select(Task).options(selectinload(Task.source)).where(Task.id == task_id)
        )
        task = result.scalar_one_or_none()
        if not task:
            logger.error(f"Task {task_id} not found")
            return
        session.add(Run(id=run_id, task_id=task_id, status="processing", started_at=datetime.now()))
        await session.commit()
        task_name = task.name
        source_row = task.source

    logger.info(f"Executing task {task_name} ({task_id}) run={run_id}")
    video_path: str | None = None
    published: list | None = None

    try:
        source = _build_source(source_row)
        if source is None:
            raise ValueError(
                f"Source unavailable or unsupported: {source_row.type if source_row else 'missing'}"
            )
        items = await source.fetch(count=10)
        if not items:
            raise ValueError("Source returned no content")
        item = items[0]
        content = (item.content or "").strip() or item.title
        from .routes.videos import VideoGenerateRequest  # lazy to avoid import cycle

        request = VideoGenerateRequest(title=(item.title or "Untitled")[:200], content=content)

        if getattr(settings, "scheduler_auto_publish", False):
            async with async_session_maker() as s:
                platforms = await _enabled_platforms(s)
            if platforms:
                request.publish_to = platforms
                logger.info(f"Task {task_name}: auto-publish to {platforms}")

        async with async_session_maker() as s:
            run = await s.get(Run, run_id)
            if run:
                run.input_content = content
                await s.commit()

        task_dir = settings.output_dir / run_id
        video_tasks[run_id] = {
            "id": run_id,
            "status": "pending",
            "task_dir": str(task_dir),
            "progress": 0.0,
        }
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, run_video_generation, run_id, request, task_dir)

        info = video_tasks.get(run_id, {})
        if info.get("status") != "completed":
            raise RuntimeError(info.get("error") or "Video generation did not complete")

        video_path = info.get("video_path")
        published = info.get("published_to")

        async with async_session_maker() as s:
            run = await s.get(Run, run_id)
            if run:
                run.status = "completed"
                run.video_path = video_path
                run.ended_at = datetime.now()
                script_file = Path(info.get("task_dir", task_dir)) / "script.json"
                if script_file.exists():
                    run.script = script_file.read_text(encoding="utf-8")
                if published is not None:
                    run.published_to = json.dumps(published, ensure_ascii=False)
                await s.commit()
        logger.info(f"Task {task_name} completed")

    except Exception as e:
        logger.error(f"Task {task_name} failed: {e}", exc_info=True)
        async with async_session_maker() as s:
            run = await s.get(Run, run_id)
            if run:
                run.status = "failed"
                run.error = str(e)
                run.ended_at = datetime.now()
                await s.commit()


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
    """Manually trigger a task execution. Returns the run id."""
    run_id = hashlib.md5(f"{task_id}{datetime.now().isoformat()}".encode()).hexdigest()[:16]

    # Execute immediately in the background
    asyncio.create_task(execute_task(task_id, run_id))

    return run_id


async def init_scheduler():
    """Initialize scheduler and load all enabled tasks (idempotent)."""
    if scheduler.running:
        logger.info("Scheduler already running")
        return
    async with async_session_maker() as session:
        result = await session.execute(select(Task).where(Task.enabled == True))
        tasks = result.scalars().all()

        for task in tasks:
            await add_task(task)

    scheduler.start()
    logger.info("Scheduler started")


async def shutdown_scheduler():
    """Shutdown the scheduler (idempotent)."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler shutdown")
