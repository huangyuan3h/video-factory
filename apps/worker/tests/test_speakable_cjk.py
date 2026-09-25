"""CJK TTS text normalisation (task-S).

The bug: ``to_speakable_text`` turned the ideographic comma ``、`` into a comma
and replaced ``《》`` with spaces, so edge-tts paused inside noun phrases
(``美国，日本等国签订了 广场协议 ``). The fix keeps ``、`` and removes
quote/bracket marks without splitting the phrase.
"""

from src.core.tts.speakable import to_speakable_text


def test_guangchang_sentence_keeps_ideographic_comma_and_brackets():
    text = "1985年，美国、日本等国签订了《广场协议》，联合干预外汇市场让美元贬值。"
    assert (
        to_speakable_text(text)
        == "1985年，美国、日本等国签订了广场协议，联合干预外汇市场让美元贬值。"
    )


def test_book_titles_lose_brackets_without_spaces():
    assert (
        to_speakable_text("他读了《人类简史》和《未来简史》。")
        == "他读了人类简史和未来简史。"
    )


def test_quotes_removed_without_space():
    assert to_speakable_text("他说“金叉就买”。") == "他说金叉就买。"


def test_ideographic_comma_unchanged():
    assert to_speakable_text("苹果、香蕉、橘子") == "苹果、香蕉、橘子"


def test_numbers_never_split():
    for text in ("涨了15.5个百分点", "52.4%", "2004年", "1,000", "3:00"):
        assert to_speakable_text(text) == text


def test_corner_brackets_collapse_around_ascii():
    assert to_speakable_text("「散户以为」vs「数据告诉你」") == "散户以为vs数据告诉你"


def test_english_apostrophe_kept_and_words_not_glued():
    assert to_speakable_text("Adam's book (2020)") == "Adam's book 2020"
    assert to_speakable_text("it's Adam's(2020)") == "it's Adam's 2020"
    assert to_speakable_text("don't stop") == "don't stop"


def test_em_dash_and_ellipsis_become_comma():
    assert to_speakable_text("他说——你好") == "他说，你好"
    assert to_speakable_text("等等……") == "等等，"


def test_pause_marks_never_double_or_meet_period():
    assert "，，" not in to_speakable_text("你好，——世界")
    assert "，。" not in to_speakable_text("等等……。结束")
    assert to_speakable_text("等等……。结束") == "等等。结束"


def test_markdown_and_emoji_still_stripped():
    cleaned = to_speakable_text("**重点** 🎉 <thinking>hidden</thinking> `code`")
    assert "**" not in cleaned
    assert "🎉" not in cleaned
    assert "hidden" not in cleaned
    assert "code" in cleaned
