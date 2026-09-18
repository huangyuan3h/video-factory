"""Tests for the scheduler pipeline (fetch -> generate -> publish)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src import scheduler as sched
from src.models import Run, Source
from src.services.video_service import video_tasks
from src.sources.base import ContentItem


def test_build_source_rss():
    src = Source(id="1", type="rss", name="Feed", url="http://example.com/rss", keywords='["a","b"]')
    built = sched._build_source(src)
    assert built is not None
    assert built.url == "http://example.com/rss"
    assert built.keywords == ["a", "b"]


def test_build_source_news_requires_key():
    assert sched._build_source(Source(id="2", type="news_api", name="N")) is None
    built = sched._build_source(Source(id="3", type="news_api", name="N", api_key="k"))
    assert built is not None


def test_build_source_hot_topics_platform_detection():
    built = sched._build_source(Source(id="4", type="hot_topics", name="zhihu hot"))
    assert built.platform == "zhihu"
    built2 = sched._build_source(Source(id="5", type="hot_topics", name="weibo"))
    assert built2.platform == "weibo"


def test_build_source_unsupported():
    assert sched._build_source(None) is None
    assert sched._build_source(Source(id="6", type="weird", name="w")) is None


class _FakeResult:
    def __init__(self, task):
        self._task = task

    def scalar_one_or_none(self):
        return self._task


class _FakeSession:
    def __init__(self, store, task):
        self.store = store
        self.task = task

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def execute(self, stmt):
        return _FakeResult(self.task)

    def add(self, obj):
        self.store[obj.id] = obj

    async def commit(self):
        return None

    async def get(self, model, key):
        return self.store.get(key)


class _FakeMaker:
    def __init__(self, task):
        self.store = {}
        self.task = task

    def __call__(self):
        return _FakeSession(self.store, self.task)


@pytest.mark.asyncio
async def test_execute_task_success(monkeypatch, tmp_path):
    task = SimpleNamespace(id="task-1", name="Daily", source=SimpleNamespace(type="rss"))
    maker = _FakeMaker(task)

    fake_source = SimpleNamespace(
        fetch=AsyncMock(return_value=[ContentItem(title="Hello", content="World body")])
    )

    def fake_run(tid, req, task_dir):
        video_tasks[tid] = {
            "id": tid,
            "status": "completed",
            "video_path": str(task_dir / "output.mp4"),
            "task_dir": str(task_dir),
        }

    monkeypatch.setattr(sched.settings, "output_dir", tmp_path)
    monkeypatch.setattr(sched.settings, "scheduler_auto_publish", False)

    with patch.object(sched, "async_session_maker", maker), patch.object(
        sched, "_build_source", return_value=fake_source
    ), patch.object(sched, "run_video_generation", fake_run):
        await sched.execute_task("task-1")

    run = next(iter(maker.store.values()))
    assert isinstance(run, Run)
    assert run.status == "completed"
    assert run.input_content == "World body"
    assert run.video_path is not None
    # cleanup
    for tid in list(video_tasks.keys()):
        if tid == run.id:
            video_tasks.pop(tid, None)


@pytest.mark.asyncio
async def test_execute_task_no_content_fails(monkeypatch, tmp_path):
    task = SimpleNamespace(id="task-2", name="Empty", source=SimpleNamespace(type="rss"))
    maker = _FakeMaker(task)
    fake_source = SimpleNamespace(fetch=AsyncMock(return_value=[]))

    monkeypatch.setattr(sched.settings, "output_dir", tmp_path)
    with patch.object(sched, "async_session_maker", maker), patch.object(
        sched, "_build_source", return_value=fake_source
    ):
        await sched.execute_task("task-2")

    run = next(iter(maker.store.values()))
    assert run.status == "failed"
    assert "no content" in (run.error or "").lower()


@pytest.mark.asyncio
async def test_execute_task_unsupported_source_fails(monkeypatch, tmp_path):
    task = SimpleNamespace(id="task-3", name="Bad", source=None)
    maker = _FakeMaker(task)
    monkeypatch.setattr(sched.settings, "output_dir", tmp_path)
    with patch.object(sched, "async_session_maker", maker), patch.object(
        sched, "_build_source", return_value=None
    ):
        await sched.execute_task("task-3")
    run = next(iter(maker.store.values()))
    assert run.status == "failed"


@pytest.mark.asyncio
async def test_execute_task_missing_task_returns(monkeypatch):
    maker = _FakeMaker(None)
    with patch.object(sched, "async_session_maker", maker):
        await sched.execute_task("nope")
    assert maker.store == {}


@pytest.mark.asyncio
async def test_enabled_platforms_dedup():
    class _Res:
        def scalars(self):
            return self

        def all(self):
            return ["YouTube", "youtube", "", "douyin"]

    class _Sess:
        async def execute(self, stmt):
            return _Res()

    platforms = await sched._enabled_platforms(_Sess())
    assert platforms == ["youtube", "douyin"]
