#!/usr/bin/env python
"""Post-render auto QA gate (video-use self-eval) for one rendered task dir.

Usage::

    cd apps/worker
    uv run python scripts/render_qa.py TASK_DIR [--episode N] [--fix] [--json]

Checks (see ``src/services/render_qa.py``): ebur128 mix/narration/bed loudness
+ true peak, cover 1-3s not a silent pocket, duration (and video stream) vs the
timeline.json (or task.log) plan, frames at every segment cut +-1.5s (black / flash / subtitle ink
in the band), pops at every narration join, cover + first-frame episode OCR.
``--fix`` allows at most 3 QA rounds with audio-only re-mix fixes (keeps
``output.pre_fix.mp4``); anything else stops with ``needs_human``.
Writes ``TASK_DIR/render_qa.json``. Exit 0 PASS, 1 FAIL.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.services.render_qa import MAX_FIX_ROUNDS, fix_loop, run_render_qa  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Post-render auto QA (video-use)")
    ap.add_argument("task_dir", type=Path)
    ap.add_argument("--episode", type=int, default=None, help="expected episode number (default: from script.json title)")
    ap.add_argument("--fix", action="store_true", help=f"audio-only self-fix, at most {MAX_FIX_ROUNDS} rounds")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.fix:
        rep = fix_loop(args.task_dir, episode=args.episode)
    else:
        rep = run_render_qa(args.task_dir, episode=args.episode)
        rep["needs_human"] = not rep.get("pass")
    out = args.task_dir / "render_qa.json"
    try:
        out.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    lm = (rep.get("metrics") or {}).get("loudness", {})
    summary = (f"RENDER QA {'PASS' if rep.get('pass') else 'FAIL'}: mix {lm.get('mix_I')} LUFS TP {lm.get('mix_TP')} "
               f"narr {lm.get('narration_I')} bed {lm.get('bed_I')} cover {lm.get('cover_1_3s_I')} "
               f"cuts {len(rep.get('cuts', []))} joins {len(rep.get('joins', []))} "
               f"ocr {(rep.get('metrics') or {}).get('cover_ocr', {}).get('status')}")
    if args.json:
        print(json.dumps({k: rep.get(k) for k in ("pass", "needs_human", "checks", "issues", "metrics", "rounds")},
                         ensure_ascii=False))
    else:
        print(summary)
        for i in rep.get("issues", []):
            print(f"  - {i}")
    return 0 if rep.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
