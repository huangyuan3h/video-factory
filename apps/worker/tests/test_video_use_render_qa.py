"""video-use (browser-use/video-use, MIT) lessons adopted 2026-10-06.

Hard render rules in compose_service (strict font, 30 ms join fades, subtitles
last) and the post-render gate in services/render_qa.py.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.services import compose_service as cs
from src.services import render_qa as rq

FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


# ----------------------------------------------------------------- hard rules
def test_join_fade_is_30ms_and_applied():
    seen = {}

    class Clip:
        def with_effects(self, effects):
            seen["effects"] = effects
            return self

    out = cs._join_fade(Clip())
    assert cs.JOIN_FADE_S == pytest.approx(0.03)
    names = [type(e).__name__ for e in seen["effects"]]
    assert names == ["AudioFadeIn", "AudioFadeOut"]
    assert all(getattr(e, "duration", None) == pytest.approx(0.03) for e in seen["effects"])
    assert isinstance(out, Clip)


def test_join_fade_tolerates_minimal_doubles():
    obj = object()
    assert cs._join_fade(obj) is obj


def test_audio_track_fades_every_narration_segment(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cs, "_join_fade", lambda c: calls.append(c) or c)

    class A:
        duration = 1.0

        def with_start(self, s):
            self.start = s
            return self

    monkeypatch.setattr(cs, "AudioFileClip", lambda p: A())
    monkeypatch.setattr(cs, "CompositeAudioClip", lambda clips: SimpleNamespace(clips=clips))
    logger = SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None)
    segs = [{"index": i, "audio_path": tmp_path / f"s{i}.mp3", "duration": 1.0, "offset": i * 1.5} for i in range(3)]
    cs._create_audio_track(segs, None, 5.0, logger)
    assert len(calls) == 3


def test_require_font_fails_loudly_when_missing(monkeypatch):
    monkeypatch.setattr(cs, "FONT_PATHS", ["/no/such/font.ttf"])
    with pytest.raises(cs.SubtitleFontError, match="no subtitle font"):
        cs._require_font_path(["字幕"])


def test_require_font_rejects_font_without_cjk(monkeypatch):
    dejavu = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    if not Path(dejavu).exists():
        pytest.skip("DejaVu not installed")
    monkeypatch.setattr(cs, "FONT_PATHS", [dejavu])
    assert cs._require_font_path(["plain ascii"]) == dejavu
    with pytest.raises(cs.SubtitleFontError, match="lacks glyphs"):
        cs._require_font_path(["中文字幕"])


def test_missing_glyphs_empty_for_cjk_font():
    path = cs._find_font_path()
    if not path or "DejaVu" in path:
        pytest.skip("no CJK font on this host")
    assert cs._missing_glyphs(path, "第41集 指标 · RSI 69.5%") == []


def test_subtitles_are_the_last_layer():
    src = Path(cs.__file__).read_text(encoding="utf-8")
    assert "all_clips = video_clips + subtitle_clips" in src


# ----------------------------------------------------------------- pure QA helpers
EBUR = """
[Parsed_ebur128_0 @ 0x1] t: 1.0 M: -30.0 S: -120.7 I: -30.0 LUFS
[Parsed_ebur128_0 @ 0x1] Summary:

  Integrated loudness:
    I:         -23.8 LUFS
    Threshold: -34.0 LUFS

  Loudness range:
    LRA:         4.1 LU

  True peak:
    Peak:       -6.0 dBFS
"""


def test_parse_ebur128_summary_only():
    assert rq.parse_ebur128(EBUR) == {"I": -23.8, "LRA": 4.1, "TP": -6.0}
    assert rq.parse_ebur128("") == {"I": None, "LRA": None, "TP": None}


def test_targets_follow_bgm_standard():
    from src.services import bgm

    assert rq._targets() == (float(bgm.NARRATION_REF_LUFS), float(bgm.TARGET_BED_LUFS))
    assert rq._targets()[1] == -42.0


@pytest.mark.parametrize(
    "text,n,ok",
    [("第 41 集", 41, True), ("415 - RSI", 41, True), ("#398", 39, True), ("24", 39, False),
     ("2026 99.5% 1,234", 41, False), ("14", 4, False)],
)
def test_parse_ocr_episode(text, n, ok):
    assert rq.parse_ocr_episode(text, n)["ok"] is ok


def test_episode_verdict_wrong_card_guard():
    assert rq.episode_verdict("415 · MACD", "415 MACD 2026", 41)["ok"] is True
    # ep39 incident: the card says 24 while the full frame happens to contain 39
    bad = rq.episode_verdict("24 · KDJ", "24 KDJ 39", 39)
    assert bad["ok"] is False and bad["line_first"] == "24"


def test_frame_anomalies_black_and_flash():
    rng = np.random.default_rng(0)
    base = rng.integers(80, 160, size=(10, 18, 32)).astype(np.uint8)
    base[:] = base[0]
    assert rq.frame_anomalies(base) == {"black": [], "flash": [], "frames": 10}
    black = base.copy()
    black[4] = 0
    rep = rq.frame_anomalies(black, [i / 10 for i in range(10)])
    assert rep["black"] == [0.4] and rep["flash"] == [0.4]


def test_ink_fraction_detects_text_on_light_and_dark():
    band = np.full((40, 400), 235, np.uint8)
    assert rq.ink_fraction(band) == 0.0
    band[15:25, 100:300] = 20
    assert rq.ink_fraction(band) > rq.SUB_INK_MIN
    dark = np.full((40, 400), 10, np.uint8)
    dark[15:25, 100:300] = 250
    assert rq.ink_fraction(dark) > rq.SUB_INK_MIN


def test_pop_ratio_click_vs_fade():
    sr = 48000
    t = np.arange(sr // 2) / sr
    x = 0.3 * np.sin(2 * np.pi * 220 * t)
    k = len(x) // 2
    smooth = x.copy()
    r, _ = rq.pop_ratio(smooth, k, sr)
    assert r < rq.POP_RATIO_MAX
    clicked = x.copy()
    clicked[k:] = 0.0
    clicked[k - 1] = 0.9
    r2, p2 = rq.pop_ratio(clicked, k, sr)
    assert r2 > rq.POP_RATIO_MAX and p2 > rq.POP_ABS_MIN


def test_read_plan_prefers_timeline_then_task_log(tmp_path):
    (tmp_path / "task.log").write_text(
        "2026-10-06 10:00:00 INFO 音频片段 1: 开始=0.0s, 时长=2.0s\n"
        "2026-10-06 10:00:00 INFO 音频片段 2: 开始=2.5s, 时长=3.1s\n"
        "2026-10-06 10:00:00 INFO 音频片段 2: 开始=2.5s, 时长=3.2s\n",  # re-render: last wins
        encoding="utf-8",
    )
    plan = rq.read_plan(tmp_path)
    assert plan["source"] == "task.log"
    assert plan["segments"] == [(0.0, 2.0), (2.5, 3.2)]
    assert plan["planned"] == pytest.approx(5.7)
    (tmp_path / "timeline.json").write_text(json.dumps({
        "cover_hold": 3.0, "segments": [{"start": 3.0, "duration": 2.0137}, {"start": 5.5137, "duration": 3.2}]}))
    plan = rq.read_plan(tmp_path)
    assert plan["source"] == "timeline.json"
    assert plan["cover_hold"] == 3.0 and plan["planned"] == pytest.approx(8.7137)


def test_ass_cues_shift_to_output_timeline(tmp_path):
    (tmp_path / "subtitles.ass").write_text(
        "[Events]\nDialogue: 0,0:00:01.50,0:00:03.00,Default,,0,0,0,,你好\n", encoding="utf-8")
    assert rq.ass_cues(tmp_path, 3.0) == [(4.5, 6.0)]


def test_propose_fix_only_audio_issues():
    rep = {"checks": {"true_peak_ok": False, "bed_loudness_ok": False},
           "metrics": {"loudness": {"mix_TP": -0.2, "bed_I": -39.0, "bed_target": -42.0}}}
    fix = rq.propose_fix(rep, {})
    assert fix["narration_gain_db"] == pytest.approx(-1.3)
    assert fix["bed_gain_adjust_db"] == pytest.approx(-3.0)
    assert fix["remixed"] is True
    assert rq.propose_fix({"checks": {"no_join_pops": False}, "metrics": {}}, {})["remixed"] is True
    # visuals / OCR / duration are never auto-fixed
    assert rq.propose_fix({"checks": {"cut_frames_clean": False, "cover_episode_ocr": False}, "metrics": {}}, {}) is None


def test_fix_loop_caps_at_three_rounds_and_flags_human(tmp_path):
    fixes = []

    def qa(_d):
        return {"pass": False, "checks": {"true_peak_ok": False}, "issues": ["true_peak_ok"],
                "metrics": {"loudness": {"mix_TP": 0.0}}}

    rep = rq.fix_loop(tmp_path, qa=qa, fixer=lambda d, p: fixes.append(p))
    assert len(rep["rounds"]) == 3 and len(fixes) == 2
    assert rep["needs_human"] is True


def test_fix_loop_stops_when_fixed(tmp_path):
    state = {"n": 0}

    def qa(_d):
        state["n"] += 1
        ok = state["n"] > 1
        return {"pass": ok, "checks": {"no_join_pops": ok}, "issues": [], "metrics": {}}

    rep = rq.fix_loop(tmp_path, qa=qa, fixer=lambda d, p: None)
    assert rep["pass"] and not rep["needs_human"] and len(rep["rounds"]) == 2


def test_fix_loop_no_auto_fix_for_visual_issue(tmp_path):
    rep = rq.fix_loop(tmp_path, qa=lambda d: {"pass": False, "checks": {"cut_frames_clean": False},
                                               "issues": ["cut_frames_clean"], "metrics": {}},
                      fixer=lambda d, p: pytest.fail("must not remix"))
    assert len(rep["rounds"]) == 1 and rep["needs_human"]


# ----------------------------------------------------------------- tiny e2e (ffmpeg)
def _ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


@pytest.fixture
def tiny_task(tmp_path):
    if not FFMPEG:
        pytest.skip("ffmpeg not installed")
    for i, f in enumerate((300, 450)):
        _ff("-f", "lavfi", "-i", f"sine=f={f}:d=1.5:sample_rate=44100", "-af",
            "volume=0.12,aresample=44100", "-c:a", "libmp3lame", "-b:a", "128k", str(tmp_path / f"segment_{i}.mp3"))
    d0 = rq.stream_durations(tmp_path / "segment_0.mp3")["format"]
    d1 = rq.stream_durations(tmp_path / "segment_1.mp3")["format"]
    segs = [(0.5, d0), (0.5 + d0 + 0.5, d1)]
    total = round(segs[-1][0] + d1, 3)
    (tmp_path / "timeline.json").write_text(json.dumps(
        {"cover_hold": 0.5, "segments": [{"start": s, "duration": d} for s, d in segs]}))
    _ff("-f", "lavfi", "-i", f"testsrc2=s=320x180:r=30:d={total}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(tmp_path / "video_only.mp4"))
    shutil.copy2(tmp_path / "video_only.mp4", tmp_path / "output.mp4")
    rq.remix_audio(tmp_path, {})
    (tmp_path / "output.pre_fix.mp4").unlink()
    return tmp_path, segs, total


def test_e2e_clean_render_passes_frame_pop_duration(tiny_task):
    task, segs, total = tiny_task
    rep = rq.run_render_qa(task, band_frac=0.12)
    c = rep["checks"]
    assert c["duration_matches_plan"] and c["video_stream_matches_plan"]
    assert c["cut_frames_clean"], rep["cuts"]
    assert c["no_join_pops"], rep["joins"]
    assert rep["metrics"]["loudness"]["mix_TP"] <= -1.0


def test_e2e_detects_black_frames_and_click_then_remix_fixes_click(tiny_task):
    task, segs, total = tiny_task
    cut = segs[1][0]
    broken = task / "broken.mp4"
    # black frames right after the 2nd cut + a hard click at the 2nd narration end
    click_t = segs[1][0] + segs[1][1]
    _ff("-i", str(task / "output.mp4"), "-vf",
        f"drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='between(t,{cut + 0.2},{cut + 0.4})'",
        "-af", f"aeval='val(ch)+0.8*between(t,{click_t:.4f},{click_t + 0.0006:.4f})':c=same",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(broken))
    rep = rq.run_render_qa(task, band_frac=0.12, video=broken)
    assert rep["checks"]["cut_frames_clean"] is False
    assert any(x["black"] for x in rep["cuts"])
    # audio-only defect: remix from stems removes it and keeps the video stream
    _ff("-i", str(task / "output.mp4"), "-c:v", "copy", "-af",
        f"aeval='val(ch)+0.8*between(t,{click_t:.4f},{click_t + 0.0006:.4f})':c=same", "-c:a", "aac",
        str(task / "clicked.mp4"))
    shutil.move(task / "clicked.mp4", task / "output.mp4")
    assert rq.run_render_qa(task, band_frac=0.12)["checks"]["no_join_pops"] is False
    rep2 = rq.fix_loop(task, band_frac=0.12)
    assert rep2["checks"]["no_join_pops"] is True
    assert (task / "output.pre_fix.mp4").exists()
    assert len(rep2["rounds"]) == 2


def test_cli_writes_report_and_exit_code(tiny_task, capsys):
    import importlib.util

    task, _segs, _total = tiny_task
    spec = importlib.util.spec_from_file_location(
        "render_qa_cli", Path(__file__).resolve().parent.parent / "scripts" / "render_qa.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rc = mod.main([str(task), "--json"])
    data = json.loads((task / "render_qa.json").read_text(encoding="utf-8"))
    assert rc == (0 if data["pass"] else 1)
    printed = json.loads(capsys.readouterr().out)
    assert printed["checks"]["cut_frames_clean"] is True
    assert "needs_human" in printed


def test_renderer_writes_output_timeline_plan():
    from src.services import video_service as vs

    src = Path(vs.__file__).read_text(encoding="utf-8")
    assert '"timeline.json"' in src and "_start + float(sa.get(\"offset\"" in src
