"""Post-render auto QA (absorbed from browser-use/video-use "Self-eval", MIT).

Measures the rendered ``output.mp4`` instead of trusting the plan:

- ebur128 integrated loudness + TRUE peak of the full mix; narration stem
  (``segment_*.mp3``) near ``bgm.NARRATION_REF_LUFS``; bed stem (the exact
  excerpt + gain from ``bgm.json``) at ``bgm.TARGET_BED_LUFS`` (-42) and
  >=15 dB under narration (``bgm.check_bgm_loudness``); cover window 1-3 s not
  a silent pocket (>= -42-6 i.e. bgm.MAX_QUIET_DROP_DB, <= -42+3 LUFS).
- duration vs plan (cover hold + task.log segment offsets/durations), video
  stream included (a short video stream hides behind ``format=duration``).
- frames at every segment cut +-1.5 s: black frames, single-frame flashes,
  and subtitle ink present in the band while a cue is active (subtitles on top).
- audio pops at every narration join (2nd-difference spike).
- cover / first-frame episode number via tesseract (hard gate when tesseract
  exists, skipped+recorded otherwise - same policy as the jargon OCR gate).
- :func:`fix_loop`: at most 3 rounds; only audio problems have a deterministic
  fix (re-mix from stems with 30 ms join fades, ``-c:v copy``); anything visual
  stops and flags a human.

Read-only on its inputs except ``remix_audio`` (keeps ``output.pre_fix.mp4``).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

JOIN_FADE_S = 0.03
NARRATION_TOL_DB = 2.5
MIX_TOL_DB = 2.5
TRUE_PEAK_MAX = -1.0
COVER_WINDOW = (1.0, 3.0)
COVER_TOL_DB = 3.0  # cover may be at most this LOUDER than the bed target
DURATION_TOL_S = 0.25
VIDEO_STREAM_TOL_S = 0.15
CUT_WINDOW_S = 1.5
BLACK_MEAN_MAX = 12.0
BLACK_STD_MAX = 6.0
FLASH_DIFF_MIN = 60.0
POP_RATIO_MAX = 8.0
POP_ABS_MIN = 0.02
SUB_INK_MIN = 0.002
MAX_FIX_ROUNDS = 3
SEGMENT_PAUSE_S = 0.5

_START_RE = re.compile(r"音频片段\s+(\d+):\s*开始=([\d.]+)s,\s*时长=([\d.]+)s")
_DIALOGUE_RE = re.compile(r"Dialogue:\s*\d+,(\d+):(\d{2}):(\d{2})\.(\d{2}),(\d+):(\d{2}):(\d{2})\.(\d{2}),")
_EP_RE = re.compile(r"第\s*(\d+)\s*集")


def _targets() -> tuple[float, float]:
    try:
        from .bgm import NARRATION_REF_LUFS, TARGET_BED_LUFS

        return float(NARRATION_REF_LUFS), float(TARGET_BED_LUFS)
    except Exception:  # pragma: no cover - bgm always importable in the worker
        return -24.0, -42.0


# ------------------------------------------------------------------ ffmpeg helpers
def parse_ebur128(stderr: str) -> dict:
    idx = (stderr or "").rfind("Summary:")
    block = stderr[idx:] if idx >= 0 else (stderr or "")
    out: dict = {"I": None, "LRA": None, "TP": None}
    for key, rx in (("I", r"^\s*I:\s*(-?[\d.]+|-inf)\s*LUFS"), ("LRA", r"^\s*LRA:\s*(-?[\d.]+)\s*LU\b"),
                    ("TP", r"^\s*Peak:\s*(-?[\d.]+|-inf)\s*dBFS")):
        m = re.search(rx, block, re.M)
        if m:
            out[key] = float("-inf") if m.group(1) == "-inf" else float(m.group(1))
    return out


def ebur128(path, ss: float | None = None, t: float | None = None, pre: str = "") -> dict:
    cmd = ["ffmpeg", "-hide_banner", "-nostats"]
    if ss is not None:
        cmd += ["-ss", f"{max(ss, 0.0):.3f}"]
    if t is not None:
        cmd += ["-t", f"{t:.3f}"]
    cmd += ["-i", str(path), "-vn", "-af", (pre + "," if pre else "") + "ebur128=peak=true", "-f", "null", "-"]
    return parse_ebur128(subprocess.run(cmd, capture_output=True, text=True).stderr or "")


def concat_lufs(files: list[Path]) -> dict:
    inputs: list[str] = []
    for f in files:
        inputs += ["-i", str(f)]
    n = len(files)
    fc = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1,ebur128=peak=true"
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", *inputs, "-filter_complex", fc, "-f", "null", "-"],
                       capture_output=True, text=True)
    return parse_ebur128(r.stderr or "")


def stream_durations(path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration:format=duration",
                        "-of", "json", str(path)], capture_output=True, text=True)
    data = json.loads(r.stdout or "{}")
    out: dict = {}
    for st in data.get("streams", []):
        try:
            out.setdefault(st.get("codec_type"), float(st.get("duration")))
        except (TypeError, ValueError):
            pass
    try:
        out["format"] = float((data.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        pass
    return out


def video_size(path) -> tuple[int, int]:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        w, h = [int(x) for x in (r.stdout or "").strip().split(",")[:2]]
        return w, h
    except ValueError:
        return 0, 0


def gray_frames(path, start: float, dur: float, fps: int = 10, width: int = 128):
    import numpy as np

    w0, h0 = video_size(path)
    h = max(2, int(round(width * (h0 or 9) / (w0 or 16) / 2)) * 2)
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(start, 0):.3f}", "-t", f"{dur:.3f}", "-i", str(path),
                        "-an", "-vf", f"fps={fps},scale={width}:{h},format=gray", "-f", "rawvideo", "-"],
                       capture_output=True)
    buf = np.frombuffer(r.stdout, dtype=np.uint8)
    n = buf.size // (width * h)
    return buf[: n * width * h].reshape(n, h, width)


def band_crop(path, t: float, band_frac: float):
    """Full-res grayscale bottom band (subtitle area) at ``t`` as a 2-D array."""
    import numpy as np

    w, h = video_size(path)
    band = max(8, int(round(h * band_frac)))
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(t, 0):.3f}", "-i", str(path), "-frames:v", "1",
                        "-vf", f"crop={w}:{band}:0:{h - band},format=gray", "-f", "rawvideo", "-"],
                       capture_output=True)
    a = np.frombuffer(r.stdout, dtype=np.uint8)
    return a[: w * band].reshape(band, w) if a.size >= w * band else a.reshape(0, w)


def audio_window(path, center: float, half: float = 0.25, sr: int = 48000):
    import numpy as np

    start = max(center - half, 0.0)
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{2 * half:.3f}", "-i", str(path),
                        "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], capture_output=True)
    return np.frombuffer(r.stdout, dtype=np.float32), int(round((center - start) * sr))


# ------------------------------------------------------------------ pure detectors
def frame_anomalies(frames, times: list[float] | None = None) -> dict:
    import numpy as np

    f = frames.astype(np.float32)
    n = len(f)
    black = [i for i in range(n) if f[i].mean() <= BLACK_MEAN_MAX and f[i].std() <= BLACK_STD_MAX]
    flash = []
    for i in range(1, n - 1):
        a = np.abs(f[i] - f[i - 1]).mean()
        b = np.abs(f[i + 1] - f[i]).mean()
        c = np.abs(f[i + 1] - f[i - 1]).mean()
        if a >= FLASH_DIFF_MIN and b >= FLASH_DIFF_MIN and c < FLASH_DIFF_MIN / 3:
            flash.append(i)
    t = times or list(range(n))
    return {"black": [round(t[i], 2) for i in black], "flash": [round(t[i], 2) for i in flash], "frames": n}


def ink_fraction(band) -> float:
    """Share of band pixels far from the band's median (text on light OR dark band)."""
    import numpy as np

    if band.size == 0:
        return 0.0
    med = float(np.median(band))
    return float((np.abs(band.astype(np.int16) - med) > 60).mean())


def pop_ratio(samples, join_index: int, sr: int = 48000, near_ms: float = 15.0) -> tuple[float, float]:
    import numpy as np

    x = np.asarray(samples, dtype=np.float64)
    if x.size < 16:
        return 0.0, 0.0
    d2 = np.abs(np.diff(x, n=2))
    k = int(sr * near_ms / 1000)
    lo, hi = max(join_index - k, 0), min(join_index + k, d2.size)
    near, rest = d2[lo:hi], np.concatenate([d2[:lo], d2[hi:]])
    if near.size == 0 or rest.size == 0:
        return 0.0, 0.0
    peak = float(near.max())
    return peak / (float(np.percentile(rest, 99)) + 1e-4), peak


def parse_ocr_episode(text: str, n: int) -> dict:
    """Episode-number verdict from eng OCR of the cover.

    eng tesseract reads 「第 41 集」 as ``415`` / ``#398`` (集 -> one junk
    digit), so a run equal to N, or N plus exactly one trailing digit, counts.
    Decimals, percents, thousands and 4-digit years are ignored. Any other
    1-3 digit standalone run that is not N is reported as a foreign number.
    """
    found: list[str] = []
    for m in re.finditer(r"(?<![\d.,])(\d{1,4})(?![\d.,%])", text or ""):
        tok = m.group(1)
        if len(tok) == 4:
            continue
        found.append(tok)
    s = str(int(n))
    hit = [t for t in found if t == s or (t.startswith(s) and len(t) == len(s) + 1)]
    foreign = [t for t in found if t not in hit]
    return {"ok": bool(hit), "hits": hit, "foreign": foreign}


EP_LINE_CROP = (0.25, 0.22, 0.75, 0.40)  # 「第 N 集 · 名称」 line of the indicator title card


def episode_verdict(line_text: str, full_text: str, n: int) -> dict:
    """The episode line's FIRST number must be N (wrong-card guard, ep39 24-vs-39
    incident); the full frame must also contain N somewhere."""
    line = parse_ocr_episode(line_text, n)
    full = parse_ocr_episode(full_text, n)
    first = re.search(r"\d{1,3}", line_text or "")
    line_first_ok = True
    if first:
        tok = first.group(0)
        s = str(int(n))
        line_first_ok = tok == s or (tok.startswith(s) and len(tok) == len(s) + 1)
    ok = bool(full["ok"] or line["ok"]) and line_first_ok
    return {"ok": ok, "line_first": first.group(0) if first else None, "hits": line["hits"] + full["hits"],
            "foreign": full["foreign"]}


def ocr_text(png: Path, crop: tuple[float, float, float, float] | None = None, psm: int = 6) -> str | None:
    if shutil.which("tesseract") is None:
        return None
    src = png
    if crop:
        from PIL import Image

        im = Image.open(png)
        w, h = im.size
        src = png.with_name(png.stem + "_crop.png")
        im.crop((int(w * crop[0]), int(h * crop[1]), int(w * crop[2]), int(h * crop[3]))).save(src)
    r = subprocess.run(["tesseract", str(src), "stdout", "-l", "eng", "--psm", str(psm)],
                       capture_output=True, text=True)
    return r.stdout or ""


def cover_window_ok(cov: float | None, bed_target: float) -> bool:
    """Cover 1-3 s (bed only, fade-in included) is no quieter than the owner's
    quiet-pocket guard allows (``bgm.MAX_QUIET_DROP_DB`` = 6 dB under the bed
    target) and not more than ``COVER_TOL_DB`` louder."""
    if cov is None:
        return False
    try:
        from .bgm import MAX_QUIET_DROP_DB as drop
    except Exception:  # pragma: no cover
        drop = 6.0
    return bed_target - float(drop) <= cov <= bed_target + COVER_TOL_DB


# ------------------------------------------------------------------ plan from task dir
def read_plan(task_dir: Path, cover_hold: float = 3.0) -> dict:
    """Narration placement on the OUTPUT timeline (cover hold included).

    Sources, best first: ``timeline.json`` (exact, written by the renderer),
    ``task.log`` (offsets rounded to 0.1 s), mp3 durations + 0.5 s pauses.
    """
    segs: list[tuple[float, float]] = []
    source = "none"
    mp3s = sorted(task_dir.glob("segment_*.mp3"), key=lambda p: int(re.findall(r"\d+", p.stem)[-1]))
    tl = task_dir / "timeline.json"
    if tl.is_file():
        try:
            data = json.loads(tl.read_text(encoding="utf-8"))
            segs = [(float(x["start"]), float(x["duration"])) for x in data.get("segments", [])]
            source = "timeline.json"
        except Exception:
            segs = []
    log = task_dir / "task.log"
    if not segs and log.is_file():
        seen: dict[int, tuple[float, float]] = {}
        for m in _START_RE.finditer(log.read_text(encoding="utf-8", errors="ignore")):
            seen[int(m.group(1))] = (float(m.group(2)), float(m.group(3)))  # last render wins
        segs = [seen[k] for k in sorted(seen)]
        source = "task.log" if segs else source
    if not segs and mp3s:
        t = cover_hold
        for p in mp3s:
            d = float(stream_durations(p).get("format") or 0.0)
            segs.append((t, d))
            t += d + SEGMENT_PAUSE_S
        source = "mp3"
    cover = segs[0][0] if segs else cover_hold
    end = (segs[-1][0] + segs[-1][1]) if segs else 0.0
    return {"segments": segs, "cover_hold": cover, "planned": end, "mp3s": mp3s, "source": source}


def ass_cues(task_dir: Path, offset: float) -> list[tuple[float, float]]:
    p = task_dir / "subtitles.ass"
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = _DIALOGUE_RE.match(line)
        if m:
            g = [int(x) for x in m.groups()]
            a = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 100
            b = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 100
            out.append((a + offset, b + offset))
    return out


def episode_number(task_dir: Path) -> int | None:
    for name in ("script.json",):
        p = task_dir / name
        if p.is_file():
            try:
                m = _EP_RE.search(json.loads(p.read_text(encoding="utf-8")).get("title") or "")
                if m:
                    return int(m.group(1))
            except Exception:
                pass
    return None


# ------------------------------------------------------------------ the gate
def run_render_qa(task_dir: Path, episode: int | None = None, band_frac: float | None = None,
                  video: Path | None = None) -> dict:
    task_dir = Path(task_dir)
    mp4 = Path(video) if video else task_dir / "output.mp4"
    narr_ref, bed_target = _targets()
    checks: dict = {}
    issues: list[str] = []
    metrics: dict = {}
    if not mp4.is_file():
        return {"pass": False, "checks": {"output_exists": False}, "issues": [f"missing {mp4}"], "metrics": {}}
    plan = read_plan(task_dir)
    cover_hold = plan["cover_hold"]

    # loudness
    mix = ebur128(mp4)
    narr = concat_lufs(plan["mp3s"]) if plan["mp3s"] else {"I": None}
    bed_i = None
    bj = task_dir / "bgm.json"
    bgm = json.loads(bj.read_text(encoding="utf-8")) if bj.is_file() else {}
    if bgm.get("track") and Path(bgm["track"]).is_file() and bgm.get("gain_db") is not None:
        bed_i = ebur128(bgm["track"], ss=float(bgm.get("offset") or 0.0), t=max(plan["planned"], 1.0),
                        pre=f"volume={float(bgm['gain_db']):.2f}dB").get("I")
    cov = ebur128(mp4, ss=COVER_WINDOW[0], t=COVER_WINDOW[1] - COVER_WINDOW[0]).get("I") if bgm else None
    checks["mix_lufs_near_standard"] = mix["I"] is not None and abs(mix["I"] - narr_ref) <= MIX_TOL_DB
    checks["true_peak_ok"] = mix["TP"] is not None and mix["TP"] <= TRUE_PEAK_MAX
    checks["narration_lufs_near_standard"] = narr.get("I") is not None and abs(narr["I"] - narr_ref) <= NARRATION_TOL_DB
    if bgm:
        from .bgm import check_bgm_loudness

        bl = check_bgm_loudness(bed_i, narr.get("I"), target_bed=bed_target)
        checks["bed_loudness_ok"] = bool(bl["ok"])
        issues += [f"bgm: {x}" for x in bl["issues"]]
        checks["cover_not_silent_pocket"] = cover_window_ok(cov, bed_target)
    metrics["loudness"] = {"mix_I": mix["I"], "mix_TP": mix["TP"], "mix_LRA": mix["LRA"], "narration_I": narr.get("I"),
                           "bed_I": bed_i, "cover_1_3s_I": cov, "narration_ref": narr_ref, "bed_target": bed_target,
                           "bed_delta_db": (round(narr["I"] - bed_i, 1) if narr.get("I") is not None and bed_i is not None else None)}

    # duration
    sd = stream_durations(mp4)
    planned = plan["planned"]
    checks["duration_matches_plan"] = planned > 0 and abs(sd.get("format", 0) - planned) <= DURATION_TOL_S
    checks["video_stream_matches_plan"] = planned > 0 and abs(sd.get("video", 0) - planned) <= VIDEO_STREAM_TOL_S + 0.1
    metrics["duration"] = {"planned": round(planned, 3), **{k: round(v, 3) for k, v in sd.items()}}

    # frames at cuts (+-1.5s) + subtitles on top
    if band_frac is None:
        try:
            from ..config import settings

            band_frac = float(getattr(settings, "chart_fullframe_band_px", 130) or 130) / 1080.0
        except Exception:
            band_frac = 130 / 1080.0
    cues = ass_cues(task_dir, cover_hold)
    cuts = [round(s, 3) for s, _d in plan["segments"]]
    cut_rep = []
    cuts_ok = True
    for c in cuts:
        start = max(c - CUT_WINDOW_S, 0.0)
        fr = gray_frames(mp4, start, 2 * CUT_WINDOW_S)
        an = frame_anomalies(fr, [start + i / 10 for i in range(len(fr))]) if len(fr) >= 3 else {"black": [], "flash": [], "frames": len(fr)}
        subs = []
        for ts in (c - CUT_WINDOW_S, c + CUT_WINDOW_S):
            if ts > 0 and any(a + 0.1 <= ts <= b - 0.1 for a, b in cues):
                ink = ink_fraction(band_crop(mp4, ts, band_frac))
                subs.append({"t": round(ts, 2), "ink": round(ink, 4), "pass": ink >= SUB_INK_MIN})
        ok = not an["black"] and not an["flash"] and all(s["pass"] for s in subs) and an["frames"] >= 3
        cuts_ok = cuts_ok and ok
        cut_rep.append({"cut": c, "pass": ok, **an, "subtitle_frames": subs})
    checks["cut_frames_clean"] = cuts_ok

    # pops at every narration join (start and end of each segment)
    joins = sorted({round(s, 3) for s, _ in plan["segments"]} | {round(s + d, 3) for s, d in plan["segments"]})
    pop_rep = []
    for j in joins:
        x, k = audio_window(mp4, j)
        r, p = pop_ratio(x, k)
        pop_rep.append({"t": j, "ratio": round(r, 2), "peak": round(p, 4), "pop": bool(r > POP_RATIO_MAX and p > POP_ABS_MIN)})
    checks["no_join_pops"] = not any(x["pop"] for x in pop_rep)

    # cover / first frame episode number
    n = episode if episode is not None else episode_number(task_dir)
    ocr = {"status": "no-episode"}
    if n is not None:
        if shutil.which("tesseract") is None:
            ocr = {"status": "skipped-no-tesseract", "episode": n}
        else:
            res = []
            for ts in (1.5, 0.1):
                png = task_dir / f"_render_qa_cover_{ts:.1f}.png"
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{ts}", "-i", str(mp4), "-frames:v", "1", str(png)],
                               check=False)
                line = ocr_text(png, EP_LINE_CROP, psm=7) or ""
                full = ocr_text(png) or ""
                v = episode_verdict(line, full, n)
                res.append({"t": ts, **v})
                for p in png.parent.glob(png.stem + "*.png"):
                    p.unlink(missing_ok=True)
            ok = all(r["ok"] for r in res)
            ocr = {"status": "checked", "episode": n, "frames": res, "pass": ok}
            checks["cover_episode_ocr"] = ok
    metrics["cover_ocr"] = ocr

    issues = [k for k, v in checks.items() if not v] + issues
    return {"pass": bool(all(checks.values())), "checks": checks, "issues": issues, "metrics": metrics,
            "cuts": cut_rep, "joins": pop_rep, "video": str(mp4)}


# ------------------------------------------------------------------ audio re-mix (only deterministic fix)
def remix_filter(segments: list[tuple[float, float]], total: float, narr_gain_db: float,
                 bed: dict | None) -> str:
    parts, labels = [], []
    for i, (s, d) in enumerate(segments):
        ms = int(round(s * 1000))
        fo = max(d - JOIN_FADE_S, 0.0)
        parts.append(f"[{i + 1}:a]aresample=44100,aformat=channel_layouts=stereo,volume={narr_gain_db:.2f}dB,"
                     f"afade=t=in:st=0:d={JOIN_FADE_S},afade=t=out:st={fo:.3f}:d={JOIN_FADE_S},adelay={ms}|{ms}[n{i}]")
        labels.append(f"[n{i}]")
    if bed:
        k = len(segments) + 1
        parts.append(f"[{k}:a]aresample=44100,aformat=channel_layouts=stereo,atrim=0:{total:.3f},asetpts=PTS-STARTPTS,"
                     f"volume={bed['gain_db']:.2f}dB,afade=t=in:st=0:d={bed.get('fade_in', 2.0)},"
                     f"afade=t=out:st={max(total - float(bed.get('fade_out', 3.0)), 0):.3f}:d={bed.get('fade_out', 3.0)}[bg]")
        labels.append("[bg]")
    parts.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=longest,"
                 f"atrim=0:{total:.3f},apad=whole_dur={total:.3f}[aout]")
    return ";".join(parts)


def remix_audio(task_dir: Path, params: dict) -> Path:
    """Rebuild the audio from stems (30 ms join fades) and mux with ``-c:v copy``."""
    task_dir = Path(task_dir)
    mp4 = task_dir / "output.mp4"
    backup = task_dir / "output.pre_fix.mp4"
    if not backup.exists():
        shutil.copy2(mp4, backup)
    plan = read_plan(task_dir)
    sd = stream_durations(backup)
    total = sd.get("format") or plan["planned"]
    bj = task_dir / "bgm.json"
    bgm = json.loads(bj.read_text(encoding="utf-8")) if bj.is_file() else {}
    bed = None
    inputs = ["-i", str(backup)] + sum((["-i", str(p)] for p in plan["mp3s"]), [])
    if bgm.get("track") and Path(bgm["track"]).is_file():
        bed = {"gain_db": float(bgm.get("gain_db") or 0.0) + float(params.get("bed_gain_adjust_db", 0.0)),
               "fade_in": float(bgm.get("fade_in", 2.0)), "fade_out": float(bgm.get("fade_out", 3.0))}
        inputs += ["-ss", f"{float(bgm.get('offset') or 0.0):.3f}", "-i", str(bgm["track"])]
    fc = remix_filter(plan["segments"], total, float(params.get("narration_gain_db", 0.0)), bed)
    tmp = task_dir / "output.remix.tmp.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", fc, "-map", "0:v", "-map", "[aout]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}", "-movflags", "+faststart",
                    str(tmp)], check=True)
    tmp.replace(mp4)
    return mp4


def propose_fix(report: dict, params: dict) -> dict | None:
    c, m = report.get("checks", {}), report.get("metrics", {}).get("loudness", {})
    new, changed = dict(params), False
    if c.get("true_peak_ok") is False and m.get("mix_TP") is not None:
        new["narration_gain_db"] = float(params.get("narration_gain_db", 0.0)) - (m["mix_TP"] - (TRUE_PEAK_MAX - 0.5))
        changed = True
    if c.get("bed_loudness_ok") is False and m.get("bed_I") is not None:
        new["bed_gain_adjust_db"] = float(params.get("bed_gain_adjust_db", 0.0)) + (m["bed_target"] - m["bed_I"])
        changed = True
    if c.get("no_join_pops") is False and not params.get("remixed"):
        changed = True  # remix applies 30 ms fades at every join
    if changed:
        new["remixed"] = True
    # cover silent pocket needs a new BGM offset (bgm guard), visuals/OCR/duration: human.
    return new if changed else None


def fix_loop(task_dir: Path, qa: Callable[[Path], dict] | None = None,
             fixer: Callable[[Path, dict], Path] | None = None, max_rounds: int = MAX_FIX_ROUNDS,
             **qa_kwargs) -> dict:
    """QA -> (audio fix -> QA)*, at most ``max_rounds`` QA rounds, then flag a human."""
    qa = qa or (lambda d: run_render_qa(d, **qa_kwargs))
    fixer = fixer or remix_audio
    params: dict = {}
    rounds = []
    report: dict = {}
    for r in range(1, max_rounds + 1):
        report = qa(task_dir)
        rounds.append({"round": r, "params": dict(params), "pass": bool(report.get("pass")),
                       "issues": list(report.get("issues", []))})
        if report.get("pass") or r == max_rounds:
            break
        nxt = propose_fix(report, params)
        if nxt is None:
            break
        params = nxt
        fixer(task_dir, params)
    report = dict(report)
    report["rounds"] = rounds
    report["needs_human"] = not bool(report.get("pass"))
    return report
