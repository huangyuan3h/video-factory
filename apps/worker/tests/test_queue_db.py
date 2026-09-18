"""Tests for the queue abstraction (Redis + DB fallback)."""

import json
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.config import settings
from src.database import Base
from src import models  # noqa: F401  (register tables)
from src import queue as q


class _FakeRedis:
    def __init__(self):
        self.items = []

    def lpush(self, key, value):
        self.items.insert(0, value)
        return len(self.items)

    def brpop(self, key, timeout=0):
        if self.items:
            return (key, self.items.pop())
        return None

    def llen(self, key):
        return len(self.items)


@pytest_asyncio.fixture
async def mem_sessionmaker():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    with patch("src.database.async_session_maker", maker):
        yield maker
    await engine.dispose()


@pytest.mark.asyncio
async def test_enqueue_auto_without_redis_returns_inline(mem_sessionmaker):
    with patch.object(q, "_get_redis", return_value=None), patch.object(
        settings, "queue_backend", "auto"
    ):
        backend = await q.enqueue({"task_id": "t1", "task_dir": "/tmp", "request": {}})
    assert backend == ""


@pytest.mark.asyncio
async def test_enqueue_db_creates_row(mem_sessionmaker):
    with patch.object(q, "_get_redis", return_value=None), patch.object(
        settings, "queue_backend", "db"
    ):
        backend = await q.enqueue(
            {"task_id": "t2", "task_uuid": "u2", "task_dir": "/tmp", "request": {"title": "x"}}
        )
    assert backend == "db"
    assert await q.queue_depth() == 1


@pytest.mark.asyncio
async def test_claim_and_mark_db_job(mem_sessionmaker):
    with patch.object(q, "_get_redis", return_value=None), patch.object(
        settings, "queue_backend", "db"
    ):
        await q.enqueue(
            {"task_id": "t3", "task_uuid": "u3", "task_dir": "/tmp", "request": {"title": "hello"}}
        )
        job = await q.claim_next_job(timeout=0)

    assert job is not None
    assert job["task_id"] == "t3"
    assert job["backend"] == "db"
    assert job["request"] == {"title": "hello"}
    # claimed job no longer pending
    assert await q.queue_depth() == 0

    await q.mark_job("t3", "completed")
    await q.mark_job("t3", "failed", "boom")
    # marking a missing job is a no-op
    await q.mark_job("missing", "failed", "nope")


@pytest.mark.asyncio
async def test_claim_empty_returns_none(mem_sessionmaker):
    with patch.object(q, "_get_redis", return_value=None):
        assert await q.claim_next_job(timeout=0) is None
    assert await q.queue_depth() == 0


@pytest.mark.asyncio
async def test_redis_enqueue_and_claim():
    fake = _FakeRedis()
    with patch.object(q, "_get_redis", return_value=fake):
        backend = await q.enqueue({"task_id": "r1", "request": {"a": 1}})
        assert backend == "redis"
        assert await q.queue_depth() == 1
        job = await q.claim_next_job(timeout=0)
    assert job == {"task_id": "r1", "request": {"a": 1}}


@pytest.mark.asyncio
async def test_redis_errors_fall_through():
    broken = MagicMock()
    broken.lpush.side_effect = RuntimeError("down")
    broken.brpop.side_effect = RuntimeError("down")
    broken.llen.side_effect = RuntimeError("down")
    with patch.object(q, "_get_redis", return_value=broken), patch.object(
        settings, "queue_backend", "auto"
    ):
        assert await q.enqueue({"task_id": "r2", "request": {}}) == ""
    with patch.object(q, "_get_redis", return_value=broken), patch.object(
        q, "_claim_db_job", return_value=None
    ):
        assert await q.claim_next_job(timeout=0) is None


@pytest.mark.asyncio
async def test_request_cancel_pending_marks_cancelled(mem_sessionmaker):
    with patch.object(q, "_get_redis", return_value=None), patch.object(settings, "queue_backend", "db"):
        await q.enqueue({"task_id": "c1", "task_dir": "/tmp", "request": {}})
    assert await q.request_cancel("c1") is True
    assert await q.is_cancel_requested("c1") is True
    # cancelled jobs are no longer claimable
    with patch.object(q, "_get_redis", return_value=None):
        assert await q.claim_next_job(timeout=0) is None
    assert await q.queue_depth() == 0


@pytest.mark.asyncio
async def test_update_job_progress(mem_sessionmaker):
    with patch.object(q, "_get_redis", return_value=None), patch.object(settings, "queue_backend", "db"):
        await q.enqueue({"task_id": "p1", "task_dir": "/tmp", "request": {}})
    await q.update_job_progress("p1", progress=0.5, current_step=3, message="合成语音")
    # unknown job is a no-op
    await q.update_job_progress("missing", progress=1.0)
    # request_cancel on unknown job returns False
    assert await q.request_cancel("missing") is False


@pytest.mark.asyncio
async def test_publish_job_lifecycle(mem_sessionmaker):
    jobs = [
        {
            "id": "pj1",
            "task_id": "t1",
            "series_id": None,
            "video_path": "/tmp/v.mp4",
            "task_dir": "/tmp",
            "account_id": "a1",
            "platform": "youtube",
            "title": "T",
        }
    ]
    assert await q.enqueue_publish_jobs(jobs) == 1
    assert await q.publish_queue_depth() == 1

    claimed = await q.claim_next_publish_job()
    assert claimed["id"] == "pj1"
    assert claimed["attempts"] == 1
    assert claimed["video_path"] == "/tmp/v.mp4"
    assert await q.publish_queue_depth() == 0

    await q.mark_publish_job("pj1", "completed", post_url="http://x", post_id="abc")
    assert await q.retry_publish_job("pj1") is True
    assert await q.publish_queue_depth() == 1
    assert await q.retry_publish_job("missing") is False
    await q.mark_publish_job("missing", "failed", error="nope")
