"""ep21 seed fix: jargon blocklist + visual beats (fails QA otherwise)."""

import pytest

from src.services.indicator.jargon import (
    assert_no_jargon,
    check_segments,
    find_jargon,
)
from src.services.indicator.visual_beats import (
    assert_visual_beats,
    check_visual_beats,
    count_group_beats,
)


def test_jargon_blocks_seed_wording():
    assert set(find_jargon("种子20260925那组")) == {"种子", "20260925 (seed constant)"}
    assert find_jargon("换seed 1试试") == ["seed"]
    assert find_jargon("random_state=1") == ["random_state"]
    assert find_jargon("见manifest.json") != []
    assert find_jargon("随机抽了三组，每组12只") == []
    assert find_jargon("第一组0只跑赢，也就是0/12") == []
    with pytest.raises(ValueError):
        assert_no_jargon(["正常旁白", "种子20260925那组"])
    # clean passes
    assert_no_jargon(["随机抽了三组，每组12只，第一组0只跑赢"])


def test_jargon_blocks_file_names_and_params():
    assert find_jargon("见07_random_grid.png") != []
    assert find_jargon("参数名是window") != []
    assert find_jargon("第一组0/12，第二组1/12") == []


def test_count_group_beats_three_groups():
    old = (
        "种子20260925那组，12只里0只跑赢，也就是0/12。"
        "换种子1，12只里1只跑赢，也就是1/12。"
        "种子2那组，12只里3只跑赢，也就是3/12。"
    )
    assert count_group_beats(old) == 3
    new = (
        "随机抽了三组，每组12只，第一组0只跑赢，也就是0/12。"
        "第二组1只跑赢，也就是1/12。第三组3只跑赢，也就是3/12。"
    )
    assert count_group_beats(new) == 3
    assert count_group_beats("组合年化-38.9%，最大回撤-99.96%。") == 1


def test_visual_beats_single_image_for_three_groups_fails():
    segs = [
        "随机抽了三组，每组12只，第一组0只跑赢，也就是0/12。"
        "第二组1只跑赢，也就是1/12。第三组3只跑赢，也就是3/12。"
    ]
    # one image for three beats -> fail
    offenders = check_visual_beats(segs, [["only.png"]], [29.9], ["none"])
    assert offenders
    with pytest.raises(ValueError):
        assert_visual_beats(segs, [["only.png"]], [29.9], ["none"])
    # three highlight variants -> pass
    assert (
        check_visual_beats(
            segs, [["g1.png", "g2.png", "g3.png"]], [29.9], ["none", "none", "none"]
        )
        == []
    )


def test_visual_beats_long_static_hold_fails():
    # Multi-beat with single static long hold fails (the ep21 bug).
    multi = "随机抽了三组，第一组0/12，第二组1/12，第三组3/12。"
    offenders = check_visual_beats([multi], [["chart.png"]], [28.6], ["none"])
    assert offenders
    # Single-result deep-dive (one chart, 28s) is series norm -> pass.
    single = "把镜头再拉远，放到全市场看钱滚钱的结果。组合年化-38.9%。"
    assert check_visual_beats([single], [["chart.png"]], [28.6], ["none"]) == []
    # Animated multi-beat is exempt from the hold gate (but still needs beats).
    assert check_visual_beats([multi], [["a.png", "b.png", "c.png"]], [28.6], ["none"]) == []


def test_check_segments_reports_index():
    out = check_segments(["正常", "种子1那组"])
    assert out and out[0]["index"] == 1
