#!/usr/bin/env python
"""Generate a manifest-driven ``type=indicator`` chart episode in-process.

Examples::

    cd apps/worker
    uv run python scripts/indicator_episode.py \
        --manifest /path/to/charts/manifest.json [--title "MACD 金叉"] \
        [--context /path/to/summary_zh.md] [--voice zh-CN-YunxiNeural] \
        [--out-dir DIR] --script-only

    uv run python scripts/indicator_episode.py \
        --approved-script DIR/script.json [--out-dir DIR2]

    uv run python scripts/indicator_episode.py --manifest /path/to/charts/manifest.json

Exit code is 0 on success / script_ready and 1 on failure. See
``docs/indicator-episodes.md`` for the full workflow.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make ``src`` importable when run as ``python scripts/indicator_episode.py``.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.services.cli_runner import indicator_main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(indicator_main())
