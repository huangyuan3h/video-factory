"""ep21 seed fix: jargon blocklist + visual beats (fails QA otherwise)."""

import pytest

from src.services.indicator.jargon import (
    assert_no_jargon,
    check_segments,
    find_jargon,
)
from src.services.indicator.visual_beats import (
    assert_beat_sync,
    assert_visual_beats,
    beat_markers_in_order,
    check_beat_sync,
    check_visual_beats,
    compute_cue_based_holds,
    compute_holds_from_boundaries,
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


def _ep21_seg7():
    text = (
        "你可能会问，换股票会不会好点？闭眼抓12只，只吃它们身上的突破，"
        "对比一直拿着不动。随机抽了三组，每组12只，第一组0只跑赢，也就是0/12。"
        "第二组1只跑赢，也就是1/12。第三组3只跑赢，也就是3/12。"
        "换股票也躲不掉，那是不是运气差？"
    )
    # Narration-absolute cue starts (mirrors ep21 seg7 subtitles.ass).
    seg_start = 163.68
    cues = [
        {"start": 163.68, "end": 166.54, "text": "你可能会问，换股票会不会好点？"},
        {"start": 167.16, "end": 171.90, "text": "闭眼抓12只，只吃它们身上的突破，对比一直拿着不动"},
        {"start": 172.51, "end": 176.68, "text": "随机抽了三组，每组12只，第一组0只跑赢"},
        {"start": 176.68, "end": 177.78, "text": "也就是0/12"},
        {"start": 178.39, "end": 181.35, "text": "第二组1只跑赢，也就是1/12"},
        {"start": 181.96, "end": 185.08, "text": "第三组3只跑赢，也就是3/12"},
        {"start": 185.69, "end": 188.50, "text": "换股票也躲不掉，那是不是运气差？"},
    ]
    return text, seg_start, cues


def test_beat_markers_in_order():
    text, _, _ = _ep21_seg7()
    assert beat_markers_in_order(text) == ["第一组", "第二组", "第三组"]
    assert beat_markers_in_order("组合年化-38.9%。") == []


def test_cue_based_holds_follow_second_group_cue():
    text, seg_start, cues = _ep21_seg7()
    span = 26.256  # 25.756s speech + 0.5s pause
    holds = compute_cue_based_holds(text, span, cues, 3, seg_start)
    # Switches land exactly on the 第二组 / 第三组 cue starts.
    assert holds[0] == pytest.approx(178.39 - seg_start, abs=1e-6)
    assert holds[0] + holds[1] == pytest.approx(181.96 - seg_start, abs=1e-6)
    assert sum(holds) == pytest.approx(span, abs=1e-6)
    # Even split would be 8.75s each; cue-based first hold is ~14.7s.
    assert holds[0] > 12.0
    assert holds[1] == pytest.approx(3.57, abs=0.01)


def test_cue_based_fallback_on_missing_marker():
    text = "随机抽了三组，第一组0/12，第二组1/12，第三组3/12。"
    cues = [{"start": 0.0, "end": 10.0, "text": "随机抽了三组"}]
    assert compute_cue_based_holds(text, 24.0, cues, 3, 0.0) == [8.0, 8.0, 8.0]
    # Marker/image count mismatch -> even split.
    assert compute_cue_based_holds(text, 24.0, cues, 2, 0.0) == [12.0, 12.0]


def test_beat_sync_even_split_desyncs_ep21():
    text, seg_start, cues = _ep21_seg7()
    images = ["g1.png", "g2.png", "g3.png"]
    span = 26.256
    even = [span / 3] * 3
    offenders = check_beat_sync(text, images, seg_start, even, cues, span)
    # Even-split g2 switch (~172.4s) lands inside the 第一组 cue.
    assert offenders
    assert any("第二组" in o for o in offenders)
    with pytest.raises(ValueError):
        assert_beat_sync(text, images, seg_start, even, cues, span)


def test_beat_sync_cue_based_passes_ep21():
    text, seg_start, cues = _ep21_seg7()
    images = ["g1.png", "g2.png", "g3.png"]
    span = 26.256
    holds = compute_cue_based_holds(text, span, cues, 3, seg_start)
    assert check_beat_sync(text, images, seg_start, holds, cues, span) == []
    assert_beat_sync(text, images, seg_start, holds, cues, span)  # no raise


def test_beat_sync_next_cue_within_0_3s_passes():
    text = "第一组0/12。第二组1/12。第三组3/12。"
    images = ["g1.png", "g2.png", "g3.png"]
    # Switch 0.2s before the 第二组 cue -> next cue within 0.3s counts.
    cues = [
        {"start": 0.0, "end": 5.0, "text": "第一组0/12"},
        {"start": 5.2, "end": 8.0, "text": "第二组1/12"},
        {"start": 8.0, "end": 12.0, "text": "第三组3/12"},
    ]
    assert check_beat_sync(text, images, 0.0, [5.0, 3.0, 4.0], cues, 12.0) == []
    # Switch 1.0s before the cue -> fail.
    assert check_beat_sync(text, images, 0.0, [4.2, 3.8, 4.0], cues, 12.0) != []


def test_holds_from_boundaries():
    text, _, _ = _ep21_seg7()
    boundaries = [
        {"offset": 0.0, "duration": 3.0, "text": "你可能会问，换股票会不会好点？"},
        {"offset": 8.83, "duration": 4.0, "text": "随机抽了三组，每组12只，第一组0只跑赢"},
        {"offset": 14.71, "duration": 3.0, "text": "第二组1只跑赢，也就是1/12"},
        {"offset": 18.28, "duration": 3.0, "text": "第三组3只跑赢，也就是3/12"},
    ]
    holds = compute_holds_from_boundaries(text, 26.256, boundaries, 3)
    assert holds[0] == pytest.approx(14.71, abs=0.01)
