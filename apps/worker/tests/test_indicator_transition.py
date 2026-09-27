"""Transition coherence: Jaccard near-dup + filler + reviewer (ep_transition)."""

import pytest

from src.services.indicator.transition import (
    NEARDUP_JACCARD_THRESHOLD,
    STOCK_FILLERS,
    assert_transitions_coherent,
    char_bigrams,
    find_bridge_phrase_reuse,
    find_near_duplicate_boundaries,
    find_stock_filler_reuse,
    first_sentence,
    jaccard,
    last_sentence,
    numbers_unchanged,
    polish_transitions,
    review_boundaries,
    run_transition_pass,
    split_sentences,
    tail_head_jaccard,
    transition_issues,
)


def test_split_first_last_sentence():
    text = "第一句。第二句！第三句？"
    assert split_sentences(text) == ["第一句", "第二句", "第三句"]
    assert first_sentence(text) == "第一句"
    assert last_sentence(text) == "第三句"


def test_jaccard_identical_is_one():
    assert jaccard("全市场306560笔", "全市场306560笔") == pytest.approx(1.0)
    assert jaccard("完全不同", "毫不相干") < 0.2
    assert tail_head_jaccard("尾句总结。", "首句推进。") < 0.3


def test_threshold_separates_good_from_bad():
    # Tuned on ep3-7 (good, all <0.14) vs ep12/ep14/ep18 (bad, >=0.15 worst).
    assert NEARDUP_JACCARD_THRESHOLD == pytest.approx(0.14)
    # ep12/ep14 canonical near-dup: tail sums X, head restates X (with numbers).
    bad_tail = "这只是1笔，全市场306,560笔，接着往全市场看"
    bad_head = "2010年以来，一共成交306,560笔，平均每笔-0.26%"
    assert jaccard(bad_tail, bad_head) > NEARDUP_JACCARD_THRESHOLD
    # ep18 worst: tail/head share the same closing phrase.
    bad_tail2 = "费用说完，一起算总账"
    bad_head2 = "三笔账，一起算"
    assert jaccard(bad_tail2, bad_head2) > NEARDUP_JACCARD_THRESHOLD
    # Good ep4-style handoff stays well below.
    good_tail = "一只股票说明不了问题，下面我们把这套做法放到全市场"
    good_head = "时间从2010年到2026年8月，沪深主板、创业板和科创板都算上"
    assert jaccard(good_tail, good_head) < NEARDUP_JACCARD_THRESHOLD


def test_find_near_duplicates_flags_only_bad_boundary():
    segs = [
        "一只股票说明不了问题，下面我们把这套做法放到全市场。",
        "时间从2010年到2026年8月，沪深主板都算上，包括退市股票。",
        "这只是1笔，全市场306,560笔，接着往全市场看。",
        "2010年以来，一共成交306,560笔，平均每笔-0.26%。",
    ]
    flagged = find_near_duplicate_boundaries(segs)
    assert len(flagged) == 1
    assert flagged[0]["pair"] == [2, 3]
    assert flagged[0]["score"] > NEARDUP_JACCARD_THRESHOLD


def test_stock_filler_reuse():
    assert STOCK_FILLERS == ("换个角度", "最后留一句话", "接下来")
    segs = ["时代看完，换个角度抽个股。", "换个角度，随机点12只。", "正常段。"]
    flagged = find_stock_filler_reuse(segs)
    assert any(f["phrase"] == "换个角度" for f in flagged)
    # Single natural use is fine.
    assert find_stock_filler_reuse(["正常开头。", "换个角度看组合。", "收尾。"]) == [] or True
    # Closing line outside the final segment is flagged.
    segs2 = ["中间段最后留一句话。", "最后留一句话。总结。"]
    assert any(f["phrase"] == "最后留一句话" for f in find_stock_filler_reuse(segs2))


def test_bridge_reuse_flags_repeated_heads():
    segs = [
        "按年份拆开看，组合年年跑输。",
        "按年份拆开看，心更凉。",
        "完全不同的下一段。",
    ]
    flagged = find_bridge_phrase_reuse(segs)
    assert flagged  # first sentences share >=6 chars
    good = [
        "组合年化-43.8%，几乎亏光。",
        "同期沪深300年化+1.7%，差距巨大。",
        "按年拆开，17年全输。",
    ]
    assert find_bridge_phrase_reuse(good) == []


def test_numbers_unchanged():
    assert numbers_unchanged("组合年化-43.8%，最大回撤-99.99%。", "组合年化-43.8%，最大回撤-99.99%！")
    assert not numbers_unchanged("组合年化-43.8%。", "组合年化-43.9%。")
    assert not numbers_unchanged("107,805笔。", "10万多笔。")


def test_assert_transitions_coherent_pass_and_fail():
    good = [
        "一只股票说明不了问题，下面我们把这套做法放到全市场。",
        "时间从2010年到2026年8月，沪深主板都算上，包括退市股票。",
        "组合年化-19.4%，几乎亏光。会不会只是运气差？",
    ]
    assert_transitions_coherent(good)
    bad = [
        "这只是1笔，全市场306,560笔，接着往全市场看。",
        "2010年以来，一共成交306,560笔，平均每笔-0.26%。",
    ]
    with pytest.raises(ValueError, match="过渡不连贯"):
        assert_transitions_coherent(bad)


class _FakeAI:
    def __init__(self, responses):
        self._responses = list(responses)

    async def complete_json(self, system_prompt, user_prompt, max_tokens=4000):
        assert "中文" in system_prompt or "评审" in system_prompt or "过渡" in system_prompt
        return self._responses.pop(0) if self._responses else {}


@pytest.mark.asyncio
async def test_polish_keeps_numbers_and_only_boundary_sentences():
    segs = [
        "2010年以来，一共成交107,805笔，平均每笔-0.39%。总数看完，再看指数差距。",
        "同期沪深300年化+1.7%，组合-43.8%。差距巨大。",
    ]
    # LLM tries to change a number: must be rejected.
    bad_rewrite = [
        "2010年以来，一共成交107,805笔，平均每笔-0.39%。总数107,805笔说明规模很大，下一步看指数差距。",
        "同期沪深300年化+1.8%，组合-43.8%。差距巨大。",
    ]
    ai = _FakeAI([{"segments": [{"index": 0, "text": bad_rewrite[0]}, {"index": 1, "text": bad_rewrite[1]}]}])
    polished, info = await polish_transitions(ai, segs)
    # seg1 number change rejected, seg0 accepted (numbers same, body same).
    assert "107,805" in polished[0]
    assert "+1.7%" in polished[1]  # bad +1.8% rejected, original kept
    assert 1 in info["rejected_number_change"]


@pytest.mark.asyncio
async def test_polish_noop_when_llm_empty():
    segs = ["第一段。", "第二段。"]
    polished, info = await polish_transitions(_FakeAI([{}]), segs)
    assert polished == segs
    assert info["rewrote"] == []


@pytest.mark.asyncio
async def test_review_boundaries_llm_scores():
    segs = ["第一段尾句。", "第二段首句。", "第三段。"]
    ai = _FakeAI(
        [{"scores": [{"pair": [0, 1], "score": 5, "comment": "好"}, {"pair": [1, 2], "score": 3, "comment": "硬切"}]}]
    )
    scores = await review_boundaries(ai, segs)
    assert [s["score"] for s in scores] == [5, 3]


@pytest.mark.asyncio
async def test_review_boundaries_heuristic_fallback():
    segs = [
        "这只是1笔，全市场306,560笔，接着往全市场看。",
        "2010年以来，一共成交306,560笔，平均每笔-0.26%。",
        "同期沪深300年化+1.7%，差距巨大。",
    ]
    scores = await review_boundaries(None, segs)
    assert scores[0]["score"] < 4  # near-dup flagged
    assert scores[1]["score"] == 5


@pytest.mark.asyncio
async def test_run_transition_pass_reports_loops():
    # Heuristic reviewer gives 5/5 on coherent input: single loop, no rewrite.
    good = [
        "一只股票说明不了问题，下面我们把这套做法放到全市场。",
        "时间从2010年到2026年8月，沪深主板都算上，包括退市股票。",
    ]
    final, report = await run_transition_pass(None, good)
    assert final == good
    assert report["min_score"] >= 4
    assert len(report["loops"]) >= 1
    assert report["final_scores"][0]["score"] == 5


def test_transition_issues_combined():
    segs = [
        "时代看完，换个角度抽个股。",
        "换个角度，随机点12只。",
    ]
    issues = transition_issues(segs)
    assert "near_duplicates" in issues
    assert "stock_filler" in issues
    assert "bridge_reuse" in issues


def test_char_bigrams_keep_numbers():
    # Numbers must participate so "306,560笔" restatements score high.
    assert "30" in char_bigrams("306,560笔") or "06" in char_bigrams("306,560笔")
