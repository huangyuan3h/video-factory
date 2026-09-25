"""Subtitle display recovers the ORIGINAL script text (task-S).

edge-tts SentenceBoundary text reflects the speakable-cleaned input (brackets
removed), so subtitles must be re-aligned to the original segment text to show
``《广场协议》`` instead of ``,广场协议``. Timing stays boundary-driven.
"""

from src.core.subtitle_gen import SubtitleGenerator

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
