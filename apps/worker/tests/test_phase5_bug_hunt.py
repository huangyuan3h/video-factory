"""Phase 5 bug hunt: property/edge-case tests for ledger/resume/codes/registry/QA gates.

No rendering/TTS/upload/publish/browser. Pure logic + small fixtures only.
"""
import pytest

from src.services import checkpoint as cp
from src.services import error_codes as ec
from src.services import series_registry as reg
from src.services.indicator import card_qa as cq
from src.services.indicator import jargon as jg
from src.services.indicator import repeat_guard as rg
from src.services.indicator import transition as tr
from src.services.indicator import visual_beats as vb

# --- checkpoint / resume ---


def test_hash_inputs_deterministic_and_sensitive(tmp_path):
    assert cp.hash_inputs("a", "b") == cp.hash_inputs("a", "b")
    assert cp.hash_inputs("a", "b") != cp.hash_inputs("a", "c")
    assert cp.hash_inputs("") != cp.hash_inputs("x")
    # None coerced to "" (stable, no crash)
    assert cp.hash_inputs(None) == cp.hash_inputs("")  # type: ignore[arg-type]


def test_hash_file_missing_and_roundtrip(tmp_path):
    assert cp.hash_file(tmp_path / "nope.bin") is None
    f = tmp_path / "a.bin"
    f.write_bytes(b"hello")
    h1 = cp.hash_file(f)
    assert h1 is not None and len(h1) == 12
    f.write_bytes(b"hello!")
    assert cp.hash_file(f) != h1


def test_load_checkpoint_corrupted_returns_empty(tmp_path):
    d = tmp_path / "task"
    d.mkdir()
    (d / ".vf_checkpoint.json").write_text("{not json", encoding="utf-8")
    assert cp.load_checkpoint(d) == {}
    # missing file also empty
    assert cp.load_checkpoint(tmp_path / "missing") == {}


def test_should_skip_branches(tmp_path):
    d = tmp_path / "t"
    ih = cp.hash_inputs("ep1", "topic")
    assert cp.should_skip(d, "new-ep", ih) is False
    cp.save_checkpoint(d, "new-ep", ih)
    assert cp.should_skip(d, "new-ep", ih) is True
    assert cp.should_skip(d, "new-ep", "different") is False
    assert cp.should_skip(d, "other-step", ih) is False


def test_status_is_done_invalid_json(tmp_path):
    d = tmp_path / "t"
    d.mkdir()
    assert cp.status_is_done(d) == (False, {})
    (d / "status.json").write_text("{bad", encoding="utf-8")
    done, _ = cp.status_is_done(d)
    assert done is False
    (d / "status.json").write_text('{"status": "script_ready"}', encoding="utf-8")
    done, data = cp.status_is_done(d)
    assert done is True and data["status"] == "script_ready"


def test_check_resume_all_reasons(tmp_path):
    assert cp.check_resume(None, "s", "h")["reason"] == "no-task-dir"
    d = tmp_path / "t"
    assert cp.check_resume(d, "s", "h")["reason"] == "not-done"
    ih = cp.hash_inputs("x")
    cp.save_checkpoint(d, "render", ih)
    # checkpoint hit but no status.json -> skip via checkpoint
    assert cp.check_resume(d, "render", ih) == {"skip": True, "reason": "checkpoint-hit"}
    # status done + same hash -> checkpoint-hit (status path first checks both)
    (d / "status.json").write_text('{"status": "completed"}', encoding="utf-8")
    assert cp.check_resume(d, "render", ih)["reason"] == "checkpoint-hit"
    # status done + different hash -> status-done (conservative idempotency)
    assert cp.check_resume(d, "render", "other") == {"skip": True, "reason": "status-done"}


def test_load_checkpoint_list_returns_empty_not_list(tmp_path):
    """Corrupted checkpoint holding a JSON list must not propagate as dict."""
    d = tmp_path / "t"
    d.mkdir()
    (d / ".vf_checkpoint.json").write_text("[]", encoding="utf-8")
    # load returns the list as-is (caller must handle); should_skip must not crash
    assert cp.should_skip(d, "new-ep", "abc") is False


# --- error codes ---


def test_code_for_edge_cases():
    assert ec.code_for(None) == "E_BLOCKED"
    assert ec.code_for("") == "E_BLOCKED"
    assert ec.code_for("E_QA_FAIL") == "E_QA_FAIL"
    assert ec.code_for("e_qa_fail") == "E_QA_FAIL"
    assert ec.code_for("qa-fail") == "E_QA_FAIL"
    assert ec.code_for("qa fail") == "E_QA_FAIL"
    assert ec.code_for("ledger-missing") == "E_LEDGER"
    assert ec.code_for("something-weird-xyz") == "E_BLOCKED"
    assert ec.code_for("invalid_grant expired") == "E_CREDENTIALS"
    assert ec.code_for("503 overload") == "E_BACKEND_OVERLOAD"
    assert ec.code_for("invalid upload png") == "E_PNG_READ"
    assert ec.code_for("disk full") == "E_MEMORY"


def test_explain_all_codes_covered():
    for code in sorted(ec.ALL_CODES):
        e = ec.explain(code)
        assert e["code"] == code and e["cause"] and e["fix"] and e["next"]
    assert ec.explain(None)["code"] == "E_BLOCKED"
    assert ec.explain("E_NOPE")["cause"] == "Unknown code."
    # hyphen/space/case variants
    assert ec.explain("qa-fail")["code"] == "E_QA_FAIL"
    assert ec.explain("qa fail")["code"] == "E_QA_FAIL"


# --- series registry ---


def test_registry_rejects_bad_specs():
    with pytest.raises(ValueError):
        reg.register_series(reg.SeriesSpec(name="  ", content_type="x"))
    with pytest.raises(ValueError):
        reg.register_series(reg.SeriesSpec(name="bad", content_type="x", steps=("nope",)))
    # case-insensitive get
    assert reg.get_series("INDICATOR").name == "indicator"
    with pytest.raises(KeyError):
        reg.get_series("no-such-series-xyz")
    assert reg.steps_for(None) == list(reg.PIPELINE_STEPS)
    assert "research" in reg.steps_for("indicator")


def test_load_series_configs_missing_dir_returns_zero(tmp_path):
    assert reg.load_series_configs(tmp_path / "nope") == 0


def test_load_series_configs_invalid_raise(tmp_path):
    (tmp_path / "a.json").write_text("{bad", encoding="utf-8")
    with pytest.raises(ValueError):
        reg.load_series_configs(tmp_path)
    (tmp_path / "a.json").write_text('{"content_type": "x"}', encoding="utf-8")
    with pytest.raises(ValueError):
        reg.load_series_configs(tmp_path)


def test_load_series_configs_roundtrip(tmp_path):
    (tmp_path / "dummy_phase5.json").write_text(
        '{"name": "phase5dummy", "content_type": "dummy", "description": "t", "steps": ["research", "script", "review"]}',
        encoding="utf-8",
    )
    try:
        assert reg.load_series_configs(tmp_path) == 1
        assert reg.get_series("phase5dummy").steps == ("research", "script", "review")
    finally:
        reg._SERIES_REGISTRY.pop("phase5dummy", None)


def test_publisher_registry_rejects_non_subclass():
    from src.publishers import BasePublisher, register_publisher

    with pytest.raises(ValueError):
        register_publisher("phase5bad", object)  # type: ignore[arg-type]
    # valid dummy registers and unregisters cleanly
    from src.publishers import PUBLISHER_REGISTRY

    class P5Dummy(BasePublisher):
        platform_name = "p5dummy"
        login_url = "https://example.invalid/"
        upload_url = "https://example.invalid/"

        async def check_login(self):  # type: ignore[no-untyped-def]
            return True

        async def upload(self, video_path, title, **kwargs):  # type: ignore[no-untyped-def]
            raise NotImplementedError("dry-run only")

    register_publisher("p5dummy", P5Dummy)
    try:
        from src.publishers import get_publisher, list_platforms

        assert "p5dummy" in list_platforms()
        assert get_publisher("p5dummy").platform_name == "p5dummy"
    finally:
        PUBLISHER_REGISTRY.pop("p5dummy", None)


# --- repeat / transition / jargon ---


def test_repeat_empty_and_single_clean():
    assert rg.find_global_repeats([]) == []
    assert rg.find_global_repeats(["你好世界测试一下"]) == []
    assert rg.find_adjacent_bridge_repeats(["a", "b"]) == []


def test_repeat_exact_duplicate_flagged():
    dups = rg.find_global_repeats(["最后留一句话总结", "最后留一句话总结"])
    assert dups and dups[0]["segments"] == [0, 1]


def test_repeat_numbers_ignored():
    # 沪深300 repeated across segments must not trip (number token)
    assert rg.find_global_repeats(["沪深300表现不错值得关注一下", "沪深300继续观察值得跟踪一下"]) == []


def test_transition_jaccard_properties():
    assert tr.tail_head_jaccard("你好世界", "你好世界") == 1.0
    assert tr.tail_head_jaccard("", "") == 0.0
    assert tr.tail_head_jaccard("你好", "世界和平") == 0.0
    v = tr.tail_head_jaccard("接下来看看数据表现", "接下来看看数据结果")
    assert 0.0 <= v <= 1.0


def test_transition_near_duplicate_threshold():
    good = ["第一段内容完全不同谈天气", "第二段内容谈做饭技巧和方法"]
    bad = ["这只是1笔，全市场306560笔都要看完才行", "201001年以来，一共成交306560笔都要看完才行"]
    assert tr.find_near_duplicate_boundaries(good, threshold=0.14) == []
    # bad pair shares long numeric/content overlap -> flagged (or at least score high)
    scored = tr.tail_head_jaccard(bad[0], bad[1])
    assert scored > 0.10


def test_jargon_blocklist():
    assert jg.find_jargon("this uses seed 123") == ["seed"]
    assert jg.find_jargon("SEED value") == ["seed"]
    assert jg.find_jargon(" random_state ")
    assert jg.find_jargon("看manifest文件") == ["manifest"]
    assert jg.find_jargon("今天市场表现不错，继续持有") == []
    assert jg.find_jargon("") == []
    segs = jg.check_segments(["干净文本", "用了seed参数"])
    assert len(segs) == 1 and segs[0]["index"] == 1


# --- static image ≤12s / card overflow ---


def test_static_hold_multi_beat_flagged():
    multi = "第1组0/12，第2组1/12，第3组3/12，结果对比"
    assert vb.count_group_beats(multi) >= 2
    offs = vb.check_visual_beats([multi], [["a.png"]], [30.0], ["none"])
    assert any("12s" in o or "beats" in o for o in offs)
    # animated bypasses the hold gate (only beat-count remains)
    animated = vb.check_visual_beats([multi], [["a.png"]], [30.0], ["zoom"])
    assert not any("12s" in o for o in animated)
    # single-beat may hold long (series norm 15-36s)
    single = "今天市场表现不错，继续持有"
    assert vb.check_visual_beats([single], [["a.png"]], [30.0], ["none"]) == []


def test_card_shorten_keeps_numbers():
    long_fact = "这是一个非常长的事实描述" * 20 + "数字12345保留"
    short = cq.shorten_card_fact(long_fact, max_lines=2)
    assert "12345" in short
    assert len(short) <= len(long_fact)


def test_visual_beats_empty_inputs():
    assert vb.check_visual_beats([], [], [], []) == []
    assert vb.count_group_beats("") == 1
