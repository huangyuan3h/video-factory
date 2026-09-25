"""Gentle pacing + friendly tone for book episodes (task-B).

Covers:
* friendly, book-agnostic prompts (and their duration-based parameterisation);
* the new book pacing config defaults;
* calmer book TTS rate + inter-segment pauses (offsets / total duration);
* compose placing audio/video clips at those offsets;
* subtitle timing that stays inside speech and skips pauses;
* the landscape default of the series generate-episodes route.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.config import settings
from src.core.subtitle_gen import SubtitleGenerator
from src.core.task_logger import TaskLogger
from src.services import book_script
from src.services import compose_service as cs
from src.services import video_service as vs
from tests.test_compose_cover_unit import FakeClip, patch_moviepy

# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #

_BANNED = ("竖屏", "短视频", "japan", "日本经济", "bubble economy")


def test_friendly_prompts_drop_vertical_short_video_and_japan_wording():
    for prompt in (
        book_script.book_dense_rewrite_prompt(),
        book_script.book_dense_script_prompt(),
    ):
        lowered = prompt.lower()
        for banned in _BANNED:
            assert banned not in lowered


def test_friendly_prompts_have_tone_markers():
    for prompt in (
        book_script.book_dense_rewrite_prompt(),
        book_script.book_dense_script_prompt(),
    ):
        assert "朋友" in prompt
        assert "我们先来看" in prompt
    assert "小结一下" in book_script.book_dense_rewrite_prompt()


def test_prompts_use_third_person_narrator_and_gentle_opening():
    for prompt in (
        book_script.book_dense_rewrite_prompt(),
        book_script.book_dense_script_prompt(),
    ):
        # Third-person 讲书人, author called 作者, no first-person impersonation.
        assert "作者" in prompt
        assert "第一人称" in prompt
        assert "这一集" in prompt
        # Each segment stays short and single-idea.
        assert "50-90" in prompt


def test_book_segment_range_defaults_and_scales():
    assert book_script.book_segment_range() == (8, 12)
    ten_low, ten_high = book_script.book_segment_range(target_minutes=10)
    assert ten_high > 12
    assert ten_low >= 8


def test_default_script_prompt_mentions_800_1000():
    prompt = book_script.build_book_script_prompt()
    assert "800-1000" in prompt
    assert "180-240" in prompt


def test_build_script_prompt_minutes_scale_up():
    default_low, default_high = book_script.book_char_range()
    ten_low, ten_high = book_script.book_char_range(target_minutes=10)
    assert ten_high > default_high
    assert ten_low > default_low
    assert (ten_low, ten_high) == (2300, 2600)

    # The larger target proves up in the prompt itself.
    prompt = book_script.build_book_script_prompt(target_minutes=10)
    assert f"{ten_low}-{ten_high}" in prompt
    assert "800-1000" not in prompt


def test_prompt_helpers_return_default_constants():
    assert book_script.build_book_rewrite_prompt() == book_script.BOOK_DENSE_REWRITE_PROMPT
    assert book_script.build_book_script_prompt() == book_script.BOOK_DENSE_SCRIPT_PROMPT
    assert book_script.BOOK_FRIENDLY_REWRITE_PROMPT == book_script.BOOK_DENSE_REWRITE_PROMPT
    assert book_script.BOOK_FRIENDLY_SCRIPT_PROMPT == book_script.BOOK_DENSE_SCRIPT_PROMPT
    assert book_script.book_dense_rewrite_prompt() == book_script.BOOK_DENSE_REWRITE_PROMPT
    assert book_script.book_dense_script_prompt() == book_script.BOOK_DENSE_SCRIPT_PROMPT


# --------------------------------------------------------------------------- #
# Config defaults
# --------------------------------------------------------------------------- #


def test_book_pacing_config_defaults():
    assert settings.book_tts_rate == "-8%"
    assert settings.book_segment_pause_seconds == 0.5
    assert settings.book_image_hold_seconds == 5.0
    assert settings.book_target_seconds == 210


# --------------------------------------------------------------------------- #
# _synthesize_audio: rate + pauses
# --------------------------------------------------------------------------- #


def _script(*texts):
    return SimpleNamespace(segments=[SimpleNamespace(text=t) for t in texts])


def _book_request(**overrides):
    base = dict(
        content_type="book",
        title="第一章",
        text_content="内容",
        system_prompt="",
        rewrite_content=False,
        voice="zh-CN-XiaoxiaoNeural",
        voice_rate="+0%",
        resolution_width=1920,
        resolution_height=1080,
        background_source="online",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class _Provider:
    def __init__(self, **kwargs):
        self.rate = kwargs.get("rate")
        self.calls = 0

    async def synthesize(self, text, output_path=None, voice=None, boundaries=None):
        if boundaries is not None:
            boundaries.append({"offset": 0.0, "duration": 1.0, "text": text})
        self.calls += 1
        from pathlib import Path

        Path(output_path).write_bytes(b"x")
        return output_path

    async def get_duration(self, audio_path):
        return 10.0


@pytest.mark.asyncio
async def test_book_synthesize_uses_gentle_rate_and_pauses(tmp_path):
    tl = TaskLogger("book-gentle", tmp_path)
    provider = _Provider()
    engine = MagicMock(return_value=provider)

    with patch.object(vs, "EdgeTTSEngine", engine), patch.object(vs, "_ensure_not_cancelled"):
        segs, total = await vs._synthesize_audio(
            _script("a", "b", "c"), _book_request(), tmp_path, tl
        )

    assert engine.call_args.kwargs["rate"] == "-8%"
    assert engine.call_args.kwargs["voice"] == "zh-CN-XiaoxiaoNeural"
    # Offsets include the 0.5s inter-segment pause.
    assert [s["offset"] for s in segs] == [0.0, 10.5, 21.0]
    assert [s["pause_after"] for s in segs] == [0.5, 0.5, 0.0]
    # speech (3x10) + two pauses (2x0.5)
    assert total == 31.0


@pytest.mark.asyncio
async def test_book_synthesize_explicit_rate_wins(tmp_path):
    tl = TaskLogger("book-rate-explicit", tmp_path)
    engine = MagicMock(return_value=_Provider())

    with patch.object(vs, "EdgeTTSEngine", engine), patch.object(vs, "_ensure_not_cancelled"):
        await vs._synthesize_audio(
            _script("a"), _book_request(voice_rate="+10%"), tmp_path, tl
        )

    assert engine.call_args.kwargs["rate"] == "+10%"


@pytest.mark.asyncio
async def test_book_synthesize_none_rate_uses_default_config(tmp_path):
    tl = TaskLogger("book-rate-none", tmp_path)
    engine = MagicMock(return_value=_Provider())

    with patch.object(vs, "EdgeTTSEngine", engine), patch.object(vs, "_ensure_not_cancelled"):
        await vs._synthesize_audio(
            _script("a"), _book_request(voice_rate=None), tmp_path, tl
        )

    assert engine.call_args.kwargs["rate"] == "-8%"


@pytest.mark.asyncio
async def test_non_book_synthesize_keeps_rate_and_no_pauses(tmp_path):
    tl = TaskLogger("non-book", tmp_path)
    engine = MagicMock(return_value=_Provider())

    with patch.object(vs, "EdgeTTSEngine", engine), patch.object(vs, "_ensure_not_cancelled"):
        segs, total = await vs._synthesize_audio(
            _script("a", "b"), _book_request(content_type="general", voice_rate="+0%"), tmp_path, tl
        )

    assert engine.call_args.kwargs["rate"] == "+0%"
    assert [s["pause_after"] for s in segs] == [0.0, 0.0]
    assert total == 20.0


# --------------------------------------------------------------------------- #
# compose_service: audio clip offsets
# --------------------------------------------------------------------------- #


def _logger(task_id, task_dir):
    return TaskLogger(task_id, task_dir)


def test_audio_track_places_clips_at_offsets(tmp_path):
    logger = _logger("audio-offsets", tmp_path)
    segment_audios = [
        {"index": 0, "audio_path": tmp_path / "s0.mp3", "duration": 10.0, "offset": 0.0},
        {"index": 1, "audio_path": tmp_path / "s1.mp3", "duration": 10.0, "offset": 10.5},
    ]
    starts = []

    def audio_factory(path):
        clip = FakeClip()
        orig = clip.with_start

        def _capture(start):
            starts.append(start)
            return orig(start)

        clip.with_start = _capture
        return clip

    with patch_moviepy(AudioFileClip=audio_factory):
        cs._create_audio_track(segment_audios, None, duration=21.0, task_logger=logger)

    assert starts == [0.0, 10.5]


def test_audio_track_offsets_with_start_offset(tmp_path):
    logger = _logger("audio-offsets-cover", tmp_path)
    segment_audios = [
        {"index": 0, "audio_path": tmp_path / "s0.mp3", "duration": 10.0, "offset": 0.0},
        {"index": 1, "audio_path": tmp_path / "s1.mp3", "duration": 10.0, "offset": 10.5},
    ]
    starts = []

    def audio_factory(path):
        clip = FakeClip()
        orig = clip.with_start

        def _capture(start):
            starts.append(start)
            return orig(start)

        clip.with_start = _capture
        return clip

    with patch_moviepy(AudioFileClip=audio_factory):
        cs._create_audio_track(
            segment_audios, None, duration=24.0, task_logger=logger, start_offset=3.0
        )

    assert starts == [3.0, 13.5]


def test_audio_track_missing_offset_falls_back_to_running_sum(tmp_path):
    logger = _logger("audio-fallback", tmp_path)
    segment_audios = [
        {"index": 0, "audio_path": tmp_path / "s0.mp3", "duration": 10.0},
        {"index": 1, "audio_path": tmp_path / "s1.mp3", "duration": 10.0},
    ]
    starts = []

    def audio_factory(path):
        clip = FakeClip()
        orig = clip.with_start

        def _capture(start):
            starts.append(start)
            return orig(start)

        clip.with_start = _capture
        return clip

    with patch_moviepy(AudioFileClip=audio_factory):
        cs._create_audio_track(segment_audios, None, duration=20.0, task_logger=logger)

    assert starts == [0.0, 10.0]


# --------------------------------------------------------------------------- #
# compose_service: video spans cover pauses
# --------------------------------------------------------------------------- #


def test_video_track_span_includes_pause(tmp_path):
    logger = _logger("video-pause", tmp_path)
    still = tmp_path / "a.jpg"
    created = []

    def image_factory(path):
        clip = FakeClip()
        created.append(clip)
        return clip

    with patch_moviepy(ImageClip=image_factory):
        cs._create_video_track(
            [],
            (64, 36),
            21.0,
            logger,
            segment_audios=[
                {"index": 0, "duration": 10.0, "offset": 0.0, "pause_after": 0.5},
                {"index": 1, "duration": 10.0, "offset": 10.5, "pause_after": 0.0},
            ],
            materials_per_segment=[[still], [still]],
        )

    # Segment 0 spans 10.5s (speech + pause); segment 1 starts at 10.5.
    assert created[0].duration == 10.5
    assert created[1].start == 10.5


# --------------------------------------------------------------------------- #
# Subtitle timing with pauses
# --------------------------------------------------------------------------- #


def test_subtitles_skip_pauses_and_end_at_total():
    gen = SubtitleGenerator()
    segment_audios = [
        {"text": "第一段。", "duration": 4.0, "offset": 0.0, "pause_after": 0.5},
        {"text": "第二段。", "duration": 4.0, "offset": 4.5, "pause_after": 0.5},
        {"text": "第三段。", "duration": 4.0, "offset": 9.0, "pause_after": 0.0},
    ]
    total = 13.0

    subtitles = gen.generate_for_segments(segment_audios)

    assert subtitles
    # Last subtitle ends at the last segment's offset + duration.
    assert abs(subtitles[-1].end_time - total) < 0.3
    # No subtitle starts or ends inside a pause window [off+dur, off+dur+pause].
    pauses = [(4.0, 4.5), (8.5, 9.0)]
    for sub in subtitles:
        for p_start, p_end in pauses:
            assert not (p_start < sub.start_time < p_end)
            assert not (p_start < sub.end_time < p_end)
    # Second segment's line starts after the first pause.
    seg2 = [s for s in subtitles if s.start_time >= 4.5]
    assert seg2 and seg2[0].start_time == 4.5


# --------------------------------------------------------------------------- #
# Subtitle line-break polish (boundary path)
# --------------------------------------------------------------------------- #


def test_long_boundary_sentence_breaks_at_clauses():
    gen = SubtitleGenerator(max_chars_per_line=20)
    text = "你可能会想，为什么一个国家的经济会停滞这么久？"
    segments = [
        {
            "text": text,
            "duration": 5.08,
            "offset": 2.74,
            "boundaries": [{"offset": 0.0, "duration": 5.08, "text": text}],
        }
    ]

    subtitles = gen.generate_for_segments(segments)

    assert subtitles
    for sub in subtitles:
        assert len(sub.text) >= 4
        assert not sub.text.endswith("，")
    # Timing covers the whole sentence window, starting at the segment offset.
    assert abs(subtitles[0].start_time - 2.74) < 1e-6
    assert abs(subtitles[-1].end_time - (2.74 + 5.08)) < 1e-6
    # Text is preserved apart from stripped clause punctuation.
    assert "".join(sub.text for sub in subtitles) == text.replace("，", "")


def test_single_overlong_clause_hard_wraps():
    gen = SubtitleGenerator(max_chars_per_line=5)
    text = "一二三四五六七八九十"
    segments = [
        {
            "text": text,
            "duration": 10.0,
            "offset": 0.0,
            "boundaries": [{"offset": 0.0, "duration": 10.0, "text": text}],
        }
    ]

    subtitles = gen.generate_for_segments(segments)

    assert len(subtitles) >= 2
    assert "".join(sub.text for sub in subtitles) == text


def test_boundary_clause_with_trailing_comma_stays_one_line():
    # "…三点五倍，" is 21 chars incl. the comma but only 20 displayed.
    gen = SubtitleGenerator(max_chars_per_line=20)
    text = "旧金山湾区的房价是全美平均水平的三点五倍，"
    segments = [
        {
            "text": text,
            "duration": 4.0,
            "offset": 0.0,
            "boundaries": [{"offset": 0.0, "duration": 4.0, "text": text}],
        }
    ]

    subtitles = gen.generate_for_segments(segments)

    assert len(subtitles) == 1
    assert subtitles[0].text == "旧金山湾区的房价是全美平均水平的三点五倍"
    assert all(gen._has_visible_text(sub.text) for sub in subtitles)


def test_boundary_does_not_split_ascii_word():
    gen = SubtitleGenerator(max_chars_per_line=20)
    text = "大量的住房贷款证券又被重新打包成一种叫CDO的产品"
    segments = [
        {
            "text": text,
            "duration": 5.0,
            "offset": 0.0,
            "boundaries": [{"offset": 0.0, "duration": 5.0, "text": text}],
        }
    ]

    subtitles = gen.generate_for_segments(segments)

    assert all(gen._has_visible_text(sub.text) for sub in subtitles)
    assert any("CDO" in sub.text for sub in subtitles)
    assert "".join(sub.text for sub in subtitles) == text


def test_text_fallback_merges_punctuation_only_line():
    gen = SubtitleGenerator(max_chars_per_line=20)
    segments = [{"text": "第一句。……。第二句。", "duration": 6.0, "offset": 0.0}]

    subtitles = gen.generate_for_segments(segments)

    assert subtitles
    assert all(gen._has_visible_text(sub.text) for sub in subtitles)
