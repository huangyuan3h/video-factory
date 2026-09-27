"""QA gate: card overflow + repeat dedupe (ep12/ep14 regressions)."""

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from src.services.indicator.card_qa import (
    check_card_image_no_overflow,
    shorten_card_fact,
)
from src.services.indicator.repeat_guard import (
    assert_no_repeats,
    find_adjacent_bridge_repeats,
    find_global_repeats,
    strip_bridge_duplicates,
)


def test_global_repeat_detects_six_char_duplicate():
    segs = [
        "三句话总结。第一，中位数-0.87%，55.6%都在亏。",
        "最后留一句话。306,560次一阳穿三线，平均每笔-0.26%。",
        "中间段正常讲述。",
        "最后留一句话。",  # same standalone sentence as seg1 opener
    ]
    # The closing sentence appears in seg1 and seg3.
    repeats = find_global_repeats(segs)
    assert any("最后留一句话" in r["phrase"] for r in repeats)
    with pytest.raises(ValueError):
        assert_no_repeats(
            [
                "三句话总结。最后留一句话。",
                "最后留一句话。",  # exact duplicate sentence
            ]
        )


def test_adjacent_bridge_detects_four_char_overlap():
    segs = [
        "时代看完，换个角度抽个股。",
        "换个角度，随机点12只，只做它们身上的五连阳。",
    ]
    adj = find_adjacent_bridge_repeats(segs)
    assert adj and adj[0]["phrase"] == "换个角度"
    with pytest.raises(ValueError):
        assert_no_repeats(segs)


def test_numbers_do_not_trip_repeat_guard():
    # Legitimate number repeats (沪深300, -47.9%) must not fail.
    segs = [
        "同期沪深300年化+1.7%，中证500年化+3.6%，组合-47.9%。",
        "组合-47.9%，沪深300+1.7%，中证500+3.6%，4个时代全输。",
    ]
    assert find_global_repeats(segs) == []
    assert find_adjacent_bridge_repeats(segs) == []


def test_strip_bridge_duplicates_single_owner():
    segs = [
        "时代看完，换个角度抽个股。",
        "换个角度，随机点12只。",
        "三句话总结。最后留一句话。",
        "最后留一句话。306,560次一阳穿三线。",
    ]
    fixed = strip_bridge_duplicates(segs)
    # Leading bridge removed from seg1, closing kept only in last seg.
    assert fixed[1] == "随机点12只。"
    assert "最后留一句话" not in fixed[2]
    assert "最后留一句话" in fixed[3]
    # After stripping, the adjacent check passes.
    assert find_adjacent_bridge_repeats(fixed) == []


def _card(tmp_path: Path, text_pad: int) -> Path:
    """Synthetic green card: box 200x100 at (50,30), text as dark block."""
    p = tmp_path / "card.png"
    img = Image.new("RGB", (400, 200), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    # Right box background + border (green).
    draw.rectangle([200, 30, 350, 130], fill=(234, 245, 234), outline=(44, 160, 44), width=2)
    # Dark text block inside with `text_pad` padding on each side.
    draw.rectangle(
        [200 + text_pad, 30 + text_pad, 350 - text_pad, 130 - text_pad],
        fill=(34, 34, 34),
    )
    img.save(p)
    return p


def test_card_qa_detects_real_overflow_image():
    # Fixed charts (post-fix) must pass the QA gate.
    real = Path(
        "/Users/huangyuan/Projects/karios-series-output/one_yang_three_lines/charts/13_myth_vs_data.png"
    )
    if real.is_file():
        assert check_card_image_no_overflow(real) == []


def test_shorten_card_fact_keeps_numbers_and_two_clauses():
    fact = (
        "组合年化 -47.9% vs 沪深300 +1.7% / 中证500 +3.6%；"
        "4 个时代全部跑输两大指数；额外第三句不该出现"
    )
    short = shorten_card_fact(fact)
    assert "；" not in short or short.count("；") <= 1
    for token in ("-47.9%", "+1.7%", "+3.6%", "4"):
        assert token in short
    assert "额外第三句" not in short
