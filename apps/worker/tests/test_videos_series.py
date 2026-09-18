"""Tests for series-aware output layout in the video generate route."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks, HTTPException

from src.routes import videos
from src.routes.videos import VideoGenerateRequest
from src.services.video_service import video_tasks


class _FakeSeries:
    id = "s1"
    name = "健康系列"
    slug = "jiankang"


async def _run_generate(monkeypatch, tmp_path, *, series, folders):
    monkeypatch.setattr(videos.settings, "output_dir", tmp_path)
    monkeypatch.setattr(videos.settings, "series_output_folders", folders)
    req = VideoGenerateRequest(title="t", content="c", series_id=series.id if series else None)
    with patch.object(videos, "_get_series", AsyncMock(return_value=series)), patch.object(
        videos, "enqueue", AsyncMock(return_value="")
    ), patch.object(videos, "run_video_generation", MagicMock()):
        res = await videos.generate_video(req, BackgroundTasks())
    video_tasks.pop(res["data"]["id"], None)
    return res["data"]


@pytest.mark.asyncio
async def test_generate_uses_series_slug_folder(monkeypatch, tmp_path):
    data = await _run_generate(monkeypatch, tmp_path, series=_FakeSeries(), folders=True)
    assert "jiankang" in data["task_dir"]


@pytest.mark.asyncio
async def test_generate_flat_when_disabled(monkeypatch, tmp_path):
    data = await _run_generate(monkeypatch, tmp_path, series=_FakeSeries(), folders=False)
    assert "_unsorted" in data["task_dir"]
    assert "jiankang" not in data["task_dir"]


@pytest.mark.asyncio
async def test_generate_without_series_unsorted(monkeypatch, tmp_path):
    data = await _run_generate(monkeypatch, tmp_path, series=None, folders=True)
    assert "_unsorted" in data["task_dir"]


@pytest.mark.asyncio
async def test_generate_unknown_series_404(monkeypatch, tmp_path):
    monkeypatch.setattr(videos.settings, "output_dir", tmp_path)
    req = VideoGenerateRequest(title="t", content="c", series_id="missing")
    with patch.object(videos, "_get_series", AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc:
            await videos.generate_video(req, BackgroundTasks())
    assert exc.value.status_code == 404


def test_series_id_alias():
    req = VideoGenerateRequest(title="t", content="c", seriesId="abc")
    assert req.series_id == "abc"
