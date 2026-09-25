"""Segment-aware subtitle timing (drift fix) and edge-tts boundary capture."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.core.subtitle_gen import Subtitle, SubtitleGenerator
from src.core.task_logger import TaskLogger
from src.services import video_service as vs


def _build_segments(count: int, total: float) -> list[dict]:
    """Uneven text lengths + uneven durations summing to ``total``."""
    weights = [1.0 + i for i in range(count)]
    weight_sum = sum(weights)
    segments = []
    offset = 0.0
    for i, weight in enumerate(weights):
        duration = total * weight / weight_sum
        text = "句子" + ("很长" * (i % 3 + 1)) + "。" + "短句。"
        segments.append({"text": text, "duration": duration, "offset": offset})
        offset += duration
    return segments


def _assert_within_own_segment(subtitles: list[Subtitle], segments: list[dict]) -> None:
    seg_index = 0
    for sub in subtitles:
        while (
            seg_index + 1 < len(segments)
            and sub.start_time >= segments[seg_index + 1]["offset"] - 1e-6
        ):
            seg_index += 1
        assert seg_index < len(segments)
        seg = segments[seg_index]
        assert sub.start_time >= seg["offset"] - 1e-6
        assert sub.end_time <= seg["offset"] + seg["duration"] + 1e-6


# --------------------------------------------------------------------------- #
# generate_for_segments — fallback (text) path
# --------------------------------------------------------------------------- #


def test_fallback_last_end_matches_total_and_stays_in_segments():
    gen = SubtitleGenerator()
    total = 256.4
    segments = _build_segments(10, total)

    subtitles = gen.generate_for_segments(segments)

    assert subtitles
    assert abs(subtitles[-1].end_time - total) < 0.3
    _assert_within_own_segment(subtitles, segments)

    starts = [sub.start_time for sub in subtitles]
    assert starts == sorted(starts)
    for current, following in zip(subtitles, subtitles[1:]):
        assert current.end_time <= following.start_time + 1e-6


def test_fallback_every_segment_has_its_own_lines():
    gen = SubtitleGenerator()
    segments = _build_segments(10, 100.0)

    subtitles = gen.generate_for_segments(segments)

    for seg in segments:
        in_window = [
            sub
            for sub in subtitles
            if seg["offset"] - 1e-6
            <= sub.start_time
            < seg["offset"] + seg["duration"] + 1e-6
        ]
        assert in_window, f"segment at {seg['offset']} has no subtitles"


def test_long_episode_last_end_matches_total():
    gen = SubtitleGenerator()
    total = 600.0
    segments = _build_segments(40, total)

    subtitles = gen.generate_for_segments(segments)

    assert abs(subtitles[-1].end_time - total) < 0.3
    _assert_within_own_segment(subtitles, segments)


def test_offsets_default_to_running_sum():
    gen = SubtitleGenerator()
    segments = [
        {"text": "第一段。", "duration": 5.0},
        {"text": "第二段。", "duration": 7.0},
    ]

    subtitles = gen.generate_for_segments(segments)

    assert subtitles[0].start_time == 0.0
    assert subtitles[-1].end_time == 12.0


def test_generate_for_segments_empty_and_blank():
    gen = SubtitleGenerator()
    assert gen.generate_for_segments([]) == []
    assert gen.generate_for_segments([{"text": "   ", "duration": 3.0}]) == []


# --------------------------------------------------------------------------- #
# generate_for_segments — boundaries path
# --------------------------------------------------------------------------- #


def test_boundaries_use_each_boundary_timing():
    gen = SubtitleGenerator()
    segments = [
        {
            "text": "ignored",
            "duration": 10.0,
            "offset": 0.0,
            "boundaries": [
                {"offset": 0.0, "duration": 4.0, "text": "第一句。"},
                {"offset": 4.0, "duration": 6.0, "text": "第二句。"},
            ],
        },
        {
            "text": "ignored",
            "duration": 5.0,
            "boundaries": [
                {"offset": 0.0, "duration": 5.0, "text": "第三句。"},
            ],
        },
    ]

    subtitles = gen.generate_for_segments(segments)

    assert len(subtitles) == 3
    assert (subtitles[0].start_time, subtitles[0].end_time) == (0.0, 4.0)
    assert (subtitles[1].start_time, subtitles[1].end_time) == (4.0, 10.0)
    # Second segment omitted ``offset`` -> running sum of previous durations.
    assert (subtitles[2].start_time, subtitles[2].end_time) == (10.0, 15.0)
    assert [sub.index for sub in subtitles] == [1, 2, 3]


def test_boundaries_split_long_sentence_proportionally():
    gen = SubtitleGenerator(max_chars_per_line=5)
    text = "一二三四五六七八九十"
    segments = [
        {
            "text": text,
            "duration": 10.0,
            "boundaries": [{"offset": 0.0, "duration": 10.0, "text": text}],
        }
    ]

    subtitles = gen.generate_for_segments(segments)

    assert len(subtitles) == 2
    assert (subtitles[0].start_time, subtitles[0].end_time) == (0.0, 5.0)
    assert (subtitles[1].start_time, subtitles[1].end_time) == (5.0, 10.0)
    assert subtitles[0].text + subtitles[1].text == text


def test_boundaries_group_short_words():
    gen = SubtitleGenerator(max_chars_per_line=6)
    segments = [
        {
            "text": "x",
            "duration": 3.0,
            "boundaries": [
                {"offset": 0.0, "duration": 0.5, "text": "你好"},
                {"offset": 0.5, "duration": 0.5, "text": "世界"},
                {"offset": 1.0, "duration": 0.5, "text": "再见"},
            ],
        }
    ]

    subtitles = gen.generate_for_segments(segments)

    assert len(subtitles) == 1
    assert subtitles[0].text == "你好世界再见"
    assert (subtitles[0].start_time, subtitles[0].end_time) == (0.0, 1.5)


def test_boundaries_extend_small_gap_to_next_start():
    gen = SubtitleGenerator()
    segments = [
        {
            "text": "",
            "duration": 3.0,
            "boundaries": [
                {"offset": 0.0, "duration": 1.0, "text": "甲。"},
                {"offset": 1.2, "duration": 1.0, "text": "乙。"},
            ],
        }
    ]

    subtitles = gen.generate_for_segments(segments)

    assert subtitles[0].end_time == 1.2
    assert subtitles[1].start_time == 1.2


def test_boundaries_ignore_malformed_entries_and_clamp():
    gen = SubtitleGenerator()
    segments = [
        {
            "text": "",
            "duration": 2.0,
            "boundaries": [
                "not-a-dict",
                {"offset": "bad", "duration": None, "text": ""},
                {"offset": 1.0, "duration": 5.0, "text": "超出。"},
            ],
        }
    ]

    subtitles = gen.generate_for_segments(segments)

    assert len(subtitles) == 1
    assert subtitles[0].start_time == 1.0
    assert subtitles[0].end_time == 2.0


# --------------------------------------------------------------------------- #
# legacy generate() — no accumulating gap
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_legacy_generate_last_line_ends_at_audio_duration():
    gen = SubtitleGenerator()

    subtitles = await gen.generate(text="第一句。第二句。第三句。", audio_duration=30.0)

    assert subtitles
    assert abs(subtitles[-1].end_time - 30.0) < 1e-6


# --------------------------------------------------------------------------- #
# video_service integration
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_generate_subtitles_integration_ends_at_total(tmp_path):
    tl = TaskLogger("subs-integration", tmp_path)
    total = 256.4
    segments = _build_segments(10, total)
    segment_audios = [
        {
            "index": i,
            "text": seg["text"],
            "duration": seg["duration"],
            "offset": seg["offset"],
            "boundaries": [],
        }
        for i, seg in enumerate(segments)
    ]
    request = SimpleNamespace(
        generate_subtitle=True,
        subtitle_font="Microsoft YaHei",
        subtitle_color="&H00FFFFFF",
        language="zh",
        lang="zh",
    )

    subtitles = await vs._generate_subtitles(
        segment_audios, total, request, tmp_path, tl
    )

    assert subtitles
    assert abs(subtitles[-1].end_time - total) < 0.3
    assert (tmp_path / "subtitles.ass").exists()
    assert tl.status["files"]["subtitles"].endswith("subtitles.ass")


@pytest.mark.asyncio
async def test_synthesize_audio_records_offsets_and_boundaries(tmp_path):
    tl = TaskLogger("tts-boundaries", tmp_path)
    script = SimpleNamespace(
        segments=[SimpleNamespace(text="a"), SimpleNamespace(text="b")]
    )

    class _Provider:
        def __init__(self, **kwargs):
            self.calls = 0

        async def synthesize(self, text, output_path=None, voice=None, boundaries=None):
            if boundaries is not None:
                boundaries.append(
                    {"offset": 0.0, "duration": 1.0, "text": text}
                )
            self.calls += 1
            Path(output_path).write_bytes(b"x")
            return output_path

        async def get_duration(self, audio_path):
            return 10.0 if self.calls == 1 else 20.0

    provider = _Provider()
    request = SimpleNamespace(voice="v", voice_rate="+0%")

    with patch.object(vs, "EdgeTTSEngine", MagicMock(return_value=provider)), patch.object(
        vs, "_ensure_not_cancelled"
    ):
        segment_audios, total = await vs._synthesize_audio(script, request, tmp_path, tl)

    assert total == 30.0
    assert [sa["offset"] for sa in segment_audios] == [0.0, 10.0]
    assert all(sa["boundaries"] for sa in segment_audios)


@pytest.mark.asyncio
async def test_synthesize_audio_legacy_tts_falls_back_without_boundaries(tmp_path):
    tl = TaskLogger("tts-legacy", tmp_path)
    script = SimpleNamespace(
        segments=[SimpleNamespace(text="a"), SimpleNamespace(text="b")]
    )

    class _LegacyProvider:
        """Old-style TTS whose synthesize() has no ``boundaries`` keyword."""

        def __init__(self, **kwargs):
            self.calls = 0

        async def synthesize(self, text, output_path=None, voice=None):
            self.calls += 1
            Path(output_path).write_bytes(b"x")
            return output_path

        async def get_duration(self, audio_path):
            return 10.0 if self.calls == 1 else 20.0

    provider = _LegacyProvider()
    request = SimpleNamespace(voice="v", voice_rate="+0%")

    with patch.object(vs, "EdgeTTSEngine", MagicMock(return_value=provider)), patch.object(
        vs, "_ensure_not_cancelled"
    ):
        segment_audios, total = await vs._synthesize_audio(script, request, tmp_path, tl)

    assert total == 30.0
    assert provider.calls == 2
    assert [sa["offset"] for sa in segment_audios] == [0.0, 10.0]
    assert [sa["boundaries"] for sa in segment_audios] == [[], []]


# --------------------------------------------------------------------------- #
# edge-tts provider boundary capture
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_edge_provider_captures_boundaries(tmp_path):
    from src.core.tts.edge_provider import EdgeTTSProvider

    provider = EdgeTTSProvider(voice="zh-CN-XiaoxiaoNeural", rate="+0%")
    output = tmp_path / "out.mp3"

    class _FakeCommunicate:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def stream(self):
            yield {"type": "audio", "data": b"abc"}
            yield {
                "type": "SentenceBoundary",
                "offset": 10_000_000,
                "duration": 5_000_000,
                "text": "你好。",
            }
            yield {"type": "audio", "data": b"def"}
            yield {
                "type": "WordBoundary",
                "offset": 15_000_000,
                "duration": 2_000_000,
                "text": "世界",
            }

    with patch("edge_tts.Communicate", _FakeCommunicate):
        path, boundaries = await provider.synthesize_with_boundaries(
            "你好。世界", output_path=output
        )

    assert path == output
    assert output.read_bytes() == b"abcdef"
    assert boundaries == [
        {"offset": 1.0, "duration": 0.5, "text": "你好。"},
        {"offset": 1.5, "duration": 0.2, "text": "世界"},
    ]


@pytest.mark.asyncio
async def test_edge_provider_boundary_failure_falls_back(tmp_path):
    from src.core.tts.edge_provider import EdgeTTSProvider

    provider = EdgeTTSProvider(voice="v", rate="+0%")
    output = tmp_path / "out.mp3"

    class _FailingCommunicate:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def stream(self):
            raise RuntimeError("stream boom")
            yield  # pragma: no cover - makes this an async generator

        async def save(self, path):
            Path(path).write_bytes(b"fallback")

    with patch("edge_tts.Communicate", _FailingCommunicate):
        path, boundaries = await provider.synthesize_with_boundaries(
            "x", output_path=output
        )

    assert path == output
    assert boundaries == []
    assert output.read_bytes() == b"fallback"


@pytest.mark.asyncio
async def test_edge_provider_plain_synthesize_still_works(tmp_path):
    from src.core.tts.edge_provider import EdgeTTSProvider

    provider = EdgeTTSProvider(voice="v", rate="+0%")
    output = tmp_path / "plain.mp3"

    class _SaveCommunicate:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def save(self, path):
            Path(path).write_bytes(b"plain")

    with patch("edge_tts.Communicate", _SaveCommunicate):
        result = await provider.synthesize("你好", output_path=output)

    assert result == output
    assert output.read_bytes() == b"plain"
