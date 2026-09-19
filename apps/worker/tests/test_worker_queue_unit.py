"""Unit tests for worker.py, queue.py and material services.

No network, no Redis, no real DB writes: every external collaborator is patched.
"""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src import models  # noqa: F401  (register tables)
from src import queue as q
from src import worker as worker_mod
from src.config import settings
from src.database import Base
from src.services.material.local_assets_service import LocalAssetsService
from src.services.material.pixabay_service import PixabayService
from src.services.video_service import video_tasks


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
class FakeRedis:
    def __init__(self):
        self.store: dict[str, list[str]] = {}

    def lpush(self, key, value):
        self.store.setdefault(key, []).insert(0, value)
        return len(self.store[key])

    def brpop(self, key, timeout=0):
        lst = self.store.get(key) or []
        if not lst:
            return None
        return (key, lst.pop())

    def llen(self, key):
        return len(self.store.get(key) or [])


class _FakeSession:
    """Minimal async context manager / session double."""

    def __init__(self, obj=None):
        self._obj = obj

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, model, key):
        return self._obj


def _maker(obj=None):
    return lambda: _FakeSession(obj)


@pytest_asyncio.fixture
async def maker():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    with patch("src.database.async_session_maker", session_maker), patch.object(
        q, "_get_redis", return_value=None
    ):
        yield session_maker
    await engine.dispose()


async def _add_job(maker, **kw):
    from src.models import GenerationJob

    async with maker() as session:
        session.add(
            GenerationJob(
                id=kw.get("id", "j1"),
                task_uuid=kw.get("task_uuid"),
                series_id=kw.get("series_id"),
                task_dir=kw.get("task_dir", "/tmp"),
                request_json=kw.get("request_json", '{"title": "t"}'),
                status=kw.get("status", "pending"),
                cancel_requested=kw.get("cancel_requested", False),
            )
        )
        await session.commit()


async def _add_publish_job(maker, **kw):
    from src.models import PublishJob

    async with maker() as session:
        session.add(
            PublishJob(
                id=kw.get("id", "p1"),
                task_id=kw.get("task_id", "t1"),
                platform=kw.get("platform", "youtube"),
                status=kw.get("status", "pending"),
                tags_json=kw.get("tags_json"),
                video_path=kw.get("video_path"),
                attempts=kw.get("attempts", 0),
            )
        )
        await session.commit()


# =========================================================================== #
# queue.py — Redis helpers
# =========================================================================== #
def test_get_redis_returns_cached(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(q, "_redis_client", sentinel)
    assert q._get_redis() is sentinel


def test_get_redis_connects_from_env(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_TLS_URL", raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(q, "_redis_client", None)
    fake = MagicMock()
    fake.ping.return_value = True
    with patch("redis.from_url", return_value=fake) as from_url:
        assert q._get_redis() is fake
    from_url.assert_called_once()


def test_get_redis_connects_from_settings(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_TLS_URL", raising=False)
    monkeypatch.setattr(q, "_redis_client", None)
    fake = MagicMock()
    fake.ping.return_value = True
    with patch.object(settings, "redis_url", "redis://settings"), patch(
        "redis.from_url", return_value=fake
    ):
        assert q._get_redis() is fake


def test_get_redis_unavailable_on_error(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_TLS_URL", raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://nope")
    monkeypatch.setattr(q, "_redis_client", None)
    with patch("redis.from_url", side_effect=RuntimeError("down")):
        assert q._get_redis() is None


def test_get_redis_settings_import_failure(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_TLS_URL", raising=False)
    monkeypatch.setattr(q, "_redis_client", None)
    with patch.dict(sys.modules, {"src.config": None}):
        assert q._get_redis() is None


def test_redis_available():
    with patch.object(q, "_get_redis", return_value=object()):
        assert q.redis_available() is True
    with patch.object(q, "_get_redis", return_value=None):
        assert q.redis_available() is False


def test_queue_backend_normalises_and_falls_back():
    with patch.object(settings, "queue_backend", "DB"):
        assert q._queue_backend() == "db"
    with patch.dict(sys.modules, {"src.config": None}):
        assert q._queue_backend() == "auto"


# =========================================================================== #
# queue.py — enqueue / claim
# =========================================================================== #
async def test_enqueue_redis_success():
    fake = FakeRedis()
    with patch.object(q, "_get_redis", return_value=fake):
        assert await q.enqueue({"task_id": "r1"}) == "redis"
    assert fake.llen(q.QUEUE_KEY) == 1


async def test_enqueue_redis_error_db_fallback():
    broken = MagicMock()
    broken.lpush.side_effect = RuntimeError("down")
    with patch.object(q, "_get_redis", return_value=broken), patch.object(
        settings, "queue_backend", "db"
    ), patch.object(q, "_enqueue_db", AsyncMock(return_value="db")):
        assert await q.enqueue({"task_id": "r2"}) == "db"


async def test_enqueue_redis_error_auto_returns_empty():
    broken = MagicMock()
    broken.lpush.side_effect = RuntimeError("down")
    with patch.object(q, "_get_redis", return_value=broken), patch.object(
        settings, "queue_backend", "auto"
    ):
        assert await q.enqueue({"task_id": "r3"}) == ""


async def test_enqueue_db_exception_returns_empty():
    with patch.object(q, "_get_redis", return_value=None), patch.object(
        settings, "queue_backend", "db"
    ), patch("src.database.async_session_maker", side_effect=RuntimeError("db down")):
        assert await q.enqueue({"task_id": "r4"}) == ""


async def test_enqueue_db_success(maker):
    from src.models import GenerationJob

    with patch.object(q, "_get_redis", return_value=None), patch.object(
        settings, "queue_backend", "db"
    ):
        backend = await q.enqueue(
            {"task_id": "edb", "task_uuid": "u", "series_id": "s",
             "task_dir": "/tmp", "request": {"title": "x"}}
        )
    assert backend == "db"
    async with maker() as session:
        row = await session.get(GenerationJob, "edb")
        assert row.status == "pending"
        assert json.loads(row.request_json) == {"title": "x"}


async def test_claim_next_job_redis_success():
    fake = FakeRedis()
    fake.lpush(q.QUEUE_KEY, json.dumps({"task_id": "rj", "request": {"a": 1}}))
    with patch.object(q, "_get_redis", return_value=fake):
        job = await q.claim_next_job(timeout=0)
    assert job == {"task_id": "rj", "request": {"a": 1}}


async def test_claim_next_job_redis_empty_returns_none():
    with patch.object(q, "_get_redis", return_value=FakeRedis()):
        assert await q.claim_next_job(timeout=0) is None


async def test_claim_next_job_redis_error_falls_to_db():
    broken = MagicMock()
    broken.brpop.side_effect = RuntimeError("down")
    with patch.object(q, "_get_redis", return_value=broken), patch.object(
        q, "_claim_db_job", AsyncMock(return_value=None)
    ) as claim_db:
        assert await q.claim_next_job(timeout=0) is None
    claim_db.assert_awaited_once()


async def test_claim_db_job_success(maker):
    await _add_job(maker, id="db1", request_json='{"title": "hi"}')
    job = await q.claim_next_job(timeout=0)
    assert job["task_id"] == "db1"
    assert job["backend"] == "db"
    assert job["request"] == {"title": "hi"}
    assert await q.queue_depth() == 0


async def test_claim_db_job_empty_returns_none(maker):
    assert await q.claim_next_job(timeout=0) is None


async def test_claim_db_job_bad_request_json(maker):
    await _add_job(maker, id="db2", request_json="not-json")
    job = await q.claim_next_job(timeout=0)
    assert job["request"] == {}


async def test_claim_db_job_exception_returns_none():
    with patch.object(q, "_get_redis", return_value=None), patch(
        "src.database.async_session_maker", side_effect=RuntimeError("db down")
    ):
        assert await q.claim_next_job(timeout=0) is None


# =========================================================================== #
# queue.py — job status / progress
# =========================================================================== #
async def test_mark_job_success_and_missing(maker):
    from src.models import GenerationJob

    await _add_job(maker, id="m1")
    await q.mark_job("m1", "completed", "done")
    async with maker() as session:
        row = await session.get(GenerationJob, "m1")
        assert row.status == "completed"
        assert row.error == "done"
        assert row.ended_at is not None
    await q.mark_job("missing", "failed")  # no-op


async def test_mark_job_exception_swallowed():
    with patch("src.database.async_session_maker", side_effect=RuntimeError("db down")):
        await q.mark_job("m2", "failed")


async def test_update_job_progress_success_and_missing(maker):
    from src.models import GenerationJob

    await _add_job(maker, id="pg1")
    await q.update_job_progress("pg1", progress=0.25, current_step=3, message="step")
    async with maker() as session:
        row = await session.get(GenerationJob, "pg1")
        assert row.progress == 0.25
        assert row.current_step == 3
        assert row.message == "step"
    await q.update_job_progress("missing", progress=1.0)


async def test_update_job_progress_exception_swallowed():
    with patch("src.database.async_session_maker", side_effect=RuntimeError("db down")):
        await q.update_job_progress("pg2", progress=0.1)


async def test_request_cancel_pending_and_missing(maker):
    from src.models import GenerationJob

    await _add_job(maker, id="c1", status="pending")
    assert await q.request_cancel("c1") is True
    async with maker() as session:
        row = await session.get(GenerationJob, "c1")
        assert row.cancel_requested is True
        assert row.status == "cancelled"
    assert await q.request_cancel("missing") is False


async def test_request_cancel_exception_returns_false():
    with patch("src.database.async_session_maker", side_effect=RuntimeError("db down")):
        assert await q.request_cancel("c2") is False


async def test_is_cancel_requested_true_false_and_error(maker):
    await _add_job(maker, id="ic1", cancel_requested=True)
    await _add_job(maker, id="ic2", cancel_requested=False)
    assert await q.is_cancel_requested("ic1") is True
    assert await q.is_cancel_requested("ic2") is False
    assert await q.is_cancel_requested("missing") is False
    with patch("src.database.async_session_maker", side_effect=RuntimeError("db down")):
        assert await q.is_cancel_requested("ic3") is False


# =========================================================================== #
# queue.py — publish jobs
# =========================================================================== #
async def test_enqueue_publish_jobs_success(maker):
    jobs = [
        {"id": "pub1", "task_id": "t1", "platform": "youtube"},
        {"id": "pub2", "task_id": "t2", "platform": "douyin"},
    ]
    assert await q.enqueue_publish_jobs(jobs) == 2
    assert await q.publish_queue_depth() == 2


async def test_enqueue_publish_jobs_exception_returns_zero():
    with patch("src.database.async_session_maker", side_effect=RuntimeError("db down")):
        assert await q.enqueue_publish_jobs([{"id": "x", "task_id": "t", "platform": "y"}]) == 0


async def test_claim_next_publish_job_success(maker):
    await _add_publish_job(maker, id="cp1", tags_json=json.dumps(["a", "b"]))
    job = await q.claim_next_publish_job()
    assert job["id"] == "cp1"
    assert job["tags"] == ["a", "b"]
    assert job["attempts"] == 1


async def test_claim_next_publish_job_empty_returns_none(maker):
    assert await q.claim_next_publish_job() is None


async def test_claim_next_publish_job_bad_tags_returns_none(maker):
    await _add_publish_job(maker, id="cp2", tags_json="not-json")
    assert await q.claim_next_publish_job() is None


async def test_claim_next_publish_job_exception_returns_none():
    with patch("src.database.async_session_maker", side_effect=RuntimeError("db down")):
        assert await q.claim_next_publish_job() is None


async def test_mark_publish_job_success_with_error_and_missing(maker):
    from src.models import PublishJob

    await _add_publish_job(maker, id="mp1")
    await q.mark_publish_job("mp1", "failed", error="boom")
    async with maker() as session:
        row = await session.get(PublishJob, "mp1")
        assert row.status == "failed"
        assert row.error == "boom"
    await q.mark_publish_job("missing", "completed")


async def test_mark_publish_job_records_post_fields(maker):
    from src.models import PublishJob

    await _add_publish_job(maker, id="mp3")
    await q.mark_publish_job("mp3", "completed", post_url="http://p", post_id="pid")
    async with maker() as session:
        row = await session.get(PublishJob, "mp3")
        assert row.post_url == "http://p"
        assert row.post_id == "pid"


async def test_mark_publish_job_exception_swallowed():
    with patch("src.database.async_session_maker", side_effect=RuntimeError("db down")):
        await q.mark_publish_job("mp2", "failed")


async def test_retry_publish_job_success_and_missing(maker):
    from src.models import PublishJob

    await _add_publish_job(maker, id="rp1", status="completed")
    assert await q.retry_publish_job("rp1") is True
    async with maker() as session:
        row = await session.get(PublishJob, "rp1")
        assert row.status == "pending"
    assert await q.retry_publish_job("missing") is False


async def test_retry_publish_job_exception_returns_false():
    with patch("src.database.async_session_maker", side_effect=RuntimeError("db down")):
        assert await q.retry_publish_job("rp2") is False


async def test_publish_queue_depth_exception_returns_zero():
    with patch("src.database.async_session_maker", side_effect=RuntimeError("db down")):
        assert await q.publish_queue_depth() == 0


# =========================================================================== #
# queue.py — queue_depth
# =========================================================================== #
async def test_queue_depth_redis():
    fake = FakeRedis()
    fake.lpush(q.QUEUE_KEY, "x")
    with patch.object(q, "_get_redis", return_value=fake):
        assert await q.queue_depth() == 1


async def test_queue_depth_redis_error_falls_to_db(maker):
    broken = MagicMock()
    broken.llen.side_effect = RuntimeError("down")
    with patch.object(q, "_get_redis", return_value=broken):
        assert await q.queue_depth() == 0


async def test_queue_depth_db_success(maker):
    await _add_job(maker, id="qd1")
    with patch.object(q, "_get_redis", return_value=None):
        assert await q.queue_depth() == 1


async def test_queue_depth_db_exception_returns_zero():
    with patch.object(q, "_get_redis", return_value=None), patch(
        "src.database.async_session_maker", side_effect=RuntimeError("db down")
    ):
        assert await q.queue_depth() == 0


# =========================================================================== #
# worker.py — _sync_progress
# =========================================================================== #
async def test_sync_progress_reads_status_file(tmp_path):
    (tmp_path / "status.json").write_text(
        json.dumps({"progress": 0.5, "current_step": 2, "message": "m"}),
        encoding="utf-8",
    )
    stop = asyncio.Event()
    upd = AsyncMock()
    with patch.object(worker_mod, "update_job_progress", upd):
        task = asyncio.create_task(worker_mod._sync_progress("t1", tmp_path, stop))
        for _ in range(100):
            if upd.await_count:
                break
            await asyncio.sleep(0.01)
        stop.set()
        await task
    assert upd.await_args.kwargs == {"progress": 0.5, "current_step": 2, "message": "m"}


async def test_sync_progress_handles_bad_json(tmp_path):
    (tmp_path / "status.json").write_text("{bad", encoding="utf-8")
    stop = asyncio.Event()
    upd = AsyncMock()
    with patch.object(worker_mod, "update_job_progress", upd):
        task = asyncio.create_task(worker_mod._sync_progress("t2", tmp_path, stop))
        await asyncio.sleep(0.05)
        stop.set()
        await task
    upd.assert_not_awaited()


async def test_sync_progress_timeout_branch(tmp_path):
    stop = asyncio.Event()
    calls = {"n": 0}

    async def fake_wait_for(awaitable, timeout):
        calls["n"] += 1
        awaitable.close()
        stop.set()
        raise TimeoutError

    with patch.object(worker_mod, "update_job_progress", AsyncMock()), patch.object(
        worker_mod.asyncio, "wait_for", fake_wait_for
    ):
        await worker_mod._sync_progress("t3", tmp_path, stop)
    assert calls["n"] == 1


# =========================================================================== #
# worker.py — _handle_job
# =========================================================================== #
async def _run_handle(job, run_impl, *, cancel=False, mark=None, depth=0):
    mark = mark or AsyncMock()
    with patch.object(worker_mod, "run_video_generation", run_impl), patch.object(
        worker_mod, "_sync_progress", AsyncMock()
    ), patch.object(worker_mod, "mark_job", mark), patch.object(
        worker_mod, "is_cancel_requested", AsyncMock(return_value=cancel)
    ), patch.object(worker_mod, "queue_depth", AsyncMock(return_value=depth)):
        await worker_mod._handle_job(job)
    return mark


async def test_handle_job_invalid_payload_marks_failed():
    mark = await _run_handle(
        {"task_id": "bad1", "task_dir": "/tmp/bad1", "request": {}, "backend": "db"},
        MagicMock(),
    )
    mark.assert_awaited_with("bad1", "failed", mark.await_args.args[2])
    assert "Invalid job payload" in mark.await_args.args[2]


async def test_handle_job_uses_task_uuid_when_no_task_dir():
    captured = {}

    def fake_run(tid, req, task_dir):
        captured["task_dir"] = task_dir
        video_tasks[tid] = {"id": tid, "status": "completed"}

    await _run_handle(
        {"task_id": "u1", "task_uuid": "uuid-1", "request": {"title": "t", "content": "c"},
         "backend": "redis"},
        fake_run,
    )
    assert captured["task_dir"] == settings.output_dir / "uuid-1"
    video_tasks.pop("u1", None)


async def test_handle_job_records_series_id():
    def fake_run(tid, req, task_dir):
        video_tasks.setdefault(tid, {"id": tid})["status"] = "completed"

    mark = await _run_handle(
        {"task_id": "s1", "task_dir": "/tmp/s1", "series_id": "ser1",
         "request": {"title": "t", "content": "c"}, "backend": "redis"},
        fake_run,
    )
    assert video_tasks["s1"]["series_id"] == "ser1"
    mark.assert_not_awaited()
    video_tasks.pop("s1", None)


async def test_handle_job_cancelled_before_start():
    run = MagicMock()
    mark = await _run_handle(
        {"task_id": "cx1", "task_dir": "/tmp/cx1",
         "request": {"title": "t", "content": "c"}, "backend": "db"},
        run,
        cancel=True,
    )
    mark.assert_awaited_with("cx1", "cancelled", "任务已取消")
    run.assert_not_called()
    assert video_tasks["cx1"]["status"] == "cancelled"
    video_tasks.pop("cx1", None)


async def test_handle_job_completed_marks_completed():
    def fake_run(tid, req, task_dir):
        video_tasks[tid] = {"id": tid, "status": "completed"}

    mark = await _run_handle(
        {"task_id": "ok1", "task_dir": "/tmp/ok1",
         "request": {"title": "t", "content": "c"}, "backend": "db"},
        fake_run,
    )
    mark.assert_awaited_with("ok1", "completed", None)
    video_tasks.pop("ok1", None)


async def test_handle_job_unknown_status_marks_failed():
    def fake_run(tid, req, task_dir):
        video_tasks[tid] = {"id": tid, "status": "weird"}

    mark = await _run_handle(
        {"task_id": "uk1", "task_dir": "/tmp/uk1",
         "request": {"title": "t", "content": "c"}, "backend": "db"},
        fake_run,
    )
    mark.assert_awaited_with("uk1", "failed", "Video generation failed")
    video_tasks.pop("uk1", None)


async def test_handle_job_redis_backend_skips_db_marks():
    def fake_run(tid, req, task_dir):
        video_tasks[tid] = {"id": tid, "status": "completed"}

    mark = await _run_handle(
        {"task_id": "rd1", "task_dir": "/tmp/rd1",
         "request": {"title": "t", "content": "c"}, "backend": "redis"},
        fake_run,
    )
    mark.assert_not_awaited()
    video_tasks.pop("rd1", None)


# =========================================================================== #
# worker.py — _execute_publish_job
# =========================================================================== #
async def test_execute_publish_job_video_not_found(tmp_path):
    mark = AsyncMock()
    with patch.object(worker_mod, "mark_publish_job", mark), patch(
        "src.database.async_session_maker", _maker(None)
    ):
        await worker_mod._execute_publish_job(
            {"id": "pj0", "platform": "youtube", "video_path": str(tmp_path / "no.mp4"),
             "task_dir": str(tmp_path), "account_id": "a1"}
        )
    mark.assert_awaited_with("pj0", "failed", error="video file not found")


async def test_execute_publish_job_no_account_id(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    mark = AsyncMock()
    with patch.object(worker_mod, "mark_publish_job", mark):
        await worker_mod._execute_publish_job(
            {"id": "pj1", "platform": "youtube", "video_path": str(video), "account_id": None}
        )
    mark.assert_awaited_with("pj1", "failed", error="no publisher account on job")


async def test_execute_publish_job_account_not_found(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    mark = AsyncMock()
    with patch.object(worker_mod, "mark_publish_job", mark), patch(
        "src.database.async_session_maker", _maker(None)
    ):
        await worker_mod._execute_publish_job(
            {"id": "pj2", "platform": "youtube", "video_path": str(video), "account_id": "a1"}
        )
    mark.assert_awaited_with("pj2", "failed", error="publisher account not found")


async def test_execute_publish_job_falls_back_to_task_dir(tmp_path):
    (tmp_path / "output.mp4").write_bytes(b"x")
    mark = AsyncMock()
    with patch.object(worker_mod, "mark_publish_job", mark):
        await worker_mod._execute_publish_job(
            {"id": "pj3", "platform": "youtube",
             "video_path": str(tmp_path / "gone.mp4"), "task_dir": str(tmp_path),
             "account_id": None}
        )
    # fallback found output.mp4, then stopped on the missing account
    assert mark.await_args.args == ("pj3", "failed")
    assert mark.await_args.kwargs["error"] == "no publisher account on job"


async def test_execute_publish_job_success(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    acc = MagicMock(credentials={"token": "t"}, cookies="c", folder_id="f")
    pub = MagicMock()
    pub.upload = AsyncMock(
        return_value=SimpleNamespace(success=True, post_url="http://post", post_id="pid")
    )
    pub.close_browser = AsyncMock()
    mark = AsyncMock()
    with patch.object(worker_mod, "mark_publish_job", mark), patch(
        "src.database.async_session_maker", _maker(acc)
    ), patch("src.publishers.get_publisher", return_value=pub) as get_pub:
        await worker_mod._execute_publish_job(
            {"id": "pj4", "platform": "youtube", "video_path": str(video),
             "account_id": "a1", "title": None}
        )
    get_pub.assert_called_once()
    mark.assert_awaited_with("pj4", "completed", post_url="http://post", post_id="pid")
    pub.close_browser.assert_awaited_once()


async def test_execute_publish_job_failure(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    acc = MagicMock(credentials=None, cookies="c", folder_id=None)
    pub = MagicMock()
    pub.upload = AsyncMock(
        return_value=SimpleNamespace(success=False, error="nope", post_url=None, post_id=None)
    )
    pub.close_browser = AsyncMock()
    mark = AsyncMock()
    with patch.object(worker_mod, "mark_publish_job", mark), patch(
        "src.database.async_session_maker", _maker(acc)
    ), patch("src.publishers.get_publisher", return_value=pub):
        await worker_mod._execute_publish_job(
            {"id": "pj5", "platform": "youtube", "video_path": str(video), "account_id": "a1"}
        )
    mark.assert_awaited_with("pj5", "failed", error="nope")


async def test_execute_publish_job_close_browser_error_is_swallowed(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    acc = MagicMock(credentials={"token": "t"}, cookies=None, folder_id=None)
    pub = MagicMock()
    pub.upload = AsyncMock(
        return_value=SimpleNamespace(success=True, post_url=None, post_id="pid")
    )
    pub.close_browser = AsyncMock(side_effect=RuntimeError("close failed"))
    mark = AsyncMock()
    with patch.object(worker_mod, "mark_publish_job", mark), patch(
        "src.database.async_session_maker", _maker(acc)
    ), patch("src.publishers.get_publisher", return_value=pub):
        await worker_mod._execute_publish_job(
            {"id": "pj6", "platform": "youtube", "video_path": str(video), "account_id": "a1"}
        )
    mark.assert_awaited_with("pj6", "completed", post_url=None, post_id="pid")


# =========================================================================== #
# worker.py — poll loop / main
# =========================================================================== #
async def test_poll_loop_processes_publish_job_then_exits():
    calls = {"n": 0}

    async def fake_claim(timeout=5):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        raise KeyboardInterrupt

    publish_job = {"id": "pub-1"}
    execute = AsyncMock()
    with patch.object(worker_mod, "init_db", AsyncMock()), patch.object(
        worker_mod, "claim_next_job", fake_claim
    ), patch.object(
        worker_mod, "claim_next_publish_job", AsyncMock(return_value=publish_job)
    ), patch.object(worker_mod, "_execute_publish_job", execute), patch(
        "asyncio.sleep", new_callable=AsyncMock
    ):
        with pytest.raises(KeyboardInterrupt):
            await worker_mod._poll_loop()
    execute.assert_awaited_once_with(publish_job)


async def test_poll_loop_publish_failure_marks_failed():
    calls = {"n": 0}

    async def fake_claim(timeout=5):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        raise KeyboardInterrupt

    execute = AsyncMock(side_effect=RuntimeError("boom"))
    mark = AsyncMock()
    with patch.object(worker_mod, "init_db", AsyncMock()), patch.object(
        worker_mod, "claim_next_job", fake_claim
    ), patch.object(
        worker_mod, "claim_next_publish_job", AsyncMock(return_value={"id": "pub-2"})
    ), patch.object(worker_mod, "_execute_publish_job", execute), patch.object(
        worker_mod, "mark_publish_job", mark
    ), patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(KeyboardInterrupt):
            await worker_mod._poll_loop()
    mark.assert_awaited_once()
    assert mark.await_args.args[0] == "pub-2"


async def test_poll_loop_idle_sleeps_then_exits():
    calls = {"n": 0}

    async def fake_claim(timeout=5):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        raise KeyboardInterrupt

    sleep = AsyncMock()
    with patch.object(worker_mod, "init_db", AsyncMock()), patch.object(
        worker_mod, "claim_next_job", fake_claim
    ), patch.object(
        worker_mod, "claim_next_publish_job", AsyncMock(return_value=None)
    ), patch("asyncio.sleep", sleep):
        with pytest.raises(KeyboardInterrupt):
            await worker_mod._poll_loop()
    sleep.assert_awaited()


def test_main_swallows_keyboard_interrupt():
    with patch.object(worker_mod, "_poll_loop", MagicMock(return_value=None)), patch.object(
        worker_mod.asyncio, "run", side_effect=KeyboardInterrupt
    ):
        worker_mod.main()


def test_module_main_guard_executes():
    import runpy

    calls = []

    def fake_run(coro):
        calls.append(coro)
        coro.close()
        return None

    with patch.object(worker_mod.asyncio, "run", fake_run):
        runpy.run_module("src.worker", run_name="__main__")
    assert len(calls) == 1


# =========================================================================== #
# PixabayService
# =========================================================================== #
class _FakeResponse:
    def __init__(self, json_data=None, content=b"", status_code=200):
        self._json = json_data
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


class _FakeAsyncClient:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None):
        return self._response


async def test_pixabay_no_api_key_returns_empty():
    svc = PixabayService(api_key=None)
    assert await svc.fetch_images(["a"]) == []


async def test_pixabay_fetch_images_success(monkeypatch):
    svc = PixabayService(api_key="key")
    resp = _FakeResponse(
        json_data={
            "totalHits": 1,
            "hits": [
                {"id": 1, "largeImageURL": "http://x/1.jpg"},
                {"id": 2},
            ],
        }
    )
    download = AsyncMock(return_value=Path("/tmp/pixabay_1.jpg"))
    with patch(
        "src.services.material.pixabay_service.httpx.AsyncClient",
        return_value=_FakeAsyncClient(resp),
    ), patch.object(svc, "_download_file", download):
        out = await svc.fetch_images(["a", "b"], count=3)
    assert out == [Path("/tmp/pixabay_1.jpg")]
    download.assert_awaited_once_with("http://x/1.jpg", "pixabay_1.jpg")


async def test_pixabay_non_200_returns_empty():
    svc = PixabayService(api_key="key")
    with patch(
        "src.services.material.pixabay_service.httpx.AsyncClient",
        return_value=_FakeAsyncClient(_FakeResponse(status_code=500)),
    ):
        assert await svc.fetch_images(["a"]) == []


async def test_pixabay_request_exception_returns_empty():
    svc = PixabayService(api_key="key")

    class _BoomClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None):
            raise RuntimeError("network down")

    with patch(
        "src.services.material.pixabay_service.httpx.AsyncClient",
        return_value=_BoomClient(),
    ):
        assert await svc.fetch_images(["a"]) == []


async def test_pixabay_download_file_success(tmp_path, monkeypatch):
    svc = PixabayService(api_key="key")
    monkeypatch.setattr(
        "src.services.material.pixabay_service.tempfile.mkdtemp", lambda: str(tmp_path)
    )
    resp = _FakeResponse(content=b"hello-bytes")
    with patch(
        "src.services.material.pixabay_service.httpx.AsyncClient",
        return_value=_FakeAsyncClient(resp),
    ):
        out = await svc._download_file("http://x/1.jpg", "one.jpg")
    assert out == tmp_path / "one.jpg"
    assert out.read_bytes() == b"hello-bytes"


async def test_pixabay_download_file_failure_returns_none():
    svc = PixabayService(api_key="key")

    class _BoomClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None):
            raise RuntimeError("download failed")

    with patch(
        "src.services.material.pixabay_service.httpx.AsyncClient",
        return_value=_BoomClient(),
    ):
        assert await svc._download_file("http://x/1.jpg", "one.jpg") is None


# =========================================================================== #
# LocalAssetsService
# =========================================================================== #
async def test_local_assets_no_dir_returns_empty():
    svc = LocalAssetsService(assets_dir=None)
    assert await svc.fetch_videos() == []
    assert await svc.fetch_images() == []


async def test_local_assets_missing_subdirs_return_empty(tmp_path):
    svc = LocalAssetsService(assets_dir=tmp_path)
    assert await svc.fetch_videos() == []
    assert await svc.fetch_images() == []


async def test_local_assets_lists_and_slices(tmp_path):
    videos = tmp_path / "videos"
    images = tmp_path / "images"
    videos.mkdir()
    images.mkdir()
    (videos / "a.mp4").write_bytes(b"v")
    (videos / "b.mov").write_bytes(b"v")
    (videos / "c.mp4").write_bytes(b"v")
    (images / "a.jpg").write_bytes(b"i")
    (images / "b.jpeg").write_bytes(b"i")
    (images / "c.png").write_bytes(b"i")
    (images / "ignore.gif").write_bytes(b"i")

    svc = LocalAssetsService(assets_dir=tmp_path)
    found_videos = await svc.fetch_videos(count=2)
    found_images = await svc.fetch_images(count=10)
    assert len(found_videos) == 2
    assert all(p.suffix in {".mp4", ".mov"} for p in found_videos)
    assert {p.suffix for p in found_images} == {".jpg", ".jpeg", ".png"}
    assert len(found_images) == 3
