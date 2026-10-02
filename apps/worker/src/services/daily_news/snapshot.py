"""Karios snapshot fetch (read-only HTTP, never touches karios-desktop files)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timezone
from pathlib import Path
from urllib.request import urlopen


def _get(base_url: str, path: str, timeout: float = 15.0) -> dict:
    with urlopen(base_url.rstrip("/") + path, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_karios_snapshot(base_url: str, out_path: str | Path) -> Path:
    """Fetch morning/midday brief + recent items; write ``karios_snapshot.json``.

    Returns the snapshot path. Raises on network failure (caller decides
    fallback to yesterday's snapshot per design S0).
    """
    morning = _get(base_url, "/api/news/brief/latest?brief_type=morning")
    midday = _get(base_url, "/api/news/brief/latest?brief_type=midday")
    items = _get(base_url, "/api/news/items?limit=100&hours=72")
    payload = {
        "pulled_at": datetime.now(UTC).isoformat(),
        "base_url": base_url,
        "morning": morning,
        "midday": midday,
        "items_total": items.get("total", len(items.get("items", []))),
        "items": items.get("items", items)[:30],
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def load_snapshot(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def brief_items(snapshot: dict, which: str = "morning") -> list[dict]:
    node = (snapshot.get(which) or {})
    brief = node.get("brief", node)
    items = brief.get("items") or []
    return list(items)


def brief_id(snapshot: dict, which: str = "morning") -> str:
    node = (snapshot.get(which) or {})
    brief = node.get("brief", node)
    return str(brief.get("id") or brief.get("briefDate") or which)
