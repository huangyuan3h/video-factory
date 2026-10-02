"""Phase 4 coverage boost: repeat_guard / script / visual_beats defensive branches."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from src.core.task_logger import TaskLogger
from src.services.indicator import generate_indicator_script
from src.services.indicator import repeat_guard as rg
from src.services.indicator import script as script_mod
from src.services.indicator import visual_beats as beats
from src.services.indicator.manifest import IndicatorManifest, ManifestItem

# --------------------------------------------------------------------------- #
# repeat_guard
# --------------------------------------------------------------------------- #


def test_presenter_greeting_pair_is_skipped():
    sent = "大家好，我是躺平的老黄，今天聊一聊指标回测。"
    out = rg.find_global_repeats([sent, "中间聊点别的回测数字。", sent], min_len=6)
    assert out == []


def test_adjacent_bridge_suffix_prefix_detected():
    prev = "先看随机对比"
    nxt = "看随机对比的结果很差。"
    out = rg.find_adjacent_bridge_repeats([prev, nxt])
    assert out and out[0]["phrase"] == "看随机对比"


def test_strip_bridge_duplicates_adjacent_and_closer():
    segs = ["先看结论，换个角度", "换个角度，再看第二组的结果。"]
    fixed = rg.strip_bridge_duplicates(segs)
    assert fixed[1] != segs[1]  # leading bridge opening removed from seg2
    segs2 = ["前面讲了很多，最后留一句话。", "最后留一句话，别追高。"]
    fixed2 = rg.strip_bridge_duplicates(segs2)
    assert "最后留一句话" not in fixed2[0]
    assert "最后留一句话" in fixed2[1]


def test_check_transcript_str_and_list():
    rep = "仓位比择时更重要，仓位决定收益。"
    multi = f"先讲结论。{rep}再讲数字。{rep}收尾。"
    out = rg.check_transcript_no_repeats(multi)
    assert out["global"] or out["adjacent"]
    out2 = rg.check_transcript_no_repeats(["第一段讲回测数字。", "第二段讲不同年份。"])
    assert out2["global"] == []
    single = rg.check_transcript_no_repeats("只有一句话。")
    assert single["global"] == []


# --------------------------------------------------------------------------- #
# script.py pure helpers
# --------------------------------------------------------------------------- #


def test_build_user_prompt_with_context(tmp_path):
    from src.services.indicator.manifest import IndicatorManifest

    png = tmp_path / "c.png"
    Image.new("RGB", (20, 12), (1, 2, 3)).save(png)
    manifest = IndicatorManifest(
        charts_dir=tmp_path,
        items=[],
        title="T",
        indicator_id="x",
        manifest_path=tmp_path / "manifest.json",
    )
    req = SimpleNamespace(title="T", content="补充背景材料")
    prompt = script_mod._build_user_prompt(manifest, req, [])
    assert "补充背景" in prompt


def test_map_segments_skips_garbage():
    mapped = script_mod._map_segments([None, {"index": "bogus", "text": "  正文  "}, {"index": 9, "text": "越界"}], 3)
    assert mapped[1] == "正文"
    assert 9 not in mapped


def test_append_key_point_branches():
    assert script_mod._append_key_point("正文", "") == "正文"
    assert script_mod._append_key_point("正文", "要点") == "正文。要点。"
    assert script_mod._append_key_point("正文。", "要点。") == "正文。要点。"


# --------------------------------------------------------------------------- #
# script.py guard rails: generic errors are swallowed, ValueError fails loudly
# --------------------------------------------------------------------------- #


def _png(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    Image.new("RGB", (20, 12), (1, 2, 3)).save(p)
    return p


def _manifest(tmp_path, key_point="GDP 增长 15.5%"):
    item = ManifestItem(index=0, file=_png(tmp_path, "a.png"), section="explain",
                        title="图", key_point=key_point, suggested_seconds=20)
    return IndicatorManifest(charts_dir=tmp_path, items=[item], title="T",
                             indicator_id="x", manifest_path=tmp_path / "manifest.json")


class _FakeAI:
    def __init__(self, responses):
        self._responses = list(responses)

    async def complete_json(self, system_prompt, user_prompt, max_tokens=4000):
        return self._responses.pop(0) if self._responses else {}


def _request(**overrides):
    base = dict(title="T", content="", target_seconds=None)
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_script_guards_swallow_generic_errors(tmp_path, monkeypatch):
    import src.services.indicator.jargon as jargon_mod
    import src.services.indicator.transition as transition_mod
    import src.services.indicator.visual_beats as beats_mod

    monkeypatch.setattr(rg, "strip_bridge_duplicates", lambda segs: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(transition_mod, "run_transition_pass", _boom_async)
    monkeypatch.setattr(rg, "assert_no_repeats", lambda texts: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(transition_mod, "assert_transitions_coherent", lambda texts: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(jargon_mod, "assert_no_jargon", lambda texts: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(beats_mod, "assert_visual_beats", lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
    ai = _FakeAI([{"segments": [{"index": 0, "text": "GDP 增长 15.5%，表现不错。"}]}])
    script = await generate_indicator_script(ai, _manifest(tmp_path), _request(), TaskLogger("boost-swallow", tmp_path))
    assert len(script.segments) == 1


async def _boom_async(*a, **k):
    raise RuntimeError("boom")


@pytest.mark.asyncio
@pytest.mark.parametrize("module_name,attr", [
    ("src.services.indicator.repeat_guard", "assert_no_repeats"),
    ("src.services.indicator.transition", "assert_transitions_coherent"),
    ("src.services.indicator.jargon", "assert_no_jargon"),
    ("src.services.indicator.visual_beats", "assert_visual_beats"),
])
async def test_script_guards_value_error_fails_loudly(tmp_path, monkeypatch, module_name, attr):
    import importlib

    mod = importlib.import_module(module_name)
    monkeypatch.setattr(mod, attr, lambda *a, **k: (_ for _ in ()).throw(ValueError("guard FAIL")))
    ai = _FakeAI([{"segments": [{"index": 0, "text": "GDP 增长 15.5%，表现不错。"}]}])
    with pytest.raises(ValueError, match="guard FAIL"):
        await generate_indicator_script(ai, _manifest(tmp_path), _request(), TaskLogger("boost-loud", tmp_path))


# --------------------------------------------------------------------------- #
# visual_beats defensive fallbacks
# --------------------------------------------------------------------------- #


def test_cue_holds_tolerate_garbage_cues():
    text = "第一组的结果很差，第二组同样跑输。"
    cues = [{"start": "bogus", "end": "bogus", "text": "第一组"},
            {"start": "also-bogus", "text": "第二组"}]
    holds = beats.compute_cue_based_holds(text, 10.0, cues, 2)
    assert holds and abs(sum(holds) - 10.0) < 1e-6


def test_boundary_holds_tolerate_garbage_offsets():
    text = "第一组的结果很差，第二组同样跑输。"
    holds = beats.compute_holds_from_boundaries(text, 10.0, [{"offset": "bogus", "duration": 1.0, "text": "第一组"}], 2)
    assert holds and abs(sum(holds) - 10.0) < 1e-6


def test_beat_sync_skips_unparseable_cues_and_reports():
    text = "第一组的结果很差，第二组同样跑输。"
    cues = [{"start": "x", "end": "y", "text": "别的"}]
    out = beats.check_beat_sync(text, ["a.png", "b.png"], 0.0, [5.0, 5.0], cues)
    assert out, "expected an offender when no cue mentions the beat"


def test_beat_sync_never_crashes_on_garbage_holds():
    text = "第一组的结果很差，第二组同样跑输。"
    out = beats.check_beat_sync(text, ["a.png", "b.png"], 0.0, "ab", [{"start": 0.0, "end": 9.0, "text": "第一组第二组"}])
    assert out and out[0].startswith("beat-sync check error")
