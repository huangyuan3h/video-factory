#!/usr/bin/env python
"""世界简报一集式入口（vf briefing 的 worker 侧实现）。

Examples::

    cd apps/worker
    uv run python scripts/run_briefing.py --date 2026-10-03 --text-only
    uv run python scripts/run_briefing.py --date 2026-10-03 --out-dir /tmp/briefing
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.services.world_briefing.pipeline import run_full, run_text_only  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="run_briefing.py", description="世界简报一集式（md + mp4 + cover + desc + manifest）")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--out-dir", type=Path, default=None)
    p.add_argument("--text-only", action="store_true")
    p.add_argument("--voice", default=None)
    p.add_argument("--resolution", default="2560x1440")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out = args.out_dir or (Path.cwd().parent.parent / "data" / "output" / "world_briefing" / args.date)
    try:
        if args.text_only:
            res = run_text_only(args.date, out)
        else:
            res = run_full(args.date, out, voice=args.voice, resolution=args.resolution)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"TASK_DIR: {res.get('out_dir')}")
    print(f"status: {res.get('factcheck')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
