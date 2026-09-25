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


def test_leading_plus_before_number_is_dropped():
    assert to_speakable_text("+1.7%") == "1.7%"
    assert to_speakable_text("沪深300年化+1.7%") == "沪深300年化1.7%"
    assert to_speakable_text("年化 +3.6%") == "年化 3.6%"
    assert to_speakable_text("（+0.18%）") == "0.18%"
    # The ASCII and full-width plus signs are both treated as number signs.
    assert to_speakable_text("＋0.5") == "0.5"


def test_plus_between_word_chars_is_kept():
    assert to_speakable_text("1+1=2") == "1+1=2"
    assert to_speakable_text("A+B") == "A+B"
    assert to_speakable_text("C++") == "C++"


def test_negative_number_keeps_leading_minus():
    assert to_speakable_text("-2.8%") == "-2.8%"


def test_range_dash_and_tilde_become_dao():
    assert to_speakable_text("2010—2026") == "2010到2026"
    assert to_speakable_text("2010–2026") == "2010到2026"
    assert to_speakable_text("2010~2026") == "2010到2026"
    assert to_speakable_text("2010～2026") == "2010到2026"
    assert to_speakable_text("2010 — 2026") == "2010到2026"
    assert to_speakable_text("3—5年") == "3到5年"
    assert to_speakable_text("2010年—2026年") == "2010年到2026年"


def test_ascii_hyphen_range_left_intact():
    assert to_speakable_text("2010-2026") == "2010-2026"


def test_em_dash_between_non_digits_still_a_pause():
    assert to_speakable_text("他说——你好") == "他说，你好"
