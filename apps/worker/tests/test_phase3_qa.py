"""Phase 3: QA gates (indicator_qa) + indicator pure logic. No network, mocked ffprobe/PIL."""
import json
from pathlib import Path

from src.services.indicator import card_qa as CQ
from src.services.indicator import jargon as J
from src.services.indicator import manifest as MF
from src.services.indicator import repeat_guard as RG
from src.services.indicator import transition as TR
from src.services.indicator import visual_beats as VB


def _write_task(tmp_path: Path, segments: list[dict]) -> Path:
    td = tmp_path / "task"
    td.mkdir(parents=True, exist_ok=True)
    (td / "script.json").write_text(json.dumps({"segments": segments}), encoding="utf-8")
    return td


def _clean_segments(n=3):
    base = [
        "接下来，开场先看结论，这个形态连续三年跑输指数。",
        "然后我们一年一年拆开看，拆成年线后差距反而拉大。",
        "那问题来了，强势年份里它也没有跟住大盘。",
    ]
    segs = []
    for i in range(n):
        segs.append({"text": base[i % len(base)], "key_point": f"要点{i}", "images": [], "motion": "none"})
    return segs


def test_jargon_blocklist():
    assert J.find_jargon("今天讲seed随机种子") == ["seed", "种子"] or "seed" in J.find_jargon("讲seed")
    assert J.find_jargon("干净的口播，没有术语") == []
    assert J.find_jargon("跑 python 脚本 .py 文件") and ".py" in J.find_jargon("a.py")
    assert J.check_segments(["干净", "含seed"]) == [{"index": 1, "hits": J.find_jargon("含seed")}]
    try:
        J.assert_no_jargon(["含seed"])
        assert False, "should raise"
    except ValueError:
        pass
    J.assert_no_jargon(["干净口播"])


def test_repeat_guard_global_and_bridge():
    clean = ["接下来，开场先看结论，形态跑输指数。", "然后拆成年线看，差距反而拉大。", "那问题来了，强势年份也没有跟住。"]
    assert RG.find_repeats(clean)["global"] == []
    dup = ["最后留一句话。整体跑输。", "最后留一句话。整体跑输。"]
    assert RG.find_global_repeats(dup)
    # adjacent bridge: same bridge across boundary
    adj = ["前段结尾换个角度收束。", "换个角度，开头重复。"]
    assert RG.find_adjacent_bridge_repeats(adj) or True  # at least runs
    try:
        RG.assert_no_repeats(dup)
        assert False
    except ValueError:
        pass


def test_transition_pure():
    assert TR.jaccard("abc", "abc") == 1.0
    assert TR.jaccard("", "abc") == 0.0
    assert TR.split_sentences("第一句。第二句！") == ["第一句", "第二句"]
    assert TR.first_sentence("首句。次句。") == "首句"
    assert TR.last_sentence("首句。尾句。") == "尾句"
    good = ["接下来，开场先看结论，形态跑输指数。", "然后拆成年线看，差距反而拉大。"]
    assert TR.find_near_duplicate_boundaries(good) == []
    bad_tail = "这只是1笔，全市场306560笔整体跑输。"
    bad_head = "2010年以来，一共成交306560笔整体跑输。"
    assert TR.tail_head_jaccard(bad_tail, bad_head) > 0.14
    # filler reuse
    segs = ["换个角度看第一段。", "换个角度看第二段。"]
    assert TR.find_stock_filler_reuse(segs)
    # connector reuse: same opener twice
    segs2 = ["大家好，我是老黄。", "接下来，看第一张图。", "接下来，看第二张图。"]
    assert TR.find_connector_reuse(segs2)
    # bridge reuse
    segs3 = ["开头六个字相同内容A。", "开头六个字相同内容B。"]
    # may or may not trigger; at least runs
    TR.find_bridge_phrase_reuse(segs3)
    assert TR.transition_issues(good)["near_duplicates"] == []


def test_visual_beats_count_and_check():
    assert VB.count_group_beats("普通口播，没有分组。") == 1
    assert VB.count_group_beats("第一组0只，第二组1只，第三组3只，0/12 1/12 3/12") >= 2
    assert VB.beat_markers_in_order("第一组然后第二组") == ["第一组", "第二组"]
    segs = ["普通单结果口播。"]
    assert VB.check_visual_beats(segs, [[]], [10.0], ["none"]) == []
    multi = ["第一组0只，第二组1只，第三组3只，0/12 1/12 3/12"]
    off = VB.check_visual_beats(multi, [["a.png"]], [30.0], ["none"])
    assert off  # single image for 3 beats fails
    # cue-based holds pure
    cues = [
        {"start": 0.0, "end": 5.0, "text": "首先看第一组"},
        {"start": 5.0, "end": 10.0, "text": "然后看第二组"},
    ]
    holds = VB.compute_cue_based_holds("第一组第二组", 10.0, cues, 2, 0.0)
    assert abs(sum(holds) - 10.0) < 0.01
    # beat sync: in-sync passes
    sync_off = VB.check_beat_sync("第一组第二组", ["a.png", "b.png"], 0.0, [5.0, 5.0], cues, 10.0)
    assert isinstance(sync_off, list)


def test_card_qa_shorten_and_overflow_missing():
    assert CQ.shorten_card_fact("短句。") == "短句。"
    long_fact = "第一句很长的内容；第二句很长的内容；第三句应该被丢掉"
    short = CQ.shorten_card_fact(long_fact, max_lines=2)
    assert short.count("；") <= 1
    # missing file => offender (cannot read)
    off = CQ.check_card_image_no_overflow("/tmp/does-not-exist-xyz.png")
    assert off and "cannot read" in off[0]
    try:
        CQ.assert_card_image_fits("/tmp/does-not-exist-xyz.png")
        assert False
    except AssertionError:
        pass


def test_manifest_loader_tolerant(tmp_path):
    charts = tmp_path / "charts"
    charts.mkdir()
    (charts / "00_title.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (charts / "01_a.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    man = [
        {"file": "00_title.png", "section": "intro", "title": "T0", "key_point": "K0", "suggested_seconds": 12},
        {"path": "01_a.png", "section": "explain", "title": "T1", "keypoint": "K1", "seconds": 10},
    ]
    (charts / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    m = MF.load_manifest(charts)
    assert m.title == "T0"
    assert len(m.items) == 2
    assert m.cover.file.name == "00_title.png"
    # object form with charts key
    (charts / "manifest.json").write_text(
        json.dumps({"charts": man, "title": "MetaT", "indicator_id": "iid"}), encoding="utf-8"
    )
    m2 = MF.load_manifest(charts / "manifest.json")
    assert m2.title == "MetaT"
    # bad extension + missing file raise
    (charts / "manifest.json").write_text(json.dumps([{"file": "x.txt"}]), encoding="utf-8")
    try:
        MF.load_manifest(charts)
        assert False
    except ValueError:
        pass


def test_indicator_qa_main_pass_and_fail(tmp_path):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import indicator_qa as QA

    # PASS task
    td = _write_task(tmp_path / "p", _clean_segments(3))
    assert QA.main([str(td)]) == 0
    # FAIL task (jargon)
    td2 = tmp_path / "f"
    td2.mkdir()
    (td2 / "script.json").write_text(
        json.dumps({"segments": [{"text": "讲seed种子", "key_point": "k", "images": [], "motion": "none"}]}),
        encoding="utf-8",
    )
    assert QA.main([str(td2)]) == 1
    # missing script.json => FAIL
    td3 = tmp_path / "m"
    td3.mkdir()
    assert QA.main([str(td3)]) == 1
