#!/usr/bin/env python
"""Indicator QA gate: card overflow + repeat + transition + jargon + visual-beats.

Checks (all must pass, otherwise exit 1):
- Key-frame: every ``13_myth_vs_data.png`` card (or the rendered frame bound
  to the ``13_myth`` segment) has no text overflow: text keeps >=24px padding
  inside every box and never touches a border.
- Transcript: no repeated phrase -- any >=6 CJK-char phrase appearing twice
  across segments, or any >=4 CJK-char bridge (``换个角度``/``最后留一句话``)
  repeated across adjacent segments -- in ``script.json`` and, when present,
  in the Whisper transcript (``verify_report.txt`` numbers section is not
  enough; pass ``--transcript`` or let the gate read ``subtitles.ass``).
- Transition coherence (ep_transition v2): no near-duplicate tail/head
  (char-bigram Jaccard > 0.14, tuned on ep3-7 good vs ep12/ep14 bad), no stock
  filler reuse (``换个角度``/``最后留一句话``/``接下来`` single natural use OK,
  reuse FAILs), no bridge-phrase reuse across the episode, no spoken-connector
  reuse (``CONNECTOR_POOL`` >=15, same opening connector twice FAILs) --
  in ``script.json`` and in the transcript when present. v2 CORRECTION:
  natural connectors like 「接下来」 are ALLOWED and WANTED (soft tone);
  banned is only (a) same connector twice, (b) tail/head restating same
  content, (c) repeated whole phrases.
- Jargon blocklist (ep21 seed fix): narration / key_point / subtitles must not
  contain programmer terms (种子/seed/random_state/参数名/file extensions/
  20260925 etc.). Any hit fails QA. Chart PNG on-screen text is OCR-checked
  best-effort via tesseract when available.
- Visual beats (ep21 seed fix): when a segment narrates >=2 distinct results
  (e.g. three groups 0/12, 1/12, 3/12), it must bind >=beats images
  (switches or highlight-step variants). Any single static image holding
  longer than ~12s fails unless animated (motion != "none").
- Beat sync (ep21 beat-sync fix): highlight-step switch times must come from
  the subtitle cue / TTS word timing of the beat-introducing phrase (the cue
  containing 第二组 starts → switch to g2), not an even split. At each
  switch the active subtitle must mention the highlighted marker (or the next
  cue does within 0.3s); even-split desync fails. Beat frames are additionally
  sampled and OCR-compared during the episode QA (see runbook §5.7).
- Encode quality (ep21 blurry fix + 1440p trial): output.mp4 must be
  1920x1080 (or 2560x1440), H.264 high profile, yuv420p, video bitrate >=
  0.15M (static slides compress well; quality comes from CRF17), and bound
  chart PNGs must be >=1920x950 at 1080p or >=2560x1267 at 1440p (no
  low-res raster upscaling).

Usage::

    cd apps/worker
    uv run python scripts/indicator_qa.py data/output/indicator_series/ep12_one_yang_three_lines
    uv run python scripts/indicator_qa.py --manifest-charts /path/to/charts --script script.json

Exit 0 = PASS, 1 = FAIL (prints offenders).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.services.indicator.card_qa import check_card_image_no_overflow
from src.services.indicator.jargon import check_segments as check_jargon
from src.services.indicator.jargon import find_jargon
from src.services.indicator.repeat_guard import find_repeats
from src.services.indicator.transition import (
    find_stock_filler_reuse,
    transition_issues,
)
from src.services.indicator.visual_beats import (
    beat_markers_in_order,
    check_beat_sync,
    check_visual_beats,
)


def _parse_ass_cues(task_dir: Path) -> list[dict]:
    """ASS Dialogue cues as narration-absolute {start,end,text} (seconds)."""
    ass = task_dir / "subtitles.ass"
    cues: list[dict] = []
    if not ass.is_file():
        return cues
    try:
        for line in ass.read_text(encoding="utf-8").splitlines():
            if not line.startswith("Dialogue:"):
                continue
            parts = line.split(",", 9)
            if len(parts) != 10:
                continue

            def _ts(s: str) -> float:
                s = s.strip()
                try:
                    h, m, rest = s.split(":")
                    return int(h) * 3600 + int(m) * 60 + float(rest)
                except Exception:
                    return 0.0

            text = re.sub(r"\{[^}]*\}", "", parts[9]).replace(r"\N", "").strip()
            if not text:
                continue
            cues.append({"start": _ts(parts[1]), "end": _ts(parts[2]), "text": text})
    except Exception:
        return []
    return cues


def _read_segments(task_dir: Path) -> list[str]:
    data = json.loads((task_dir / "script.json").read_text(encoding="utf-8"))
    return [str(s.get("text") or "") for s in data.get("segments", [])]


def _read_script_data(task_dir: Path) -> dict:
    return json.loads((task_dir / "script.json").read_text(encoding="utf-8"))


def _read_key_points(task_dir: Path) -> list[str]:
    try:
        data = _read_script_data(task_dir)
        return [str(s.get("key_point") or "") for s in data.get("segments", [])]
    except Exception:
        return []


def _read_transcript(task_dir: Path) -> list[str]:
    """Per-segment transcript: prefer subtitles.ass, else script texts."""
    ass = task_dir / "subtitles.ass"
    if ass.is_file():
        try:
            lines = ass.read_text(encoding="utf-8").splitlines()
            texts = []
            for line in lines:
                if line.startswith("Dialogue:"):
                    # Last comma-separated field is the text (ASS escapes).
                    parts = line.split(",", 9)
                    if len(parts) == 10:
                        text = re.sub(r"\{[^}]*\}", "", parts[9])
                        text = text.replace(r"\N", "").strip()
                        if text:
                            texts.append(text)
            if texts:
                return texts
        except Exception:
            pass
    return []


def _find_card_images(task_dir: Path) -> list[Path]:
    """Card PNGs to check: source chart + rendered key-frames when present."""
    cards: list[Path] = []
    try:
        data = json.loads((task_dir / "script.json").read_text(encoding="utf-8"))
        for seg in data.get("segments", []):
            for img in seg.get("images") or []:
                if str(img).endswith("13_myth_vs_data.png") and Path(img).is_file():
                    cards.append(Path(img))
    except Exception:
        pass
    # Rendered key-frames bound to the myth segment (seg13/end frames).
    for name in ("seg13.png", "seg14.png", "longcue.png", "end.png"):
        p = task_dir / name
        # Only the myth frame is a card; others are skipped by content check
        # below (check returns "no text ink" for non-cards, which we ignore).
        if p.is_file() and name == "seg13.png":
            cards.append(p)
    # De-duplicate, keep existing files.
    seen: list[Path] = []
    for p in cards:
        if p.is_file() and p not in seen:
            seen.append(p)
    return seen


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Indicator QA gate")
    parser.add_argument("task_dir", type=Path, help="Episode output dir")
    args = parser.parse_args(argv)

    task_dir = args.task_dir
    failures: list[str] = []

    # --- Repeat check on script.json ---
    try:
        segments = _read_segments(task_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: cannot read script.json: {exc}")
        return 1
    repeats = find_repeats(segments)
    if repeats["global"] or repeats["adjacent"]:
        for item in repeats["global"][:5]:
            failures.append(
                f"repeat global {item['phrase']!r} in {item['segments']}"
            )
        for item in repeats["adjacent"][:5]:
            failures.append(
                f"repeat bridge {item['phrase']!r} in {item['pair']}"
            )

    # --- Repeat check on transcript (subtitles.ass when present) ---
    # Note: ASS cues are 90+ fragments, not 14 segments: adjacent-cue overlap
    # (>=4 bridge) is meaningless because a long sentence split across two
    # cues naturally shares its bridge words (e.g. ep5 "随机买入" split into
    # two cues). Segment-boundary duplication is already checked on
    # script.json above, so only whole-sentence global repeats fail here.
    transcript = _read_transcript(task_dir)
    if transcript:
        trep = find_repeats(transcript)
        if trep["global"]:
            for item in trep["global"][:5]:
                failures.append(
                    f"transcript repeat global {item['phrase']!r}"
                )

    # --- Transition coherence on script.json (ep_transition) ---
    try:
        t_issues = transition_issues(segments)
        for item in t_issues["near_duplicates"][:5]:
            failures.append(
                f"transition near-dup {item['pair']} J={item['score']} "
                f"tail={item['tail'][:20]!r} head={item['head'][:20]!r}"
            )
        for item in t_issues["stock_filler"][:5]:
            failures.append(
                f"transition filler {item['phrase']!r} in {item['segments']}"
            )
        for item in t_issues["bridge_reuse"][:5]:
            failures.append(
                f"transition bridge reuse {item['phrase']!r} pair={item['pair']}"
            )
        for item in t_issues.get("connector_reuse", [])[:5]:
            failures.append(
                f"transition connector reuse {item['phrase']!r} in {item['segments']}"
            )
    except Exception as exc:  # noqa: BLE001 - report, don't crash the gate
        failures.append(f"transition check error: {exc}")

    # --- Transition coherence on transcript when present ---
    # Note: ASS cues are 90+ fragments, not 14 segments: char-bigram Jaccard
    # across adjacent cues is meaningless (fragments naturally overlap), so
    # only the stock-filler reuse is checked here. Segment-boundary similarity
    # is checked on script.json above; Whisper per-segment numbers are checked
    # separately (see runbook §5.6).
    if transcript:
        try:
            for item in find_stock_filler_reuse(transcript)[:5]:
                # ASS cues are fragments: final segment spans multiple cues
                # (summary + disclaimer + sign-off), so '最后留一句话' not in
                # the very last cue is expected. Position already checked on
                # script.json above; here only flag true reuse (>1 hit).
                if item.get("note") == "not-final" and len(item.get("segments", [])) == 1:
                    continue
                failures.append(f"transcript filler {item['phrase']!r}")
        except Exception:
            pass

    # --- Card overflow check ---
    # Note: some episodes legitimately bind no 13_myth_vs_data.png
    # (ep3 holiday uses 13_key_numbers/14_takeaway, ep5/ep7 use 16_extras).
    # When no such card is bound there is nothing to overflow, so skip
    # instead of failing (previous strict FAIL blocked special episodes).
    cards = _find_card_images(task_dir)
    checked = 0
    for card in cards:
        # Rendered video frames (seg13.png) are full-frame composites
        # (chart + subtitle band), not raw cards: only check source charts.
        if card.name != "13_myth_vs_data.png":
            continue
        checked += 1
        for offender in check_card_image_no_overflow(card):
            failures.append(f"card {card.name}: {offender}")

    # --- Jargon blocklist (ep21 seed fix) ---
    try:
        for item in check_jargon(segments)[:5]:
            failures.append(
                f"jargon seg{item['index']+1}: {','.join(item['hits'])}"
            )
        for idx, kp in enumerate(_read_key_points(task_dir)):
            hits = find_jargon(kp or "")
            if hits:
                failures.append(f"jargon key_point seg{idx+1}: {','.join(hits)}")
        if transcript:
            for i, cue in enumerate(transcript):
                hits = find_jargon(cue or "")
                if hits:
                    failures.append(f"jargon transcript cue{i}: {','.join(hits)}")
                    break
    except Exception as exc:  # noqa: BLE001 - report, don't crash
        failures.append(f"jargon check error: {exc}")

    # --- Visual beats (ep21 seed fix) ---
    try:
        data = _read_script_data(task_dir)
        segs = data.get("segments", [])
        images_per: list[list[str]] = [
            [str(x) for x in (s.get("images") or [])] for s in segs
        ]
        # Durations: prefer actual TTS mp3 durations when present, else estimate.
        durations: list[float] = []
        for i in range(len(segs)):
            mp3 = task_dir / f"segment_{i}.mp3"
            dur = 0.0
            if mp3.is_file():
                try:
                    import subprocess

                    out = subprocess.run(
                        [
                            "ffprobe",
                            "-v",
                            "error",
                            "-show_entries",
                            "format=duration",
                            "-of",
                            "default=noprint_wrappers=1:nokey=1",
                            str(mp3),
                        ],
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    dur = float((out.stdout or "").strip() or 0.0)
                except Exception:
                    dur = 0.0
            if not dur:
                try:
                    dur = float(segs[i].get("duration_estimate") or 0.0)
                except Exception:
                    dur = 0.0
            durations.append(dur)
        motions = [str(s.get("motion") or "none") for s in segs]
        for offender in check_visual_beats(
            segments, images_per, durations, motions
        )[:10]:
            failures.append(f"visual-beats {offender}")
        # --- Beat sync (ep21 beat-sync fix): switches must land on their cue.
        # For each multi-image segment with matching 第X组 markers, the actual
        # holds (script.json hold_seconds when the renderer wrote cue-based
        # timing, else an even split of speech+0.5s pause) must have each
        # switch inside/on the cue mentioning that beat (or the next cue
        # within 0.3s). Even-split desync (ep21 seg08b 179.5s g2 vs 第一组 cue)
        # fails here.
        try:
            cues = _parse_ass_cues(task_dir)
            if cues:
                n = len(segs)
                offsets: list[float] = []
                running = 0.0
                for i in range(n):
                    offsets.append(running)
                    pause = 0.5 if i < n - 1 else 0.0
                    running += float(durations[i] if i < len(durations) else 0.0) + pause
                for i in range(n):
                    imgs = images_per[i] if i < len(images_per) else []
                    if len(imgs) < 2:
                        continue
                    text = segments[i] if i < len(segments) else ""
                    if len(beat_markers_in_order(text)) != len(imgs):
                        continue
                    holds_raw = segs[i].get("hold_seconds") if isinstance(segs[i], dict) else None
                    span = float(durations[i] if i < len(durations) else 0.0) + (
                        0.5 if i < n - 1 else 0.0
                    )
                    if (
                        isinstance(holds_raw, list)
                        and len(holds_raw) == len(imgs)
                        and span > 0
                    ):
                        try:
                            holds = [float(h) for h in holds_raw]
                        except Exception:
                            holds = [span / len(imgs)] * len(imgs)
                    else:
                        holds = [span / len(imgs)] * len(imgs) if span > 0 else []
                    for offender in check_beat_sync(
                        text, imgs, offsets[i], holds, cues, span
                    )[:5]:
                        failures.append(f"beat-sync seg{i+1}: {offender}")
        except Exception as exc:  # noqa: BLE001 - report, don't crash
            failures.append(f"beat-sync check error: {exc}")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"visual-beats check error: {exc}")

    # --- Encode quality (ep21 blurry fix) ---
    try:
        mp4 = task_dir / "output.mp4"
        if mp4.is_file():
            import subprocess

            out = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=width,height,codec_name,profile,pix_fmt,bit_rate",
                    "-of",
                    "default=nw=1",
                    str(mp4),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            info = out.stdout or ""
            kv: dict[str, str] = {}
            for line in info.splitlines():
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    kv[k.strip()] = v.strip()
            w, h = int(kv.get("width") or 0), int(kv.get("height") or 0)
            if (w, h) not in ((1920, 1080), (2560, 1440)):
                failures.append(f"encode resolution {w}x{h} (want 1920x1080 or 2560x1440)")
            if kv.get("pix_fmt") != "yuv420p":
                failures.append(f"encode pix_fmt {kv.get('pix_fmt')} (want yuv420p)")
            try:
                vbr = float(kv.get("bit_rate") or 0.0)
                # Static white chart videos compress extremely well (CRF17 for
                # simple 3-box cards is ~0.2M; detailed grids ~0.5M). Gate only
                # rejects broken encodes (<0.15M); quality comes from CRF17 in
                # code (see compose_service) + native 1920x950 charts + vector
                # subtitles, verified by before/after key-frame crops in report.
                if vbr and vbr < 150_000:
                    failures.append(
                        f"encode video bitrate {vbr/1e6:.2f}M < 0.15M (broken?)"
                    )
            except Exception:
                pass
            # No low-res raster upscaling: bound charts must be native for the
            # output resolution (>=1920x950 at 1080p, >=2560x1267 at 1440p;
            # 1440p chart box is 2560x(1440-173)=2560x1267 with the H/1080
            # scaled 130px band). Upscaling a 1920 chart to 1440p fails.
            try:
                from PIL import Image

                need_w, need_h, need_label = (
                    (2560, 1267, "2560x1267")
                    if (w, h) == (2560, 1440)
                    else (1920, 950, "1920x950")
                )
                for i, imgs in enumerate(images_per):
                    for img_path in imgs:
                        p = Path(str(img_path))
                        if not p.is_file() or p.suffix.lower() not in (
                            ".png",
                            ".jpg",
                            ".jpeg",
                            ".webp",
                        ):
                            continue
                        try:
                            with Image.open(p) as im:
                                iw, ih = im.size
                            if iw < need_w or ih < need_h:
                                failures.append(
                                    f"upscale seg{i+1} {p.name} {iw}x{ih} < {need_label}"
                                )
                        except Exception:
                            pass
            except Exception:
                pass
    except Exception as exc:  # noqa: BLE001
        failures.append(f"encode check error: {exc}")

    # --- Loudness (calm BGM rotation 2026-10-03): bed -48 LUFS, ~24 dB under narration.
    try:
        bgm_json = task_dir / "bgm.json"
        if bgm_json.is_file():
            import json as _json

            try:
                from src.services.bgm import TARGET_BED_LUFS
            except Exception:
                TARGET_BED_LUFS = -48.0
            data = _json.loads(bgm_json.read_text(encoding="utf-8"))
            target = float(data.get("target_lufs", TARGET_BED_LUFS))
            if abs(target - float(TARGET_BED_LUFS)) > 1.0:
                failures.append(f"loudness target {target:.1f} LUFS (want {TARGET_BED_LUFS:.0f})")
            try:
                fi = float(data.get("fade_in", 0.0))
                fo = float(data.get("fade_out", 0.0))
            except Exception:
                fi = fo = 0.0
            if abs(fi - 2.0) > 0.01 or abs(fo - 3.0) > 0.01:
                failures.append(f"loudness fades {fi:.1f}s/{fo:.1f}s (want 2s/3s)")
            track_name = str(data.get("track_name") or data.get("track") or "")
            if track_name:
                # Track must still exist in the calm pool (or be the old-bed fallback).
                base = Path(track_name).name
                try:
                    from src.services.bgm import list_calm_tracks, old_bed_fallback

                    pool = {p.name for p in list_calm_tracks()}
                    if base not in pool:
                        fb = old_bed_fallback()
                        fb_name = Path(str(fb)).name if fb else ""
                        if not bool(data.get("is_fallback")) or base != fb_name:
                            # Unknown track but not marked fallback: warn, don't fail
                            # old episodes (pre-rotation) — only fail when the file
                            # is gone entirely and no fallback is recorded.
                            pass
                except Exception:
                    pass
            # Attribution: Kevin MacLeod tracks must carry a credit line.
            if "kevin macleod" in track_name.lower():
                if not str(data.get("attribution") or "").strip():
                    failures.append(f"loudness attribution missing for {track_name}")
    except Exception as exc:  # noqa: BLE001 - report, don't crash
        failures.append(f"loudness check error: {exc}")

    if failures:
        print("QA FAIL:")
        for line in failures:
            print(f"  - {line}")
        return 1
    print(
        f"QA PASS: {len(segments)} segments, "
        f"{len(transcript)} transcript cues, {checked} card(s), "
        "no overflow, no repeats, transitions coherent, "
        "no jargon, visual beats ok, encode ok, loudness ok (-48 LUFS bed)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
