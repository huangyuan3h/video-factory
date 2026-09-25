#!/usr/bin/env python
"""Generate a book/general/news episode in-process (script + render, or script-only).

Examples::

    cd apps/worker
    uv run python scripts/generate_episode.py --type book \
        --title "第一章" --content-file chapter.txt --script-only

    uv run python scripts/generate_episode.py --type general \
        --series-episodes /path/episodes.json --episode-index 2 \
        --out-dir DIR

    uv run python scripts/generate_episode.py --type news \
        --title "市场快讯" --script-only

Exit code is 0 on success / script_ready and 1 on failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make ``src`` importable when run as ``python scripts/generate_episode.py``.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.services.cli_runner import generic_main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(generic_main())
