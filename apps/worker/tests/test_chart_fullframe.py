"""Tests for the full-frame chart layout (brief L1).

The full-frame ("fullframe") layout makes the whole 1920x1080 frame light: the
chart is contained above a subtitle band and side/band margins use the chart's
own background colour (sampled from its border), never black. The old dark
layout remains available as "letterbox".
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from moviepy import ImageClip

from src.config import Settings, settings
from src.core.subtitle_gen import Subtitle
from src.core.task_logger import TaskLogger
from src.presets import get_type_preset
from src.services import compose_service as cs
from src.services import video_service as vs
from tests.test_compose_cover_unit import patch_moviepy

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _logger(task_id, task_dir):
    return TaskLogger(task_id, task_dir)


def _solid_image(width, height, color):
    return np.full((height, width, 3), color, dtype=np.uint8)


def _chart_with_red_rect(width=1920, height=950, bg=255):
    img = np.full((height, width, 3), bg, dtype=np.uint8)
    img[300:650, 640:1280] = (200, 0, 0)
    return img


# --------------------------------------------------------------------------- #
# 1. Presets
# --------------------------------------------------------------------------- #


def test_indicator_defaults_to_fullframe_others_letterbox():
    assert get_type_preset("indicator").chart_layout == "fullframe"
    assert get_type_preset("general").chart_layout == "letterbox"
    assert get_type_preset("book").chart_layout == "letterbox"
    assert get_type_preset("news").chart_layout == "letterbox"


def test_type_presets_env_override_chart_layout(monkeypatch):
    monkeypatch.setenv("TYPE_PRESETS", '{"indicator": {"chart_layout": "letterbox"}}')
    custom = Settings()
    assert custom.type_presets["indicator"]["chart_layout"] == "letterbox"
    assert get_type_preset("indicator", custom).chart_layout == "letterbox"


# --------------------------------------------------------------------------- #
# 2. Band height
# --------------------------------------------------------------------------- #


def test_fullframe_band_height_scales_with_resolution():
    assert cs._fullframe_band_height((1920, 1080)) == 130
    assert cs._fullframe_band_height((1280, 720)) == 87


# --------------------------------------------------------------------------- #
# 3/4/5. _fit_fullframe
# --------------------------------------------------------------------------- #


def test_fit_fullframe_1920x950_fills_width_and_band():
    clip = ImageClip(_chart_with_red_rect(), duration=1.0)
    fitted = cs._fit_fullframe(clip, (1920, 1080))
    frame = fitted.get_frame(0)
    assert frame.shape[:2] == (1080, 1920)

    # Top-left, top-right and bottom-left of the 1920x950 chart box are the
    # image's white, i.e. the chart fills the full width edge-to-edge.
    assert tuple(frame[0, 0]) == (255, 255, 255)
    assert tuple(frame[0, 1919]) == (255, 255, 255)
    assert tuple(frame[949, 0]) == (255, 255, 255)
    # The whole band below row 950 is the canvas (white here).
    assert np.all(frame[950:1080] == 255)

    # No black bars anywhere outside the red rectangle.
    mask = np.ones(frame.shape[:2], bool)
    mask[300:650, 640:1280] = False
    outside = frame[mask].reshape(-1, 3).astype(int)
    assert outside.mean(axis=1).min() >= 128


def test_fit_fullframe_16x9_uses_image_bg_for_margins_and_band():
    clip = ImageClip(_solid_image(1920, 1080, (247, 249, 252)), duration=1.0)
    fitted = cs._fit_fullframe(clip, (1920, 1080))
    frame = fitted.get_frame(0)

    margin = frame[500, 10]
    band = frame[1000, 960]
    assert np.all(np.abs(margin.astype(int) - np.array([247, 249, 252])) <= 2)
    assert np.all(np.abs(band.astype(int) - np.array([247, 249, 252])) <= 2)


def test_fit_fullframe_dark_image_falls_back_to_canvas():
    clip = ImageClip(_solid_image(1920, 1080, (22, 24, 28)), duration=1.0)
    fitted = cs._fit_fullframe(clip, (1920, 1080))
    frame = fitted.get_frame(0)

    assert tuple(frame[500, 10]) == cs._canvas_color()
    assert cs._canvas_color() == (255, 255, 255)


def test_fit_fullframe_bad_source_returns_plain_canvas():
    clip = SimpleNamespace(w=0, h=0)
    fitted = cs._fit_fullframe(clip, (64, 36))
    assert fitted.get_frame(0).shape[:2] == (36, 64)


# --------------------------------------------------------------------------- #
# 6. Subtitle track
# --------------------------------------------------------------------------- #


def test_subtitle_track_fullframe_dark_no_stroke(tmp_path, monkeypatch):
    logger = _logger("ff-subs", tmp_path)
    monkeypatch.setattr(cs, "FONT_PATHS", ["/no/such/font.ttf"])
    subtitles = [Subtitle(1, 1.0, 2.0, "图表字幕")]

    with patch_moviepy() as mocks:
        clips = cs._create_subtitle_track(
            subtitles, (1920, 1080), logger, chart_layout="fullframe"
        )

    assert len(clips) == 1
    kwargs = mocks["TextClip"].call_args.kwargs
    assert kwargs["color"] == settings.chart_subtitle_dark_color
    assert kwargs["stroke_color"] is None
    assert kwargs["stroke_width"] == 0

    font_size = cs._subtitle_font_size((1920, 1080), True)
    assert kwargs["font_size"] == font_size
    band = cs._fullframe_band_height((1920, 1080))
    assert clips[0].position == ("center", 1080 - band / 2 - font_size / 2)
    assert 1080 - band <= clips[0].position[1] < 1080


# --------------------------------------------------------------------------- #
# 7. Video track
# --------------------------------------------------------------------------- #


def test_create_video_track_fullframe_returns_base_colorclip_first(tmp_path):
    logger = _logger("ff-video", tmp_path)
    a = tmp_path / "a.png"

    with patch_moviepy() as mocks:
        clips = cs._create_video_track(
            [],
            (1920, 1080),
            6.0,
            logger,
            segment_audios=[{"index": 0, "duration": 6.0, "offset": 0.0}],
            materials_per_segment=[[a]],
            segment_visual_specs=[
                {"fit": "contain", "motion": "none", "hold_seconds": None}
            ],
            chart_layout="fullframe",
        )

    assert mocks["ColorClip"].call_count >= 1
    # The opaque base colour clip comes first and spans the whole timeline.
    assert clips[0].start == 0.0
    assert clips[0].duration == 6.0


def test_create_video_track_letterbox_has_no_base_clip(tmp_path):
    logger = _logger("lb-video", tmp_path)
    a = tmp_path / "a.png"

    with patch_moviepy():
        clips = cs._create_video_track(
            [],
            (1920, 1080),
            6.0,
            logger,
            segment_audios=[{"index": 0, "duration": 6.0, "offset": 0.0}],
            materials_per_segment=[[a]],
            segment_visual_specs=[
                {"fit": "contain", "motion": "none", "hold_seconds": None}
            ],
        )

    # Only the segment clip; no extra full-duration base.
    assert len(clips) == 1
    assert clips[0].duration == pytest.approx(6.0)


# --------------------------------------------------------------------------- #
# 8. Wiring
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_compose_video_forwards_chart_layout(tmp_path):
    logger = _logger("ff-forward", tmp_path)
    expected = tmp_path / "output.mp4"

    with patch.object(cs, "_compose_video_sync", return_value=expected) as mock_sync:
        result = await cs.compose_video(
            tmp_path,
            logger,
            [],
            [],
            [],
            None,
            1.0,
            (1920, 1080),
            chart_layout="fullframe",
        )

    assert result == expected
    call = mock_sync.call_args
    assert "fullframe" in call.args or call.kwargs.get("chart_layout") == "fullframe"


@pytest.mark.asyncio
async def test_compose_final_video_indicator_passes_fullframe(tmp_path):
    logger = _logger("ff-final", tmp_path)
    out = tmp_path / "out.mp4"
    request = SimpleNamespace(
        content_type="indicator",
        resolution_width=1920,
        resolution_height=1080,
        fps=30,
        cover_image=None,
        background_music=None,
    )

    with patch.object(
        vs, "_resolve_bg_music_path", MagicMock(return_value=None)
    ), patch.object(vs, "compose_video", AsyncMock(return_value=out)) as comp:
        result = await vs._compose_final_video(request, tmp_path, logger, [], [], [], 5.0)

    assert result == out
    assert comp.await_args.kwargs["chart_layout"] == "fullframe"


@pytest.mark.asyncio
async def test_compose_final_video_general_passes_letterbox(tmp_path):
    logger = _logger("lb-final", tmp_path)
    out = tmp_path / "out.mp4"
    request = SimpleNamespace(
        content_type="general",
        resolution_width=1920,
        resolution_height=1080,
        fps=30,
        cover_image=None,
        background_music=None,
    )

    with patch.object(
        vs, "_resolve_bg_music_path", MagicMock(return_value=None)
    ), patch.object(vs, "compose_video", AsyncMock(return_value=out)) as comp:
        await vs._compose_final_video(request, tmp_path, logger, [], [], [], 5.0)

    assert comp.await_args.kwargs["chart_layout"] == "letterbox"
