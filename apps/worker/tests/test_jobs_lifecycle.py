"""Tests for task cancellation, retry, and status enrichment."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import BackgroundTasks

from src.core.task_logger import TaskLogger
from src.routes import videos
from src.services.video_service import GenerationCancelled, _ensure_not_cancelled, video_tasks


def _register(task_id: str, task_dir, status="processing", payload=None):
    video_tasks[task_id] = {
        "id": task_id,
        "status": status,
        "task_dir": str(task_dir),
        "progress": 0.0,
        "payload": payload or {},
    }
    return video_tasks[task_id]


def test_enrich_task_reads_disk_status(tmp_path):
    (tmp_path / "status.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "progress": 1.0,
                "message": "done",
                "current_step": 8,
                "step_name": "complete",
                "files": {"video": str(tmp_path / "output.mp4")},
            }
        ),
        encoding="utf-8",
    )
    task = {"id": "t-enrich", "task_dir": str(tmp_path), "status": "pending", "progress": 0.0}
    enriched = videos._enrich_task(task)
    assert enriched["status"] == "completed"
    assert enriched["progress"] == 1.0
    assert enriched["message"] == "done"
    assert enriched["video_path"] == str(tmp_path / "output.mp4")


@pytest.mark.asyncio
async def test_cancel_processing_writes_flag(tmp_path):
    tid = "cancel-proc"
    _register(tid, tmp_path, status="processing")
    try:
        with patch.object(videos, "queue_request_cancel", AsyncMock(return_value=True)):
            res = await videos.cancel_task(tid)
        assert (tmp_path / "cancel.flag").exists()
        assert res["data"]["status"] == "processing"
        assert video_tasks[tid]["message"] == "正在取消..."
    finally:
        video_tasks.pop(tid, None)


@pytest.mark.asyncio
async def test_cancel_pending_marks_cancelled(tmp_path):
    tid = "cancel-pending"
    _register(tid, tmp_path, status="pending")
    try:
        with patch.object(videos, "queue_request_cancel", AsyncMock(return_value=False)):
            res = await videos.cancel_task(tid)
        assert res["data"]["status"] == "cancelled"
    finally:
        video_tasks.pop(tid, None)


@pytest.mark.asyncio
async def test_cancel_unknown_task():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await videos.cancel_task("nope")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_retry_creates_new_task(monkeypatch, tmp_path):
    tid = "retry-src"
    payload = {"title": "T", "content": "C"}
    _register(tid, tmp_path, status="failed", payload=payload)
    new_id = None
    try:
        monkeypatch.setattr(videos.settings, "output_dir", tmp_path)
        with patch.object(videos, "_get_series", AsyncMock(return_value=None)), patch.object(
            videos, "enqueue", AsyncMock(return_value="")
        ), patch.object(videos, "run_video_generation", AsyncMock()):
            res = await videos.retry_task(tid, BackgroundTasks())
        new_id = res["data"]["id"]
        assert new_id != tid
        assert res["success"] is True
    finally:
        video_tasks.pop(tid, None)
        if new_id:
            video_tasks.pop(new_id, None)


@pytest.mark.asyncio
async def test_retry_without_payload():
    from fastapi import HTTPException

    tid = "retry-nopayload"
    video_tasks[tid] = {"id": tid, "status": "failed", "task_dir": "/tmp", "payload": None}
    try:
        with pytest.raises(HTTPException) as exc:
            await videos.retry_task(tid, BackgroundTasks())
        assert exc.value.status_code == 400
    finally:
        video_tasks.pop(tid, None)


def test_ensure_not_cancelled(tmp_path):
    logger = TaskLogger("cancel-check", tmp_path)
    _ensure_not_cancelled(logger)  # no flag -> no raise
    (tmp_path / "cancel.flag").write_text("x", encoding="utf-8")
    with pytest.raises(GenerationCancelled):
        _ensure_not_cancelled(logger)


def test_task_logger_cancelled_status(tmp_path):
    logger = TaskLogger("cancel-status", tmp_path)
    logger.cancelled("bye")
    assert logger.get_status()["status"] == "cancelled"
