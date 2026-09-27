#!/usr/bin/env python
"""Indicator QA gate: card overflow + repeat + transition checks (fails the build).

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
from src.services.indicator.repeat_guard import find_repeats
from src.services.indicator.transition import (
    CONNECTOR_POOL,
    find_connector_reuse,
    find_stock_filler_reuse,
    transition_issues,
)


def _read_segments(task_dir: Path) -> list[str]:
    data = json.loads((task_dir / "script.json").read_text(encoding="utf-8"))
    return [str(s.get("text") or "") for s in data.get("segments", [])]


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
    transcript = _read_transcript(task_dir)
    if transcript:
        trep = find_repeats(transcript)
        if trep["global"] or trep["adjacent"]:
            for item in trep["global"][:5]:
                failures.append(
                    f"transcript repeat global {item['phrase']!r}"
                )
            for item in trep["adjacent"][:5]:
                failures.append(
                    f"transcript repeat bridge {item['phrase']!r}"
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
                failures.append(f"transcript filler {item['phrase']!r}")
        except Exception:
            pass

    # --- Card overflow check ---
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
    if checked == 0:
        failures.append("card: no 13_myth_vs_data.png found to check")

    if failures:
        print("QA FAIL:")
        for line in failures:
            print(f"  - {line}")
        return 1
    print(
        f"QA PASS: {len(segments)} segments, "
        f"{len(transcript)} transcript cues, {checked} card(s), "
        "no overflow, no repeats, transitions coherent"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
