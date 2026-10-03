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
    assert bgm.TARGET_BED_LUFS == -48.0
    assert bgm.FADE_IN_S == 2.0
    assert bgm.FADE_OUT_S == 3.0
    assert bgm.NARRATION_REF_LUFS - bgm.TARGET_BED_LUFS == 24.0


def test_gain_for_target_lufs():
    g = bgm.gain_for_target_lufs(-16.1, -48.0)
    assert abs(g["db"] - (-31.9)) < 0.05
    assert 0.02 < g["linear"] < 0.03
    g2 = bgm.gain_for_target_lufs(-20.8, -48.0)
    assert abs(g2["db"] - (-27.2)) < 0.05
    g_none = bgm.gain_for_target_lufs(None, -48.0)
    assert g_none["linear"] == 1.0


def test_loudness_qa_gate():
    ok = bgm.check_bgm_loudness(-48.0, -24.0)
    assert ok["ok"] is True
    bad_bed = bgm.check_bgm_loudness(-43.8, -24.0)
    assert bad_bed["ok"] is False
    assert any("bed" in i for i in bad_bed["issues"])
    too_hot = bgm.check_bgm_loudness(-30.0, -24.0)
    assert too_hot["ok"] is False


def test_tracks_json_structure():
    p = bgm.tracks_metadata_path()
    assert p.is_file(), "assets/bgm/calm/tracks.json must exist"
    raw = json.loads(p.read_text(encoding="utf-8"))
    tracks = raw.get("tracks", {})
    assert len(tracks) >= 3
    for name, info in tracks.items():
        for key in ("title", "artist", "license", "attribution"):
            assert key in info, f"{name} missing {key}"


def test_attribution_kevin_macleod_required():
    fluid = bgm.attribution_for_track("Fluidscape - Kevin MacLeod.mp3")
    assert fluid is not None and "Fluidscape" in fluid and "Kevin MacLeod" in fluid
    drone = bgm.attribution_for_track("Drone in D - Kevin MacLeod.mp3")
    assert drone is not None and "Drone in D" in drone
    # Unicorn Heads track needs no attribution.
    assert bgm.attribution_for_track("Drifting at 432 Hz - Unicorn Heads.mp3") is None
    # Unknown Kevin MacLeod file still gets a credit (conservative fallback).
    fb = bgm.attribution_for_track("Something - Kevin MacLeod.mp3", calm="/tmp")
    assert fb is not None and "Kevin MacLeod" in fb


def test_description_builders_append_credit():
    credit = "Music: Fluidscape by Kevin MacLeod, licensed under CC BY 4.0"
    yt = build_description("标题", "什么指标不赚钱 第33集", music_credit=credit)
    assert credit in yt
    assert "不构成投资建议" in yt
    # No credit -> no music line, still funnel-complete.
    plain = build_description("标题", "什么指标不赚钱 第33集")
    assert "Music:" not in plain
    bili = build_bili_description("正文", music_credit=credit)
    assert "Fluidscape" in bili
    assert "http" not in bili  # Bilibili strips links
    bili_plain = build_bili_description("正文")
    assert "Music:" not in bili_plain


def test_parse_ep_number():
    assert bgm.parse_ep_number("ep33") == 33
    assert bgm.parse_ep_number(34) == 34
    assert bgm.normalize_ep("33") == "ep33"
    assert bgm.parse_ep_number(None) is None
