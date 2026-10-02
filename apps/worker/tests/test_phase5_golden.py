"""Phase 5 golden tests: script/subtitle timing logic with small fixtures.

No network/TTS/render. Fixtures are tiny and deterministic; expected values
were captured from the current implementation (see comments) and assert the
contract: contiguity, exact end times, even-split fallback.
"""
from types import SimpleNamespace

from src.core.subtitle_gen import SubtitleGenerator
from src.services.indicator.manifest import IndicatorManifest, ManifestItem
from src.services.indicator.script import _make_segment, _target_seconds


def test_subtitle_contiguous_two_segments_golden():
    gen = SubtitleGenerator()
    segs = [
        {"text": "你好世界测试一下字幕切分逻辑", "duration": 10.0, "offset": 0.0},
        {"text": "第二段内容继续测试时间连续性", "duration": 8.0, "offset": 10.0},
    ]
    subs = gen.generate_for_segments(segs)
    assert len(subs) == 2
    # Golden: single-line segments map 1:1 with exact times.
    assert (subs[0].start_time, subs[0].end_time) == (0.0, 10.0)
    assert (subs[1].start_time, subs[1].end_time) == (10.0, 18.0)
    assert subs[-1].end_time == 18.0
    assert [s.index for s in subs] == [1, 2]


def test_subtitle_implicit_offset_running_sum():
    gen = SubtitleGenerator()
    segs = [
        {"text": "第一段内容测试", "duration": 5.0},
        {"text": "第二段内容测试", "duration": 7.0},
    ]
    subs = gen.generate_for_segments(segs)
    assert subs[0].start_time == 0.0
    assert subs[0].end_time == 5.0
    assert subs[1].start_time == 5.0
    assert subs[1].end_time == 12.0


def test_subtitle_empty_golden():
    assert SubtitleGenerator().generate_for_segments([]) == []


def test_target_seconds_suggested_and_even_split():
    def item(seconds):
        return ManifestItem(index=0, file="a.png", section="s", title="t", key_point="k", suggested_seconds=seconds)

    man_all = IndicatorManifest(charts_dir="/tmp", items=[item(30), item(20)], title="t", indicator_id="x")
    assert _target_seconds(man_all, SimpleNamespace(target_seconds=300)) == [30, 20]

    man_missing = IndicatorManifest(charts_dir="/tmp", items=[item(0), item(0)], title="t", indicator_id="x")
    # Golden: 300 total over 2 missing -> [150, 150] (even split).
    assert _target_seconds(man_missing, SimpleNamespace(target_seconds=300)) == [150, 150]

    man_mixed = IndicatorManifest(charts_dir="/tmp", items=[item(100), item(0)], title="t", indicator_id="x")
    # Golden: known 100, remaining 200 -> 1 missing gets 200.
    assert _target_seconds(man_mixed, SimpleNamespace(target_seconds=300)) == [100, 200]


def test_make_segment_structure_golden():
    from pathlib import Path

    item = ManifestItem(index=2, file=Path("c.png"), section="sec", title="标题", key_point="要点", suggested_seconds=12)
    seg = _make_segment(item, " narration 文本 ", 12)
    assert seg.images == ["c.png"]
    assert seg.motion == "none"
    assert seg.section == "sec"
    assert seg.chart == "c.png"
    assert "narration" in seg.text or "文本" in seg.text
    # str file also works (defensive: Path(str) handling)
    item_str = ManifestItem(index=2, file="c.png", section="sec", title="标题", key_point="要点", suggested_seconds=12)  # type: ignore[arg-type]
    assert _make_segment(item_str, "t", 12).chart == "c.png"
