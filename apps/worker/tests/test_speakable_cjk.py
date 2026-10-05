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


# ---------------------------------------------------------------------------
# Finance polyphone dictionary (2026-10-05, ep36 平安银行 xíng -> yín háng).
# Homophone technique: single-reading chars force correct pronunciation with
# identical syllables (edge-tts escapes SSML, so <phoneme> cannot pass).
# Subtitles/display keep the ORIGINAL script verbatim (alignment maps
# homophones back; see test_subtitle_original_text.py).


def test_bank_forces_hang_homophone_ep36():
    # Core bug: 「平安银行」里的「银行」被读成 xíng，应为 yín háng.
    # 银杭 (yín háng) uses single-reading 杭 háng, forcing correct pronunciation
    # with identical listening syllables.
    assert to_speakable_text("平安银行000001.SZ") == "平安银杭000001.SZ"
    assert to_speakable_text("以平安银行为例") == "以平安银杭为例"
    assert to_speakable_text("平安银行") == "平安银杭"
    # Long-word-first: 银行家 contains 银行 but stays correct (yín háng jiā).
    assert to_speakable_text("银行家看好后市") == "银杭家看好后市"
    # Original script for subtitles must stay untouched (caller keeps original).
    original = "图上是平安银行000001.SZ，红字标的高乖离。"
    assert "银行" in original
    assert "银杭" not in original
    assert "银杭" in to_speakable_text(original)


def test_hang_group_forces_hang_xing_group_protected():
    # háng group -> 杭 (single reading, same tone, same listening).
    assert to_speakable_text("行业龙头") == "杭业龙头"
    assert to_speakable_text("看行情") == "看杭情"
    assert to_speakable_text("央行降息") == "央杭降息"
    assert to_speakable_text("投行业务") == "投杭业务"
    assert to_speakable_text("外资商行") == "外资商杭"
    # 券商行 contains 商行 -> 商杭 (covers the 券商行 case).
    assert to_speakable_text("券商行") == "券商杭"
    # xíng group explicitly protected: must NOT become 杭.
    for w in ("行权到期", "发行新股", "进行交易"):
        assert to_speakable_text(w) == w
        assert "杭" not in to_speakable_text(w)
    # No mutual overwrite in a mixed sentence.
    mixed = "行业龙头看行情，央行和投行都看好银行家，但发行和进行、行权仍读xing。"
    cleaned = to_speakable_text(mixed)
    assert "杭业" in cleaned and "杭情" in cleaned
    assert "央杭" in cleaned and "投杭" in cleaned and "银杭家" in cleaned
    # xíng words survive verbatim inside the same sentence.
    assert "发行" in cleaned and "进行" in cleaned and "行权" in cleaned


def test_other_finance_polyphones_few_but_accurate():
    # Same-tone single-reading homophones, listener hears identical syllables.
    assert to_speakable_text("重仓持有") == "众仓持有"  # zhòng
    assert to_speakable_text("利率下行") == "利律下行"  # lǜ
    assert to_speakable_text("调整仓位") == "条整仓位"  # tiáo
    assert to_speakable_text("累计收益") == "垒计收益"  # lěi
    assert to_speakable_text("累积回报") == "垒积回报"  # lěi
    # Protected (Edge already correct; avoid risky swaps).
    for w in ("还是要拿住", "股份分红", "子弹时间"):
        assert to_speakable_text(w) == w


def test_polyphone_preserves_ep36_segments_and_subtitle_original():
    from src.core.subtitle_gen import SubtitleGenerator

    originals = [
        "图上是平安银行000001.SZ，红字标的高乖离，标注都是持有到期。",
        "同一套做法在平安银行000001.SZ身上，下半年只有1笔完整交易。",
    ]
    gen = SubtitleGenerator()
    for original in originals:
        cleaned = to_speakable_text(original)
        assert "银杭" in cleaned  # forces yín háng
        assert "银行" in original and "银杭" not in original  # script untouched
        segs = [
            {
                "text": original,
                "duration": 8.0,
                "offset": 0.0,
                "boundaries": [{"offset": 0.0, "duration": 8.0, "text": cleaned}],
            }
        ]
        joined = "".join(s.text for s in gen.generate_for_segments(segs))
        assert "平安银行" in joined  # subtitles show original
        assert "银杭" not in joined
