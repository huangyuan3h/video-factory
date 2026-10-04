"""Calm BGM rotation for indicator episodes (Yuan 2026-10-03).

Each new episode uses a different calm track than the previous episode
(round-robin by episode number / least-recently-used, persisted in
``state/bgm_rotation.json``). Long tracks start at a random offset, fade in
2s / fade out 3s, and loop when shorter than the narration.

Volume: the bed is loudness-normalized per track to ``TARGET_BED_LUFS``
(``-42`` LUFS integrated, ~18 dB under the ``-24`` LUFS narration) so all
tracks sit at the same level. The mix is a static bed under speech; the
pipeline has no true sidechain, so "ducking" is the 18 dB static offset
(light ducking by level).

Attribution: per-track metadata lives in ``assets/bgm/calm/tracks.json``.
Kevin MacLeod tracks need a CC BY credit line; the YouTube/Bilibili
description builders append it automatically for the track used.
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

TARGET_BED_LUFS = -42.0  # 2026-10-04 owner picked B (~18 dB under narration)
NARRATION_REF_LUFS = -24.0
TARGET_DELTA_DB = NARRATION_REF_LUFS - TARGET_BED_LUFS  # 18 dB under narration
FADE_IN_S = 2.0
FADE_OUT_S = 3.0

# 2026-10-04 owner request (drop Fluidscape): guard against quiet pockets.
# The selected excerpt's head-15s and every 10s window must sit within 6 dB
# below the excerpt integrated level; else retry another offset, then another
# track. See check_excerpt_dynamics / find_dynamics_safe_offset.
HEAD_CHECK_SECS = 15.0
WINDOW_CHECK_SECS = 10.0
WINDOW_CHECK_STRIDE_SECS = 5.0
MAX_QUIET_DROP_DB = 6.0
MAX_OFFSET_TRIES = 5

SUPPORTED_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".opus"}

OLD_BED_FILENAME = "Ambiment - The Ambient - Kevin MacLeod.mp3"


def repo_root() -> Path:
    """Repo root (``.../video-factory-p2``) derived from this file."""
    return Path(__file__).resolve().parents[4]


def calm_dir(calm: Path | str | None = None) -> Path:
    """Calm-track folder (env ``VF_BGM_CALM_DIR`` wins, for tests)."""
    env = os.environ.get("VF_BGM_CALM_DIR", "").strip()
    if calm is not None:
        return Path(calm)
    if env:
        return Path(env)
    return repo_root() / "assets" / "bgm" / "calm"


def ledger_path(path: Path | str | None = None) -> Path:
    """Rotation ledger file (env ``VF_BGM_LEDGER`` wins, for tests)."""
    env = os.environ.get("VF_BGM_LEDGER", "").strip()
    if path is not None:
        return Path(path)
    if env:
        return Path(env)
    return repo_root() / "state" / "bgm_rotation.json"


def tracks_metadata_path(calm: Path | str | None = None) -> Path:
    return calm_dir(calm) / "tracks.json"


def list_calm_tracks(calm: Path | str | None = None) -> list[Path]:
    """All audio files in the calm folder, sorted (auto-picks new files)."""
    base = calm_dir(calm)
    if not base.is_dir():
        return []
    out: list[Path] = []
    for p in base.iterdir():
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
            out.append(p)
    return sorted(out)


def parse_ep_number(ep: str | int | None) -> int | None:
    """``ep33`` / ``33`` / ``33`` -> 33, else None."""
    if ep is None:
        return None
    if isinstance(ep, int):
        return ep if ep >= 0 else None
    m = re.search(r"(\d+)", str(ep))
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def normalize_ep(ep: str | int | None) -> str | None:
    n = parse_ep_number(ep)
    return f"ep{n}" if n is not None else None


def _default_ledger() -> dict:
    return {"last_index": -1, "last_track": None, "history": {}, "offsets": {}}


def load_ledger(path: Path | str | None = None) -> dict:
    """Load the rotation ledger (missing/corrupt -> fresh defaults)."""
    lp = ledger_path(path)
    data = _default_ledger()
    try:
        if lp.is_file():
            raw = json.loads(lp.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                if isinstance(raw.get("last_index"), int):
                    data["last_index"] = raw["last_index"]
                if isinstance(raw.get("last_track"), str):
                    data["last_track"] = raw["last_track"]
                if isinstance(raw.get("history"), dict):
                    data["history"] = {str(k): str(v) for k, v in raw["history"].items()}
                if isinstance(raw.get("offsets"), dict):
                    data["offsets"] = {str(k): float(v) for k, v in raw["offsets"].items() if _is_num(v)}
    except Exception:
        pass
    return data


def _is_num(v) -> bool:
    try:
        float(v)
        return True
    except Exception:
        return False


def save_ledger(data: dict, path: Path | str | None = None) -> Path:
    lp = ledger_path(path)
    lp.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_index": int(data.get("last_index", -1)),
        "last_track": data.get("last_track"),
        "history": dict(data.get("history") or {}),
        "offsets": dict(data.get("offsets") or {}),
    }
    lp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return lp


def select_calm_track(
    ep: str | int | None = None,
    calm: Path | str | None = None,
    ledger: Path | str | None = None,
) -> dict:
    """Pick the calm track for ``ep`` (round-robin / LRU, persisted).

    Returns ``{track, index, is_fallback, ep}`` where ``track`` is a Path
    (or None when the folder is empty and the caller must use the old bed).
    Idempotent: an ``ep`` already in the ledger returns the same track when
    the file still exists.
    """
    tracks = list_calm_tracks(calm)
    ep_key = normalize_ep(ep)
    data = load_ledger(ledger)
    if not tracks:
        return {"track": None, "index": -1, "is_fallback": True, "ep": ep_key}
    names = [p.name for p in tracks]
    # Resume: same ep keeps its track when still present.
    if ep_key and ep_key in data.get("history", {}):
        prev = str(data["history"][ep_key])
        if prev in names:
            idx = names.index(prev)
            data["last_index"] = idx
            data["last_track"] = prev
            save_ledger(data, ledger)
            return {"track": tracks[idx], "index": idx, "is_fallback": False, "ep": ep_key}
    # Least-recently-used fallback: never repeat the last track when N > 1.
    last_track = data.get("last_track")
    last_index = int(data.get("last_index", -1))
    if ep_key is None and last_track in names and len(tracks) > 1:
        # LRU without ep: step to next index (different from last).
        nxt = (last_index + 1) % len(tracks) if last_index >= 0 else 0
        if tracks[nxt].name == last_track:
            nxt = (nxt + 1) % len(tracks)
        idx = nxt
    elif last_index < 0 or last_track is None:
        # Fresh ledger: round-robin by episode number for determinism.
        n = parse_ep_number(ep_key)
        idx = (n % len(tracks)) if n is not None else 0
    else:
        nxt = (last_index + 1) % len(tracks)
        # Guard against stale index after tracks were added/removed.
        if tracks[nxt].name == last_track and len(tracks) > 1:
            nxt = (nxt + 1) % len(tracks)
        idx = nxt
    chosen = tracks[idx]
    data["last_index"] = idx
    data["last_track"] = chosen.name
    if ep_key:
        data.setdefault("history", {})[ep_key] = chosen.name
    save_ledger(data, ledger)
    return {"track": chosen, "index": idx, "is_fallback": False, "ep": ep_key}


def track_duration(path: Path | str) -> float:
    """Audio duration in seconds via ffprobe (0.0 on failure)."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=15,
        )
        return float((out.stdout or "").strip() or 0.0)
    except Exception:
        return 0.0


def random_offset(
    track_secs: float,
    needed_secs: float,
    rng: random.Random | None = None,
) -> float:
    """Random start offset so a long track starts at a fresh place."""
    if track_secs <= 0 or needed_secs <= 0 or track_secs <= needed_secs:
        return 0.0
    r = rng or random
    span = track_secs - needed_secs
    try:
        return float(r.uniform(0, span))
    except Exception:
        return 0.0


def offset_for_ep(
    ep: str | int | None,
    track: Path | str,
    needed_secs: float,
    calm: Path | str | None = None,
    ledger: Path | str | None = None,
    rng: random.Random | None = None,
) -> float:
    """Persisted per-episode start offset (stable across resume/retries)."""
    ep_key = normalize_ep(ep)
    data = load_ledger(ledger)
    if ep_key and ep_key in (data.get("offsets") or {}):
        try:
            return float(data["offsets"][ep_key])
        except Exception:
            pass
    dur = track_duration(track)
    off = random_offset(dur, float(needed_secs or 0.0), rng=rng)
    if ep_key:
        data.setdefault("offsets", {})[ep_key] = float(off)
        save_ledger(data, ledger)
    return float(off)


def measure_integrated_lufs(path: Path | str) -> float | None:
    """Integrated LUFS via ffmpeg ebur128 (None on failure)."""
    try:
        proc = subprocess.run(
            ["ffmpeg", "-nostats", "-i", str(path), "-map", "0:a",
             "-filter:a", "ebur128=peak=true", "-f", "null", "-"],
            capture_output=True, text=True, timeout=120,
        )
        text = (proc.stderr or "") + (proc.stdout or "")
        # Last "I:" line holds the integrated value.
        vals: list[float] = []
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("I:"):
                m = re.search(r"I:\s*(-?\d+(?:\.\d+)?)", s)
                if m:
                    try:
                        vals.append(float(m.group(1)))
                    except ValueError:
                        pass
        if vals:
            return vals[-1]
        m = re.search(r"Integrated loudness:\s*\n\s*I:\s*(-?\d+(?:\.\d+)?)", text)
        if m:
            return float(m.group(1))
        return None
    except Exception:
        return None


def measure_excerpt_lufs(track: Path | str, offset: float = 0.0, needed_secs: float = 0.0) -> float | None:
    """Integrated LUFS of the ``[offset, offset+needed)`` excerpt (None on failure).

    Excerpt-based normalization guarantees the actually-used bed segment sits
    at the target even for dynamic tracks (full-track integrated can be many
    dB off from a quiet/loud excerpt).
    """
    try:
        need = float(needed_secs or 0.0)
        off = max(0.0, float(offset or 0.0))
        if need <= 0:
            return measure_integrated_lufs(track)
        total = track_duration(track)
        if total > 0 and off + need > total:
            # Wraps past the end (or needs looping): fall back to full-track.
            return measure_integrated_lufs(track)
        proc = subprocess.run(
            ["ffmpeg", "-nostats", "-ss", f"{off:.3f}", "-t", f"{need:.3f}",
             "-i", str(track), "-map", "0:a", "-filter:a", "ebur128=peak=true",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=60,
        )
        text = (proc.stderr or "") + (proc.stdout or "")
        vals: list[float] = []
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("I:"):
                m = re.search(r"I:\s*(-?\d+(?:\.\d+)?)", s)
                if m:
                    try:
                        vals.append(float(m.group(1)))
                    except ValueError:
                        pass
        if vals:
            return vals[-1]
        m = re.search(r"Integrated loudness:\s*\n\s*I:\s*(-?\d+(?:\.\d+)?)", text)
        if m:
            return float(m.group(1))
        return None
    except Exception:
        return None


def check_excerpt_dynamics(
    track: Path | str,
    offset: float = 0.0,
    needed_secs: float = 0.0,
    max_drop_db: float = MAX_QUIET_DROP_DB,
    head_secs: float = HEAD_CHECK_SECS,
    window_secs: float = WINDOW_CHECK_SECS,
    stride_secs: float = WINDOW_CHECK_STRIDE_SECS,
    measure_fn=None,
) -> dict:
    """Quiet-pocket guard for a candidate excerpt (2026-10-04, drop Fluidscape).

    The excerpt ``[offset, offset+needed)`` passes when its head-``head_secs``
    and every ``window_secs`` window (stepped by ``stride_secs``) sit within
    ``max_drop_db`` below the excerpt integrated level. Returns
    ``{ok, issues, excerpt_lufs, head_lufs, min_window_lufs}``.

    Unmeasurable excerpts return ``ok True`` (fail-open) so a missing ffmpeg
    can never break render; the caller treats ``None`` measures as skipped.
    ``measure_fn(track, offset, secs)`` is injectable for unit tests.
    """
    fn = measure_fn or measure_excerpt_lufs
    need = float(needed_secs or 0.0)
    off = max(0.0, float(offset or 0.0))
    if need <= 0:
        return {"ok": True, "issues": [], "excerpt_lufs": None, "head_lufs": None, "min_window_lufs": None}
    try:
        excerpt = fn(track, off, need)
    except Exception:
        excerpt = None
    if excerpt is None:
        return {"ok": True, "issues": ["excerpt unmeasurable, allowing"], "excerpt_lufs": None, "head_lufs": None, "min_window_lufs": None}
    issues: list[str] = []
    head_lufs: float | None = None
    min_window: float | None = None
    try:
        head_need = min(float(head_secs), need)
        head_lufs = fn(track, off, head_need)
    except Exception:
        head_lufs = None
    if head_lufs is not None and float(head_lufs) < float(excerpt) - float(max_drop_db):
        issues.append(f"head {head_lufs:.1f} LUFS >{max_drop_db:.0f}dB below excerpt {excerpt:.1f} LUFS")
    # Sliding 10s windows over the excerpt.
    try:
        w = min(float(window_secs), need)
        stride = max(1.0, float(stride_secs or window_secs))
        start = off
        end = off + need
        worst: float | None = None
        s = start
        while s + w <= end + 1e-6:
            try:
                v = fn(track, s, w)
            except Exception:
                v = None
            if v is not None:
                if worst is None or float(v) < float(worst):
                    worst = float(v)
                if float(v) < float(excerpt) - float(max_drop_db):
                    issues.append(f"window [{s - off:.0f},{s - off + w:.0f}) {v:.1f} LUFS >{max_drop_db:.0f}dB below excerpt {excerpt:.1f} LUFS")
                    break
            s += stride
        min_window = worst
    except Exception:
        pass
    return {
        "ok": not issues,
        "issues": issues,
        "excerpt_lufs": float(excerpt),
        "head_lufs": None if head_lufs is None else float(head_lufs),
        "min_window_lufs": None if min_window is None else float(min_window),
    }


def find_dynamics_safe_offset(
    track: Path | str,
    needed_secs: float,
    calm: Path | str | None = None,
    rng: random.Random | None = None,
    max_tries: int = MAX_OFFSET_TRIES,
    measure_fn=None,
    duration_fn=None,
) -> dict | None:
    """First random offset whose excerpt passes :func:`check_excerpt_dynamics`.

    Returns ``{offset, excerpt_lufs, head_lufs, min_window_lufs}`` or None
    when no candidate passes within ``max_tries``. Pure except for ffmpeg
    measures (injectable via ``measure_fn`` / ``duration_fn`` for tests).
    """
    need = float(needed_secs or 0.0)
    if need <= 0:
        return None
    dur_fn = duration_fn or track_duration
    try:
        total = float(dur_fn(track) or 0.0)
    except Exception:
        total = 0.0
    r = rng or random
    for _ in range(max(1, int(max_tries))):
        try:
            off = float(random_offset(total, need, rng=r))
        except Exception:
            off = 0.0
        chk = check_excerpt_dynamics(track, off, need, measure_fn=measure_fn)
        if chk.get("ok"):
            return {
                "offset": float(off),
                "excerpt_lufs": chk.get("excerpt_lufs"),
                "head_lufs": chk.get("head_lufs"),
                "min_window_lufs": chk.get("min_window_lufs"),
            }
    return None


def gain_for_target_lufs(measured_lufs: float | None, target: float = TARGET_BED_LUFS) -> dict:
    """Linear gain (and dB) to move ``measured`` to ``target``."""
    if measured_lufs is None:
        return {"db": 0.0, "linear": 1.0, "measured": None, "target": float(target)}
    db = float(target) - float(measured_lufs)
    # Clamp to a sane range (-40..+20 dB) so a corrupt measure can't blast audio.
    db = max(-40.0, min(20.0, db))
    linear = math.pow(10.0, db / 20.0)
    return {"db": db, "linear": linear, "measured": float(measured_lufs), "target": float(target)}


def load_tracks_metadata(calm: Path | str | None = None) -> dict:
    """``tracks.json`` map: filename -> {title, artist, license, attribution, ...}."""
    p = tracks_metadata_path(calm)
    try:
        if p.is_file():
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                tracks = raw.get("tracks")
                if isinstance(tracks, dict):
                    return tracks
                # Also accept a bare map for forward-compat.
                return {k: v for k, v in raw.items() if isinstance(v, dict)}
    except Exception:
        pass
    return {}


def attribution_for_track(track: Path | str, calm: Path | str | None = None) -> str | None:
    """Credit line for ``track`` when attribution is required, else None."""
    meta = load_tracks_metadata(calm)
    name = Path(track).name if track else ""
    info = meta.get(name) or {}
    line = str(info.get("attribution") or "").strip()
    required = bool(info.get("attribution_required", bool(line)))
    # Unknown license: Kevin MacLeod tracks always need attribution.
    if not info and "kevin macleod" in name.lower():
        return f"Music: {Path(name).stem} by Kevin MacLeod, licensed under CC BY 4.0"
    if required and line:
        return line
    return None


def music_credit_for_ep(
    ep: str | int | None,
    calm: Path | str | None = None,
    ledger: Path | str | None = None,
) -> str | None:
    """Credit line for the track recorded for ``ep`` (None when not needed)."""
    ep_key = normalize_ep(ep)
    if not ep_key:
        return None
    data = load_ledger(ledger)
    filename = (data.get("history") or {}).get(ep_key)
    if not filename:
        # No rotation record yet: predict the track without persisting.
        tracks = list_calm_tracks(calm)
        if not tracks:
            return None
        n = parse_ep_number(ep_key)
        last_index = int(data.get("last_index", -1))
        if last_index < 0 and n is not None:
            filename = tracks[n % len(tracks)].name
        elif data.get("last_track") in [p.name for p in tracks]:
            filename = str(data.get("last_track"))
        else:
            return None
    return attribution_for_track(filename, calm)


def check_bgm_loudness(
    bed_lufs: float | None,
    narration_lufs: float | None,
    target_bed: float = TARGET_BED_LUFS,
    ref_narration: float = NARRATION_REF_LUFS,
    bed_tol: float = 2.0,
    min_delta_db: float = 15.0,
) -> dict:
    """Loudness QA gate: bed ~ -42 LUFS and >=15 dB under narration."""
    issues: list[str] = []
    if bed_lufs is None:
        issues.append("bed LUFS unmeasurable")
    elif abs(float(bed_lufs) - float(target_bed)) > float(bed_tol):
        issues.append(f"bed {bed_lufs:.1f} LUFS not within {target_bed:.0f}±{bed_tol:.0f} LUFS")
    if narration_lufs is None:
        issues.append("narration LUFS unmeasurable")
    if bed_lufs is not None and narration_lufs is not None:
        delta = float(narration_lufs) - float(bed_lufs)
        if delta < float(min_delta_db):
            issues.append(f"bed only {delta:.1f} dB under narration (want >={min_delta_db:.0f} dB)")
    return {"ok": not issues, "issues": issues}


def old_bed_fallback() -> Path | None:
    """Legacy music bed (only when the calm folder is empty)."""
    candidates = [
        repo_root() / "data" / "assets" / "music" / OLD_BED_FILENAME,
        Path("data/assets/music") / OLD_BED_FILENAME,
        Path("/Users/huangyuan/Projects/video-factory/apps/worker/data/assets/music") / OLD_BED_FILENAME,
    ]
    try:
        from .config import settings as _settings

        extra = Path(str(getattr(_settings, "assets_dir", ""))) / "music" / OLD_BED_FILENAME
        candidates.insert(0, extra)
    except Exception:
        pass
    for c in candidates:
        try:
            if c.is_file():
                return c
        except Exception:
            continue
    # Any legacy music file as a last resort.
    for base in [
        repo_root() / "data" / "assets" / "music",
        Path("data/assets/music"),
    ]:
        try:
            if base.is_dir():
                for pat in ("*.mp3", "*.wav", "*.m4a", "*.flac"):
                    files = sorted(base.glob(pat))
                    if files:
                        return files[0]
        except Exception:
            continue
    return None


def resolve_bgm_for_episode(
    ep: str | int | None = None,
    needed_secs: float = 0.0,
    calm: Path | str | None = None,
    ledger: Path | str | None = None,
    rng: random.Random | None = None,
    measure_fn=None,
    duration_fn=None,
) -> dict:
    """High-level resolver used by the render path and publish descriptions.

    Returns ``{track, index, is_fallback, offset, attribution, ep}``.

    Quiet-pocket guard (2026-10-04): the chosen excerpt's head-15s and every
    10s window must sit within 6 dB below the excerpt level (see
    :func:`check_excerpt_dynamics`). A failing offset is retried up to
    ``MAX_OFFSET_TRIES`` times, then the next track is tried; when nothing
    passes the original selection is kept (fail-open, never breaks render).
    """
    sel = select_calm_track(ep=ep, calm=calm, ledger=ledger)
    track = sel.get("track")
    if track is None:
        fb = old_bed_fallback()
        return {
            "track": fb,
            "index": -1,
            "is_fallback": True,
            "offset": 0.0,
            "attribution": None,
            "ep": sel.get("ep"),
        }
    need = float(needed_secs or 0.0)
    off = offset_for_ep(ep=sel.get("ep"), track=track, needed_secs=needed_secs, calm=calm, ledger=ledger, rng=rng)
    if need <= 0:
        credit = attribution_for_track(track, calm)
        return {
            "track": track,
            "index": int(sel.get("index", -1)),
            "is_fallback": False,
            "offset": float(off),
            "attribution": credit,
            "ep": sel.get("ep"),
        }
    try:
        first = check_excerpt_dynamics(track, off, need, measure_fn=measure_fn)
    except Exception:
        first = {"ok": True}
    if first.get("ok"):
        credit = attribution_for_track(track, calm)
        return {
            "track": track,
            "index": int(sel.get("index", -1)),
            "is_fallback": False,
            "offset": float(off),
            "attribution": credit,
            "ep": sel.get("ep"),
        }
    logger.warning("BGM excerpt dynamics fail (%s), retrying offsets: %s", getattr(track, "name", track), first.get("issues"))
    # Same track, fresh offsets.
    try:
        safe = find_dynamics_safe_offset(track, need, calm=calm, rng=rng, measure_fn=measure_fn, duration_fn=duration_fn)
    except Exception:
        safe = None
    ep_key = sel.get("ep")
    if safe is not None:
        try:
            if ep_key:
                data = load_ledger(ledger)
                data.setdefault("offsets", {})[str(ep_key)] = float(safe["offset"])
                save_ledger(data, ledger)
        except Exception:
            pass
        credit = attribution_for_track(track, calm)
        return {
            "track": track,
            "index": int(sel.get("index", -1)),
            "is_fallback": False,
            "offset": float(safe["offset"]),
            "attribution": credit,
            "ep": sel.get("ep"),
        }
    # Try the other calm tracks before giving up.
    try:
        tracks = list_calm_tracks(calm)
    except Exception:
        tracks = []
    current = Path(str(track)).name
    for cand in tracks:
        if cand.name == current:
            continue
        try:
            alt = find_dynamics_safe_offset(cand, need, calm=calm, rng=rng, measure_fn=measure_fn, duration_fn=duration_fn)
        except Exception:
            alt = None
        if alt is None:
            continue
        try:
            if ep_key:
                data = load_ledger(ledger)
                names = [p.name for p in tracks]
                idx = names.index(cand.name) if cand.name in names else -1
                data["last_index"] = int(idx)
                data["last_track"] = cand.name
                data.setdefault("history", {})[str(ep_key)] = cand.name
                data.setdefault("offsets", {})[str(ep_key)] = float(alt["offset"])
                save_ledger(data, ledger)
                credit = attribution_for_track(cand, calm)
                return {
                    "track": cand,
                    "index": int(idx),
                    "is_fallback": False,
                    "offset": float(alt["offset"]),
                    "attribution": credit,
                    "ep": ep_key,
                }
        except Exception:
            pass
        credit = attribution_for_track(cand, calm)
        names = [p.name for p in tracks]
        idx = names.index(cand.name) if cand.name in names else -1
        return {
            "track": cand,
            "index": int(idx),
            "is_fallback": False,
            "offset": float(alt["offset"]),
            "attribution": credit,
            "ep": ep_key or sel.get("ep"),
        }
    logger.warning("BGM dynamics guard found no quiet-safe excerpt, keeping original selection")
    credit = attribution_for_track(track, calm)
    return {
        "track": track,
        "index": int(sel.get("index", -1)),
        "is_fallback": False,
        "offset": float(off),
        "attribution": credit,
        "ep": sel.get("ep"),
    }


def build_bgm_audio_clip(track: Path | str, duration: float, target_lufs: float = TARGET_BED_LUFS, offset: float = 0.0, fade_in: float = FADE_IN_S, fade_out: float = FADE_OUT_S, measured_lufs: float | None = None):
    """MoviePy BGM clip: random offset, loop, -42 LUFS normalize, 2s/3s fades.

    Normalization is excerpt-based: the actually-used ``[offset,
    offset+duration)`` segment is measured (via ffmpeg ``-ss/-t`` + ebur128)
    so dynamic tracks still land on target. ``measured_lufs`` (full-track)
    is only a fallback when excerpt measurement fails.
    """
    from moviepy import AudioFileClip
    from moviepy.audio.fx import AudioFadeIn, AudioFadeOut, AudioLoop

    src = AudioFileClip(str(track))
    total = float(src.duration or 0.0)
    need = float(duration or 0.0)
    start = max(0.0, float(offset or 0.0))
    if total > 0 and start >= total:
        start = 0.0
    if total > 0 and need > 0 and start + need <= total:
        bgm = src.subclipped(start, start + need)
    elif total > 0 and need > 0 and total > need:
        # Wrap past the end by looping the tail+head (long tracks rarely need this).
        bgm = src.subclipped(start, total)
        if bgm.duration < need:
            bgm = bgm.with_effects([AudioLoop(duration=need)])
        else:
            bgm = bgm.subclipped(0, need)
    elif total > 0 and need > 0 and total < need:
        bgm = src.with_effects([AudioLoop(duration=need)])
        if start > 0:
            # Start mid-track even when looping: rotate the looped clip.
            try:
                tail = src.subclipped(start, total)
                head = src.subclipped(0, start)
                from moviepy import CompositeAudioClip as _CAC

                joined = _CAC([tail, head.with_start(tail.duration)])
                if joined.duration < need:
                    joined = joined.with_effects([AudioLoop(duration=need)])
                bgm = joined.subclipped(0, need)
            except Exception:
                pass
    elif need > 0:
        bgm = src.subclipped(0, need) if total <= 0 else src
    else:
        bgm = src
    excerpt_lufs: float | None = None
    try:
        if need > 0 and total > 0 and start + need <= total:
            excerpt_lufs = measure_excerpt_lufs(track, offset=start, needed_secs=need)
    except Exception:
        excerpt_lufs = None
    if excerpt_lufs is None:
        if measured_lufs is None:
            try:
                measured_lufs = measure_integrated_lufs(track)
            except Exception:
                measured_lufs = None
        excerpt_lufs = measured_lufs
    gain = gain_for_target_lufs(excerpt_lufs, target_lufs)
    try:
        bgm = bgm.with_volume_scaled(float(gain["linear"]))
    except Exception:
        pass
    # Fades (clamped so short beds never invert).
    try:
        d = float(bgm.duration or need or 0.0)
        fi = max(0.0, min(float(fade_in), d / 2)) if d > 0 else 0.0
        fo = max(0.0, min(float(fade_out), d / 2)) if d > 0 else 0.0
        if fi > 0:
            bgm = bgm.with_effects([AudioFadeIn(fi)])
        if fo > 0:
            bgm = bgm.with_effects([AudioFadeOut(fo)])
    except Exception:
        pass
    return bgm
