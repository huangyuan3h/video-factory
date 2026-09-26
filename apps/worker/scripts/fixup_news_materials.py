#!/usr/bin/env python
"""P0 fixup: replace weakly-relevant clips (seg0 crypto screen, seg3 politician)
with neutral finance/city clips, then update attribution + search_log.

Usage:
    cd apps/worker
    .venv/bin/python scripts/fixup_news_materials.py \
        --task-dir ../../data/output/daily_news/mvp-2026-09-25
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings  # noqa: E402
from src.services.daily_news.materials import (  # noqa: E402
    fetch_pexels_videos_with_attribution,
)

# segment -> safer replacement keywords (neutral, no recognizable people)
REPLACEMENTS = {
    0: ["股票走势", "财经数据", "股票市场"],
    3: ["城市夜景", "城市天际线"],
}


async def _main(task_dir: Path) -> dict:
    cand = task_dir / "candidates"
    attr_path = task_dir / "material_attribution.json"
    log_path = task_dir / "search_log.json"
    attr = json.loads(attr_path.read_text(encoding="utf-8"))
    log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else {"log": []}
    drop_files: list[str] = []
    for seg_idx, keywords in REPLACEMENTS.items():
        files, attrs = await fetch_pexels_videos_with_attribution(
            keywords, 2, cand, settings.pexels_api_key
        )
        if not files:
            print(f"seg{seg_idx}: refetch empty, keep old", flush=True)
            continue
        # Prefer a clip whose author/title hints finance/city, skip people clips.
        pick = None
        for f, a in zip(files, attrs):
            low = f"{a.get('source_url','')}".lower()
            if any(bad in low for bad in ("speech", "candidate", "politician", "crypto")):
                drop_files.append(f.name)
                continue
            pick = (f, a)
            break
        pick = pick or (files[0], attrs[0])
        f, a = pick
        a["segment"] = seg_idx
        # Remove old entries/files for this segment (keep data-card seg untouched).
        kept = []
        for m in attr["materials"]:
            if int(m.get("segment", -1)) == seg_idx:
                drop_files.append(m.get("file", ""))
            else:
                kept.append(m)
        kept.append(a)
        attr["materials"] = kept
        log["log"].append({"segment": seg_idx, "refetch_query": keywords,
                           "files": [x.name for x in files], "kept": f.name})
        print(f"seg{seg_idx}: kept {f.name} rel={a.get('relevance_score')}", flush=True)
    for name in set(drop_files):
        p = cand / name
        if p.exists() and p.name not in [m.get("file") for m in attr["materials"]]:
            p.unlink()
            print(f"dropped {name}", flush=True)
    attr_path.write_text(json.dumps(attr, ensure_ascii=False, indent=2), encoding="utf-8")
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"materials": len(attr["materials"])}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-dir", required=True, type=Path)
    args = ap.parse_args(argv)
    try:
        res = asyncio.run(_main(args.task_dir))
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
