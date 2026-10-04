"""Calm BGM rotation / volume / attribution (pure, no render/network)."""

import json
import random
from pathlib import Path

from src.publishers.bili import build_bili_description
from src.services import bgm
from src.services.funnel import build_description


def _make_calm(tmp_path: Path, names: list[str]) -> Path:
    calm = tmp_path / "calm"
    calm.mkdir(parents=True, exist_ok=True)
    for n in names:
        (calm / n).write_bytes(b"fake-audio")
    return calm


def test_list_calm_tracks_auto_pickup(tmp_path):
    calm = _make_calm(tmp_path, ["b.mp3", "a.mp3", "c.wav", "note.txt"])
    tracks = bgm.list_calm_tracks(calm)
    assert [p.name for p in tracks] == ["a.mp3", "b.mp3", "c.wav"]
    # New file later is picked up automatically.
    (calm / "d.flac").write_bytes(b"x")
    assert "d.flac" in [p.name for p in bgm.list_calm_tracks(calm)]


def test_rotation_differs_from_previous_and_persists(tmp_path):
    calm = _make_calm(tmp_path, ["a.mp3", "b.mp3", "c.mp3"])
    ledger = tmp_path / "rot.json"
    first = bgm.select_calm_track(ep="ep33", calm=calm, ledger=ledger)
    second = bgm.select_calm_track(ep="ep34", calm=calm, ledger=ledger)
    assert first["track"] is not None and second["track"] is not None
    assert first["track"].name != second["track"].name
    # Ledger persisted the history.
    data = json.loads(ledger.read_text(encoding="utf-8"))
    assert data["history"]["ep33"] == first["track"].name
    assert data["history"]["ep34"] == second["track"].name
    # Same ep is idempotent.
    again = bgm.select_calm_track(ep="ep33", calm=calm, ledger=ledger)
    assert again["track"].name == first["track"].name


def test_rotation_round_robin_by_ep_number(tmp_path):
    calm = _make_calm(tmp_path, ["a.mp3", "b.mp3", "c.mp3"])
    ledger = tmp_path / "rot.json"
    # Fresh ledger: ep number mod N decides the start (deterministic).
    picks = [bgm.select_calm_track(ep=f"ep{n}", calm=calm, ledger=tmp_path / f"r{n}.json") for n in (33, 34, 35)]
    names = [p["track"].name for p in picks]
    assert len(set(names)) == 3


def test_empty_folder_falls_back(tmp_path):
    calm = tmp_path / "empty"
    calm.mkdir()
    sel = bgm.select_calm_track(ep="ep33", calm=calm, ledger=tmp_path / "r.json")
    assert sel["track"] is None and sel["is_fallback"] is True


def test_random_offset_bounds_and_persisted(tmp_path):
    calm = _make_calm(tmp_path, ["a.mp3"])
    ledger = tmp_path / "r.json"
    rng = random.Random(7)
    off = bgm.random_offset(1300.0, 300.0, rng=rng)
    assert 0.0 <= off <= 1000.0
    assert bgm.random_offset(100.0, 300.0) == 0.0
    # Persisted per ep (stable across calls even with different rng).
    track = calm / "a.mp3"
    o1 = bgm.offset_for_ep("ep33", track, 300.0, calm=calm, ledger=ledger, rng=random.Random(1))
    o2 = bgm.offset_for_ep("ep33", track, 300.0, calm=calm, ledger=ledger, rng=random.Random(99))
    assert o1 == o2


def test_fade_and_target_constants():
    assert bgm.TARGET_BED_LUFS == -42.0
    assert bgm.FADE_IN_S == 2.0
    assert bgm.FADE_OUT_S == 3.0
    assert bgm.NARRATION_REF_LUFS - bgm.TARGET_BED_LUFS == 18.0


def test_gain_for_target_lufs():
    g = bgm.gain_for_target_lufs(-16.1, -48.0)
    assert abs(g["db"] - (-31.9)) < 0.05
    assert 0.02 < g["linear"] < 0.03
    g2 = bgm.gain_for_target_lufs(-20.8, -48.0)
    assert abs(g2["db"] - (-27.2)) < 0.05
    g_none = bgm.gain_for_target_lufs(None, -48.0)
    assert g_none["linear"] == 1.0


def test_loudness_qa_gate():
    ok = bgm.check_bgm_loudness(-42.0, -24.0)
    assert ok["ok"] is True
    bad_bed = bgm.check_bgm_loudness(-46.0, -24.0)
    assert bad_bed["ok"] is False
    assert any("bed" in i for i in bad_bed["issues"])
    too_hot = bgm.check_bgm_loudness(-30.0, -24.0)
    assert too_hot["ok"] is False


def test_tracks_json_structure():
    p = bgm.tracks_metadata_path()
    assert p.is_file(), "assets/bgm/calm/tracks.json must exist"
    raw = json.loads(p.read_text(encoding="utf-8"))
    tracks = raw.get("tracks", {})
    assert len(tracks) >= 2
    for name, info in tracks.items():
        for key in ("title", "artist", "license", "attribution"):
            assert key in info, f"{name} missing {key}"
    # 2026-10-04 owner request: Fluidscape removed (too dynamic / quiet pockets).
    assert "Fluidscape - Kevin MacLeod.mp3" not in tracks
    assert "Drifting at 432 Hz - Unicorn Heads.mp3" in tracks
    assert "Drone in D - Kevin MacLeod.mp3" in tracks


def test_removed_track_never_selected(tmp_path):
    calm = _make_calm(tmp_path, ["Drifting at 432 Hz - Unicorn Heads.mp3", "Drone in D - Kevin MacLeod.mp3"])
    ledger = tmp_path / "r.json"
    for ep in ("ep33", "ep34", "ep35", "ep36", "ep37", "ep38"):
        sel = bgm.select_calm_track(ep=ep, calm=calm, ledger=tmp_path / f"r{ep}.json")
        assert sel["track"] is not None
        assert sel["track"].name != "Fluidscape - Kevin MacLeod.mp3"
    # Real calm dir must not contain the removed file either.
    real_names = [p.name for p in bgm.list_calm_tracks()]
    assert "Fluidscape - Kevin MacLeod.mp3" not in real_names


def test_attribution_kevin_macleod_required():
    meta = bgm.load_tracks_metadata()
    assert "Fluidscape - Kevin MacLeod.mp3" not in meta
    drone = bgm.attribution_for_track("Drone in D - Kevin MacLeod.mp3")
    assert drone is not None and "Drone in D" in drone
    # Unicorn Heads track needs no attribution.
    assert bgm.attribution_for_track("Drifting at 432 Hz - Unicorn Heads.mp3") is None
    # Unknown Kevin MacLeod file still gets a credit (conservative fallback).
    fb = bgm.attribution_for_track("Something - Kevin MacLeod.mp3", calm="/tmp")
    assert fb is not None and "Kevin MacLeod" in fb


def test_description_builders_append_credit():
    credit = "Music: Drone in D by Kevin MacLeod, licensed under CC BY 4.0"
    yt = build_description("标题", "什么指标不赚钱 第33集", music_credit=credit)
    assert credit in yt
    assert "不构成投资建议" in yt
    # No credit -> no music line, still funnel-complete.
    plain = build_description("标题", "什么指标不赚钱 第33集")
    assert "Music:" not in plain
    bili = build_bili_description("正文", music_credit=credit)
    assert "Drone in D" in bili
    assert "http" not in bili  # Bilibili strips links
    bili_plain = build_bili_description("正文")
    assert "Music:" not in bili_plain


def test_parse_ep_number():
    assert bgm.parse_ep_number("ep33") == 33
    assert bgm.parse_ep_number(34) == 34
    assert bgm.normalize_ep("33") == "ep33"
    assert bgm.parse_ep_number(None) is None


def test_excerpt_dynamics_head_quiet_fails():
    # ep35 Fluidscape class: excerpt avg -22.9, head -29.9 (-7dB) must FAIL.
    def fake_measure(track, offset, secs):
        if secs >= 60:
            return -22.9
        return -29.9

    chk = bgm.check_excerpt_dynamics("t.mp3", 0.0, 300.0, measure_fn=fake_measure)
    assert chk["ok"] is False
    assert any("head" in i for i in chk["issues"])


def test_excerpt_dynamics_window_quiet_fails():
    # Head ok, but a mid 10s window sits 10dB below the excerpt avg.
    def fake_measure(track, offset, secs):
        if secs >= 60:
            return -20.0
        if abs(secs - 15.0) < 0.01:
            return -20.5
        # 10s sliding windows: quiet pocket at [20,30).
        if abs(secs - 10.0) < 0.01 and 19.0 <= offset <= 21.0:
            return -30.0
        return -20.2

    chk = bgm.check_excerpt_dynamics("t.mp3", 0.0, 60.0, measure_fn=fake_measure)
    assert chk["ok"] is False
    assert any("window" in i for i in chk["issues"])


def test_excerpt_dynamics_passes_within_6db():
    def fake_measure(track, offset, secs):
        if secs >= 60:
            return -20.0
        return -22.0  # -2dB, within tolerance

    chk = bgm.check_excerpt_dynamics("t.mp3", 0.0, 60.0, measure_fn=fake_measure)
    assert chk["ok"] is True


def test_excerpt_dynamics_allows_unmeasurable():
    chk = bgm.check_excerpt_dynamics("t.mp3", 0.0, 300.0, measure_fn=lambda *a: None)
    assert chk["ok"] is True


def test_resolve_switches_track_when_first_is_quiet(tmp_path):
    calm = _make_calm(tmp_path, ["a.mp3", "b.mp3"])
    ledger = tmp_path / "rot.json"

    def fake_measure(track, offset, secs):
        name = str(track)
        if "a.mp3" in name:
            # a.mp3: excerpt loud avg, head + windows quiet -> always fail.
            if secs >= 30:
                return -18.0
            return -28.0
        # b.mp3: flat, always passes.
        return -19.0

    res = bgm.resolve_bgm_for_episode(
        ep="ep34", needed_secs=120.0, calm=calm, ledger=ledger,
        rng=random.Random(3), measure_fn=fake_measure,
        duration_fn=lambda t: 1000.0,
    )
    assert res["track"] is not None
    assert res["track"].name == "b.mp3"
    data = json.loads(ledger.read_text(encoding="utf-8"))
    assert data["history"]["ep34"] == "b.mp3"
