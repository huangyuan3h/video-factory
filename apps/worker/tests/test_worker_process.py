"""Tests for the independent queue worker process."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src import worker as worker_mod
from src.services.video_service import video_tasks


@pytest.mark.asyncio
async def test_handle_job_invalid_payload_marks_failed():
    mark = AsyncMock()
    with patch.object(worker_mod, "mark_job", mark):
        await worker_mod._handle_job(
            {"task_id": "bad1", "task_dir": "/tmp/bad1", "request": {}, "backend": "db"}
        )
    mark.assert_awaited()
    assert mark.await_args.args[0] == "bad1"
    assert mark.await_args.args[1] == "failed"


@pytest.mark.asyncio
async def test_handle_job_success_db_backend(tmp_path):
    task_id = "ok1"
    video_tasks.pop(task_id, None)

    def fake_run(tid, req, task_dir):
        video_tasks[tid] = {"id": tid, "status": "completed", "video_path": "/tmp/out.mp4"}

    mark = AsyncMock()
    with patch.object(worker_mod, "run_video_generation", fake_run), patch.object(
        worker_mod, "mark_job", mark
    ), patch.object(worker_mod, "queue_depth", AsyncMock(return_value=0)):
        await worker_mod._handle_job(
            {
                "task_id": task_id,
                "task_dir": str(tmp_path),
                "request": {"title": "t", "content": "c"},
                "backend": "db",
            }
        )
    mark.assert_awaited_with(task_id, "completed", None)
    video_tasks.pop(task_id, None)


@pytest.mark.asyncio
async def test_handle_job_failure_db_backend(tmp_path):
    task_id = "fail1"
    video_tasks.pop(task_id, None)

    def fake_run(tid, req, task_dir):
        video_tasks[tid] = {"id": tid, "status": "failed", "error": "kaboom"}

    mark = AsyncMock()
    with patch.object(worker_mod, "run_video_generation", fake_run), patch.object(
        worker_mod, "mark_job", mark
    ), patch.object(worker_mod, "queue_depth", AsyncMock(return_value=0)):
        await worker_mod._handle_job(
            {
                "task_id": task_id,
                "task_dir": str(tmp_path),
                "request": {"title": "t", "content": "c"},
                "backend": "db",
            }
        )
    mark.assert_awaited_with(task_id, "failed", "kaboom")
    video_tasks.pop(task_id, None)


@pytest.mark.asyncio
async def test_handle_job_redis_backend_does_not_touch_db(tmp_path):
    task_id = "r1"
    video_tasks.pop(task_id, None)

    def fake_run(tid, req, task_dir):
        video_tasks[tid] = {"id": tid, "status": "completed"}

    mark = AsyncMock()
    with patch.object(worker_mod, "run_video_generation", fake_run), patch.object(
        worker_mod, "mark_job", mark
    ), patch.object(worker_mod, "queue_depth", AsyncMock(return_value=0)):
        await worker_mod._handle_job(
            {
                "task_id": task_id,
                "task_dir": str(tmp_path),
                "request": {"title": "t", "content": "c"},
                "backend": "redis",
            }
        )
    mark.assert_not_awaited()
    video_tasks.pop(task_id, None)


@pytest.mark.asyncio
async def test_handle_job_cancelled_before_start(tmp_path):
    task_id = "cancel-1"
    video_tasks.pop(task_id, None)
    mark = AsyncMock()
    run = MagicMock()
    with patch.object(worker_mod, "is_cancel_requested", AsyncMock(return_value=True)), patch.object(
        worker_mod, "mark_job", mark
    ), patch.object(worker_mod, "run_video_generation", run), patch.object(
        worker_mod, "queue_depth", AsyncMock(return_value=0)
    ):
        await worker_mod._handle_job(
            {
                "task_id": task_id,
                "task_dir": str(tmp_path),
                "request": {"title": "t", "content": "c"},
                "backend": "db",
            }
        )
    mark.assert_awaited_with(task_id, "cancelled", "任务已取消")
    run.assert_not_called()
    video_tasks.pop(task_id, None)
