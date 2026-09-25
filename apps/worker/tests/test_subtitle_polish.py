"""Subtitle line polish: number integrity, balanced wrap and orientation width."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.subtitle_gen import SubtitleGenerator
from src.core.task_logger import TaskLogger
from src.services import video_service as vs


def _boundary_subtitles(text: str, max_chars: int):
    gen = SubtitleGenerator(max_chars_per_line=max_chars)
    segments = [
        {
            "text": text,
            "duration": 10.0,
            "offset": 0.0,
            "boundaries": [{"offset": 0.0, "duration": 10.0, "text": text}],
        }
    ]
    return gen.generate_for_segments(segments)


# --------------------------------------------------------------------------- #
# Numbers stay intact
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("max_chars", [20, 26])
def test_decimal_number_is_never_broken(max_chars):
    text = "2004年这里的房价又比上一年涨了15.5个百分点，涨幅远超日常物价的涨速。"

    subtitles = _boundary_subtitles(text, max_chars)

    assert subtitles
    assert any("15.5" in sub.text for sub in subtitles)
    for sub in subtitles:
        assert len(sub.text) >= 4
        if "15" in sub.text:
            assert "15.5" in sub.text


def test_percent_number_stays_whole():
    gen = SubtitleGenerator(max_chars_per_line=10)

    lines = gen._split_into_lines("增长率52.4%保持不变")

    assert "".join(lines) == "增长率52.4%保持不变"
    assert any("52.4%" in line for line in lines)
    for line in lines:
        if "52" in line:
            assert "52.4%" in line


def test_thousand_separator_stays_whole():
    gen = SubtitleGenerator(max_chars_per_line=5)

    lines = gen._split_sentence_pieces("价格上涨1,000倍")

    assert "".join(lines) == "价格上涨1,000倍"
    assert any("1,000" in line for line in lines)
    for line in lines:
        if "1" in line:
            assert "1,000" in line


# --------------------------------------------------------------------------- #
# Balanced hard wrap
# --------------------------------------------------------------------------- #


def test_long_clause_wraps_into_balanced_lines():
    text = "这一集我们来聊聊美国房地产泡沫是怎么一步步吹起来的。"

    subtitles = _boundary_subtitles(text, 20)

    assert len(subtitles) == 2
    lengths = [len(sub.text) for sub in subtitles]
    assert max(lengths) - min(lengths) <= 2


def test_long_clause_stays_single_line_when_it_fits():
    text = "这一集我们来聊聊美国房地产泡沫是怎么一步步吹起来的。"

    subtitles = _boundary_subtitles(text, 26)

    assert len(subtitles) == 1
    assert subtitles[0].text == text.rstrip("。")


# --------------------------------------------------------------------------- #
# Orientation-aware width
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "width,height,expected", [(1920, 1080, 26), (1080, 1920, 20)]
)
async def test_generate_subtitles_uses_orientation_width(
    tmp_path, width, height, expected
):
    tl = TaskLogger(f"orientation-{width}x{height}", tmp_path)
    gen = MagicMock()
    gen.generate_for_segments = MagicMock(return_value=[])
    gen.save_ass = AsyncMock()
    ctor = MagicMock(return_value=gen)
    request = SimpleNamespace(
        generate_subtitle=True,
        resolution_width=width,
        resolution_height=height,
        subtitle_font="Microsoft YaHei",
        subtitle_color="&H00FFFFFF",
        language="zh",
        lang="zh",
    )

    with patch.object(vs, "SubtitleGenerator", ctor):
        await vs._generate_subtitles([], 5.0, request, tmp_path, tl)

    assert ctor.call_args.kwargs["max_chars_per_line"] == expected


# --------------------------------------------------------------------------- #
# Display-text normalization (TTS-cleaned boundary artefacts)
# --------------------------------------------------------------------------- #


def test_display_text_fixes_tts_cleaned_sample():
    raw = "1985年，美国，日本等国签订了,广场协议 "

    assert SubtitleGenerator._display_text(raw) == "1985年，美国，日本等国签订了，广场协议"


def test_display_text_removes_whitespace_between_cjk():
    assert SubtitleGenerator._display_text("签订 了 广 场协议") == "签订了广场协议"
    assert SubtitleGenerator._display_text("协议 签署") == "协议签署"


def test_display_text_converts_ascii_punct_adjacent_to_cjk():
    assert SubtitleGenerator._display_text("等等;然后") == "等等；然后"
    assert SubtitleGenerator._display_text("他说:好的") == "他说：好的"
    assert SubtitleGenerator._display_text("中文,English") == "中文，English"


def test_display_text_collapses_repeated_punctuation():
    assert SubtitleGenerator._display_text("好的，，然后") == "好的，然后"
    assert SubtitleGenerator._display_text("好的，,然后") == "好的，然后"
    assert SubtitleGenerator._display_text("好的；;然后") == "好的；然后"


def test_display_text_strips_leading_and_trailing_marks():
    assert SubtitleGenerator._display_text("  《广场协议。") == "《广场协议"
    assert SubtitleGenerator._display_text("，。中文，") == "中文"


@pytest.mark.parametrize(
    "text", ["3:00", "1,000", "52.4%", "Hello, world", "CDO 2004"]
)
def test_display_text_keeps_ascii_intact(text):
    assert SubtitleGenerator._display_text(text) == text


def test_display_text_normalization_applied_to_boundary_lines():
    raw = "1985年，美国，日本等国签订了,广场协议 "

    subtitles = _boundary_subtitles(raw, 40)

    assert [sub.text for sub in subtitles] == [
        "1985年，美国，日本等国签订了，广场协议"
    ]


# --------------------------------------------------------------------------- #
# Length guard directive
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@patch.object(vs, "book_char_range", return_value=(800, 1000))
async def test_guard_directive_states_both_bounds(_range, tmp_path):
    tl = TaskLogger("guard-directive", tmp_path)
    long = MagicMock()
    long.segments = [MagicMock(text="字" * 500) for _ in range(3)]
    long.model_dump.return_value = {}
    short = MagicMock()
    short.segments = [MagicMock(text="字" * 300) for _ in range(3)]
    ai = MagicMock()
    ai.generate_script = AsyncMock(side_effect=[long, short])
    request = SimpleNamespace(
        content_type="book", title="标题", text_content="内容", system_prompt=""
    )

    await vs._guard_book_script_length(ai, request, long, "", tl)

    directive = ai.generate_script.await_args.kwargs["system_prompt"]
    assert "不要少于" in directive
    assert "800-1000 字" in directive and "8-12 段" in directive
