"""Subtitle display recovers the ORIGINAL script text (task-S).

edge-tts SentenceBoundary text reflects the speakable-cleaned input (brackets
removed), so subtitles must be re-aligned to the original segment text to show
``《广场协议》`` instead of ``,广场协议``. Timing stays boundary-driven.
"""

from src.core.subtitle_gen import SubtitleGenerator
from src.core.tts.speakable import to_speakable_text

_ORIGINAL = "1985年，美国、日本等国签订了《广场协议》，联合干预外汇市场让美元贬值。"
_CLEANED = "1985年，美国、日本等国签订了广场协议，联合干预外汇市场让美元贬值。"


def _segments(original, cleaned, duration=8.0, offset=0.0):
    return [
        {
            "text": original,
            "duration": duration,
            "offset": offset,
            "boundaries": [{"offset": 0.0, "duration": duration, "text": cleaned}],
        }
    ]


def test_display_recovers_book_title_brackets():
    gen = SubtitleGenerator()
    subtitles = gen.generate_for_segments(_segments(_ORIGINAL, _CLEANED))

    joined = "".join(sub.text for sub in subtitles)
    assert "《广场协议》" in joined
    assert ",广场协议" not in joined
    assert "，广场协议" not in joined


def test_display_preserves_quotes():
    gen = SubtitleGenerator()
    subtitles = gen.generate_for_segments(
        _segments("他说“金叉就买”。", "他说金叉就买。")
    )

    assert any("“金叉就买”" in sub.text for sub in subtitles)


def test_timing_stays_boundary_driven():
    gen = SubtitleGenerator()
    subtitles = gen.generate_for_segments(
        _segments(_ORIGINAL, _CLEANED, duration=6.0, offset=2.5)
    )

    assert abs(subtitles[0].start_time - 2.5) < 1e-6
    assert abs(subtitles[-1].end_time - (2.5 + 6.0)) < 1e-6


def test_alignment_failure_falls_back_to_boundary_text():
    gen = SubtitleGenerator()
    subtitles = gen.generate_for_segments(_segments("完全不同的原文。", "unrelated text."))

    joined = "".join(sub.text for sub in subtitles)
    assert "unrelated" in joined


def test_extra_space_in_original_is_tolerated():
    gen = SubtitleGenerator()
    subtitles = gen.generate_for_segments(
        _segments("第一句。 第二句。", "第一句。第二句。", duration=6.0)
    )

    joined = "".join(sub.text for sub in subtitles)
    assert "第一句" in joined
    assert "第二句" in joined


def test_display_keeps_plus_sign_before_number():
    gen = SubtitleGenerator()
    original = "中证500年化+3.6%，全市场等权也有+1.4%。"
    subtitles = gen.generate_for_segments(_segments(original, to_speakable_text(original)))

    joined = "".join(sub.text for sub in subtitles)
    assert "+3.6%" in joined
    assert "+1.4%" in joined


def test_display_keeps_plus_sign_at_line_start():
    gen = SubtitleGenerator()
    original = "+0.18%的涨幅。"
    subtitles = gen.generate_for_segments(_segments(original, to_speakable_text(original)))

    joined = "".join(sub.text for sub in subtitles)
    assert joined.startswith("+0.18%")


def test_display_keeps_range_dash():
    gen = SubtitleGenerator()
    original = "2010—2026年，市场大幅波动。"
    subtitles = gen.generate_for_segments(_segments(original, to_speakable_text(original)))

    joined = "".join(sub.text for sub in subtitles)
    assert "2010—2026年" in joined
    assert "2010到2026" not in joined


def test_display_keeps_range_dash_after_unit():
    gen = SubtitleGenerator()
    original = "2010年—2026年，市场大幅波动。"
    subtitles = gen.generate_for_segments(_segments(original, to_speakable_text(original)))

    joined = "".join(sub.text for sub in subtitles)
    assert "2010年—2026年" in joined
    assert "2010年到2026年" not in joined


def test_display_keeps_negative_number():
    gen = SubtitleGenerator()
    original = "净利润-27.4%，同比下滑。"
    subtitles = gen.generate_for_segments(_segments(original, to_speakable_text(original)))

    joined = "".join(sub.text for sub in subtitles)
    assert "-27.4%" in joined
