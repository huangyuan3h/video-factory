"""Tests for the review + publish pipeline (M5)."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.database import Base
from src import models  # noqa: F401
from src.models import PublisherAccount, SeriesPublishTarget
from src.publishers.base import PublishResult
from src.routes import publishing as pub_routes
from src.routes import series as series_routes
from src.routes import videos
from src.services.video_service import video_tasks
from src import worker as worker_mod


@pytest_asyncio.fixture
async def maker():
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    with patch("src.database.async_session_maker", session_maker):
        yield session_maker
    await engine.dispose()


def _completed_task(tmp_path, task_id="v1", series_id=None, approved=False):
    (tmp_path / "output.mp4").write_bytes(b"data")
    status = {
        "status": "completed",
        "progress": 1.0,
        "message": "done",
        "current_step": 8,
        "step_name": "complete",
        "files": {"video": str(tmp_path / "output.mp4")},
        "series_id": series_id,
        "review_status": "approved" if approved else "draft",
    }
    (tmp_path / "status.json").write_text(json.dumps(status), encoding="utf-8")
    video_tasks[task_id] = {
        "id": task_id,
        "status": "pending",
        "series_id": series_id,
        "task_dir": str(tmp_path),
        "request": {"title": "My Video"},
        "payload": {},
    }
    return task_id


@pytest.mark.asyncio
async def test_review_approves_completed(tmp_path):
    tid = _completed_task(tmp_path, "rev-ok")
    try:
        res = await videos.review_task(tid, videos.ReviewRequest(decision="approve"))
        assert res["data"]["review_status"] == "approved"
        assert json.loads((tmp_path / "status.json").read_text())["review_status"] == "approved"
    finally:
        video_tasks.pop(tid, None)


@pytest.mark.asyncio
async def test_review_rejects_unfinished(tmp_path):
    from fastapi import HTTPException

    tid = "rev-unfinished"
    video_tasks[tid] = {"id": tid, "status": "processing", "task_dir": str(tmp_path)}
    try:
        with pytest.raises(HTTPException) as exc:
            await videos.review_task(tid, videos.ReviewRequest(decision="approve"))
        assert exc.value.status_code == 400
    finally:
        video_tasks.pop(tid, None)


@pytest.mark.asyncio
async def test_publish_requires_approval(tmp_path):
    from fastapi import HTTPException

    tid = _completed_task(tmp_path, "pub-unapproved")
    try:
        with pytest.raises(HTTPException) as exc:
            await videos.publish_task(tid, videos.PublishTaskRequest(platforms=["youtube"]))
        assert exc.value.status_code == 400
    finally:
        video_tasks.pop(tid, None)


@pytest.mark.asyncio
async def test_publish_queues_for_platform(maker, tmp_path):
    tid = _completed_task(tmp_path, "pub-ok", approved=True)
    try:
        async with maker() as session:
            session.add(PublisherAccount(id="acct1", platform="youtube", name="YT", enabled=True))
            await session.commit()
        res = await videos.publish_task(tid, videos.PublishTaskRequest(platforms=["youtube"]))
        assert res["data"]["queued"] == 1
        jobs = await videos.list_task_publish_jobs(tid)
        assert len(jobs["data"]) == 1
        assert jobs["data"][0]["platform"] == "youtube"
    finally:
        video_tasks.pop(tid, None)


@pytest.mark.asyncio
async def test_publish_no_targets(maker, tmp_path):
    from fastapi import HTTPException

    tid = _completed_task(tmp_path, "pub-notarget", approved=True)
    try:
        with pytest.raises(HTTPException) as exc:
            await videos.publish_task(tid, videos.PublishTaskRequest(platforms=["youtube"]))
        assert exc.value.status_code == 400
    finally:
        video_tasks.pop(tid, None)


class _FakeSeriesSession:
    def __init__(self, series=None):
        self.series = series
        self.targets: list = []

    async def get(self, model, key):
        if model is series_routes.Series:
            return self.series
        for target in self.targets:
            if getattr(target, "id", None) == key:
                return target
        return None

    async def execute(self, stmt):
        class _R:
            def __init__(self, rows):
                self._rows = rows

            def scalars(self):
                return self

            def all(self):
                return self._rows

        return _R(self.targets)

    def add(self, obj):
        self.targets.append(obj)

    async def commit(self):
        return None

    async def refresh(self, obj):
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now()

    async def delete(self, obj):
        self.targets.remove(obj)


@pytest.mark.asyncio
async def test_series_target_crud():
    series = MagicMock()
    series.id = "s1"
    session = _FakeSeriesSession(series)
    created = await series_routes.create_target(
        "s1", series_routes.TargetCreate(platform="youtube", account_id="a1"), session
    )
    assert created["data"]["platform"] == "youtube"
    listed = await series_routes.list_targets("s1", session)
    assert len(listed["data"]) == 1
    target_id = created["data"]["id"]
    deleted = await series_routes.delete_target("s1", target_id, session)
    assert deleted["success"] is True


@pytest.mark.asyncio
async def test_series_publish_approved(maker, tmp_path):
    async with maker() as session:
        session.add(PublisherAccount(id="acct2", platform="youtube", name="YT", enabled=True))
        await session.commit()
    tid = _completed_task(tmp_path, "series-pub", series_id="s9", approved=True)
    session = _FakeSeriesSession()
    session.series = MagicMock(id="s9")
    session.targets = [SeriesPublishTarget(id="t1", series_id="s9", platform="youtube", account_id="acct2", enabled=True)]
    try:
        res = await series_routes.publish_approved("s9", session)
        assert res["data"]["videos"] == 1
        assert res["data"]["queued"] == 1
    finally:
        video_tasks.pop(tid, None)


@pytest.mark.asyncio
async def test_worker_execute_publish_job(maker, tmp_path):
    async with maker() as session:
        session.add(PublisherAccount(id="acct3", platform="youtube", name="YT", enabled=True))
        await session.commit()
    video = tmp_path / "output.mp4"
    video.write_bytes(b"data")
    fake_pub = MagicMock()
    fake_pub.upload = AsyncMock(return_value=PublishResult(success=True, platform="YouTube", post_id="pid"))
    fake_pub.close_browser = AsyncMock()
    mark = AsyncMock()
    with patch("src.publishers.get_publisher", return_value=fake_pub), patch.object(
        worker_mod, "mark_publish_job", mark
    ):
        await worker_mod._execute_publish_job(
            {
                "id": "job1",
                "task_id": "t1",
                "platform": "youtube",
                "account_id": "acct3",
                "video_path": str(video),
                "task_dir": str(tmp_path),
                "title": "T",
                "tags": [],
            }
        )
    mark.assert_awaited_with("job1", "completed", post_url=None, post_id="pid")


@pytest.mark.asyncio
async def test_worker_execute_publish_job_missing_video(maker):
    mark = AsyncMock()
    with patch.object(worker_mod, "mark_publish_job", mark):
        await worker_mod._execute_publish_job(
            {"id": "job2", "task_id": "t2", "platform": "youtube", "account_id": "a", "video_path": "/nope.mp4", "task_dir": "/nope"}
        )
    assert mark.await_args.args[1] == "failed"


@pytest.mark.asyncio
async def test_publishing_routes_list_and_retry(maker):
    from src import queue as q

    await q.enqueue_publish_jobs(
        [{"id": "jobx", "task_id": "t", "platform": "youtube", "account_id": "a"}]
    )
    async with maker() as session:
        listed = await pub_routes.list_publish_jobs(status="pending", session=session)
    assert listed["data"][0]["id"] == "jobx"

    retried = await pub_routes.retry_job("jobx")
    assert retried["success"] is True
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        await pub_routes.retry_job("missing")
