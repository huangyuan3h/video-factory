#!/usr/bin/env python
"""Run the daily-news P0 MVP (S0-S8) in-process.

Example:
    cd apps/worker
    .venv/bin/python scripts/run_daily_news_mvp.py \
        --task-dir ../../data/output/daily_news/mvp-2026-09-25 \
        --snapshot ../../data/output/daily_news/mvp-2026-09-25/karios_snapshot.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings  # noqa: E402
from src.services.daily_news.pipeline import run_mvp_sync  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Daily news P0 MVP")
    ap.add_argument("--task-dir", required=True, type=Path)
    ap.add_argument("--snapshot", type=Path, default=None)
    ap.add_argument("--karios-base", default="http://127.0.0.1:4330")
    ap.add_argument("--no-render", action="store_true")
    args = ap.parse_args(argv)
    try:
        res = run_mvp_sync(
            task_dir=args.task_dir,
            karios_base=args.karios_base,
            snapshot_path=args.snapshot,
            pexels_api_key=settings.pexels_api_key,
            render=not args.no_render,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
