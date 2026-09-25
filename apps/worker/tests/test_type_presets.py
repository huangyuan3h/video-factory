"""Per-content-type presets (task-S)."""

import json

import pytest

from src.config import DEFAULT_TYPE_PRESETS, Settings, settings
from src.presets import TypePreset, get_type_preset, normalize_type


def test_defaults_are_populated_on_settings():
    assert set(DEFAULT_TYPE_PRESETS) == {"general", "news", "book", "indicator"}
    for name in DEFAULT_TYPE_PRESETS:
        assert name in settings.type_presets


def test_general_preset_values():
    preset = get_type_preset("general")
    assert preset.voice == "zh-CN-XiaoxiaoNeural"
    assert preset.tts_rate == "+0%"
    assert preset.sentence_pause_seconds == 0.0
    assert preset.segment_pause_seconds == 0.0
    assert preset.image_hold_seconds == 4.0
    assert preset.orientation == "landscape"
    assert preset.footage == "video_first"
    assert preset.proofread is False


def test_book_preset_values():
    preset = get_type_preset("book")
    assert preset.voice == "zh-CN-XiaoxiaoNeural"
    assert preset.tts_rate == "-8%"
    assert preset.sentence_pause_seconds == 0.38
    assert preset.segment_pause_seconds == 0.5
    assert preset.image_hold_seconds == 5.0
    assert preset.proofread is True


def test_indicator_preset_uses_male_voice_and_g2_ready():
    preset = get_type_preset("indicator")
    assert preset.voice == "zh-CN-YunxiNeural"
    assert preset.tts_rate == "-8%"
    assert preset.sentence_pause_seconds == 0.38
    assert preset.proofread is True


def test_unknown_type_falls_back_to_general():
    assert get_type_preset("mystery") == get_type_preset("general")
    assert get_type_preset(None) == get_type_preset("general")
    assert normalize_type("  BOOK ") == "book"


def test_type_merges_over_general_for_missing_fields():
    custom = Settings(type_presets={"book": {"voice": "zh-CN-XiaoyiNeural"}})
    preset = get_type_preset("book", custom)
    assert preset.voice == "zh-CN-XiaoyiNeural"
    # Untouched book fields still come from the book preset, not general.
    assert preset.tts_rate == "-8%"
    assert preset.sentence_pause_seconds == 0.38


def test_book_preset_tracks_legacy_book_settings():
    custom = Settings(
        book_tts_rate="-12%",
        book_segment_pause_seconds=0.9,
        book_image_hold_seconds=7.5,
    )
    preset = get_type_preset("book", custom)
    assert preset.tts_rate == "-12%"
    assert preset.segment_pause_seconds == 0.9
    assert preset.image_hold_seconds == 7.5


def test_type_presets_env_json_override(monkeypatch):
    monkeypatch.setenv(
        "TYPE_PRESETS",
        json.dumps({"indicator": {"voice": "zh-CN-YunyangNeural"}}),
    )
    custom = Settings()
    assert custom.type_presets["indicator"]["voice"] == "zh-CN-YunyangNeural"
    # Unspecified fields keep their defaults.
    assert custom.type_presets["indicator"]["tts_rate"] == "-8%"


def test_env_defined_new_type_inherits_general(monkeypatch):
    monkeypatch.setenv("TYPE_PRESETS", json.dumps({"chart": {"voice": "zh-CN-YunyeNeural"}}))
    custom = Settings()
    preset = get_type_preset("chart", custom)
    assert preset.voice == "zh-CN-YunyeNeural"
    assert preset.tts_rate == "+0%"


def test_explicit_type_presets_beat_legacy_book_settings():
    custom = Settings(
        book_tts_rate="-12%",
        type_presets={"book": {"tts_rate": "-20%"}},
    )
    assert get_type_preset("book", custom).tts_rate == "-20%"


def test_type_preset_is_dataclass():
    assert isinstance(get_type_preset("general"), TypePreset)


# --------------------------------------------------------------------------- #
# Wiring: voice / rate / materials by content type
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_indicator_synthesize_uses_male_preset_voice(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from src.core.task_logger import TaskLogger
    from src.services import video_service as vs

    class _Provider:
        def __init__(self, **kwargs):
            pass

        async def synthesize(self, text, output_path=None, voice=None, boundaries=None):
            if boundaries is not None:
                boundaries.append({"offset": 0.0, "duration": 1.0, "text": text})
            from pathlib import Path

            Path(output_path).write_bytes(b"x")
            return output_path

        async def get_duration(self, audio_path):
            return 3.0

    from src.routes.videos import VideoGenerateRequest

    tl = TaskLogger("indicator-voice", tmp_path)
    engine = MagicMock(return_value=_Provider())
    script = SimpleNamespace(segments=[SimpleNamespace(text="第一句。")])
    # Indicator requests are manifest-driven; a minimal one satisfies validation.
    (tmp_path / "00.png").write_bytes(b"x")
    (tmp_path / "manifest.json").write_text(
        '[{"file": "00.png", "section": "intro", "key_point": "涨了 15%"}]',
        encoding="utf-8",
    )
    # A real request leaves ``voice`` unset, so the indicator preset voice wins.
    request = VideoGenerateRequest(
        type="indicator",
        title="指标",
        custom_visuals_manifest=str(tmp_path),
    )

    with patch.object(vs, "EdgeTTSEngine", engine), patch.object(vs, "_ensure_not_cancelled"):
        await vs._synthesize_audio(script, request, tmp_path, tl)

    assert engine.call_args.kwargs["voice"] == "zh-CN-YunxiNeural"
    assert engine.call_args.kwargs["rate"] == "-8%"


@pytest.mark.asyncio
async def test_indicator_materials_route_through_book_fetcher(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock, patch

    from src.core.task_logger import TaskLogger
    from src.services import video_service as vs

    clip = tmp_path / "v.mp4"
    fetcher = MagicMock()
    fetcher.fetch_videos = AsyncMock(return_value=[clip])
    fetcher.fetch_book_images = AsyncMock()
    ctor = MagicMock(return_value=fetcher)
    request = SimpleNamespace(
        content_type="indicator",
        title="指标",
        resolution_width=1920,
        resolution_height=1080,
        background_source="online",
    )
    script = SimpleNamespace(
        segments=[SimpleNamespace(text="一段", keywords=["gdp"], duration_estimate=20)]
    )
    tl = TaskLogger("indicator-mat", tmp_path)

    with patch.object(vs, "get_general_settings", AsyncMock(return_value={})), patch.object(
        vs, "MaterialFetcher", ctor
    ), patch.object(vs.settings, "assets_dir", tmp_path):
        result = await vs._fetch_materials(script, request, tl)

    assert result == [clip]
    assert ctor.call_args.kwargs["book_mode"] is True
    # indicator preset is video_first, so images are not fetched.
    fetcher.fetch_book_images.assert_not_called()
