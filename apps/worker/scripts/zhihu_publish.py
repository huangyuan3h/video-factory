#!/usr/bin/env python
"""Thin wrapper so `uv run python scripts/zhihu_publish.py ...` works (repo convention)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.publishers.zhihu_publish import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
