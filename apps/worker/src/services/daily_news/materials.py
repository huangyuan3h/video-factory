"""P0 materials: Pexels video search with Tier-1 attribution + text-prior relevance.

Only sources from design §5.1 Tier-1 are used (pexels/pixabay here; official/
press-kit/CC-YT/Commons arrive in P1). GNews images are never used as visuals.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone, UTC
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

PEXELS_SEARCH = "https://api.pexels.com/v1/videos/search"

# Chinese segment keywords -> English Pexels queries (P0 hand-mapped, safe).
EN_QUERIES = {
    "美国国债": "us treasury bonds",
    "债券收益率": "bond chart finance",
    "财经新闻": "financial news studio",
    "石油设施": "oil refinery plant",
    "炼油厂": "oil refinery",
    "沙漠油田": "desert oil field",
    "数据图表": "stock market chart",
    "股票走势": "stock chart screen",
    "财经数据": "financial data screen",
    "新闻发布会": "press conference podium",
    "财经访谈": "business interview",
    "城市夜景": "city night skyline",
    "交易大厅": "stock exchange trading floor",
    "股票市场": "stock market",
    "城市天际线": "city skyline",
    "美元": "us dollar bills closeup",
    "华尔街": "wall street new york stock exchange",
}


def english_query(keywords: list[str]) -> str:
    parts = [EN_QUERIES.get(k, k) for k in (keywords or [])]
    return " ".join(parts)[:120] or "financial news"


def score_relevance(item: dict, keywords: list[str]) -> float:
    """Text-prior score 0-100: query hit + whitelist + landscape + recency."""
    score = 55.0  # Pexels search itself is a relevance prior
    q = english_query(keywords).lower()
    title = f"{item.get('title','')} {item.get('photographer','')}".lower()
    hits = sum(1 for w in q.split() if len(w) > 3 and w in title)
    score += min(20.0, hits * 5.0)
    if str(item.get("page_url", "")).startswith("https://www.pexels.com/"):
        score += 10.0
    if int(item.get("width") or 0) >= 1280:
        score += 5.0
    return round(min(100.0, score), 1)


async def fetch_pexels_videos_with_attribution(
    keywords: list[str],
    count: int,
    dest_dir: Path,
    api_key: str | None,
    client: httpx.AsyncClient | None = None,
) -> tuple[list[Path], list[dict]]:
    """Search Pexels, download landscape mp4s, return (files, attribution)."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    if not api_key:
        return [], []
    owns = client is None
    if owns:
        client = httpx.AsyncClient(timeout=60.0)
    files, attrs = [], []
    try:
        resp = await client.get(
            PEXELS_SEARCH,
            params={"query": english_query(keywords), "per_page": max(count, 3),
                    "orientation": "landscape"},
            headers={"Authorization": api_key},
        )
        resp.raise_for_status()
        for v in (resp.json().get("videos", []) or [])[:count]:
            vid = v.get("id")
            files_meta = v.get("video_files", []) or []
            # Prefer 1920-wide landscape mp4, else largest.
            landscape = [f for f in files_meta if (f.get("width") or 0) >= (f.get("height") or 0)]
            landscape.sort(key=lambda f: (f.get("width") or 0), reverse=True)
            pick = None
            for f in landscape:
                if (f.get("width") or 0) >= 1280 and str(f.get("link", "")).endswith(".mp4"):
                    pick = f
                    break
            pick = pick or (landscape[0] if landscape else None)
            if not pick or not pick.get("link"):
                continue
            dl = await client.get(pick["link"], timeout=120.0)
            dl.raise_for_status()
            data = dl.content or b""
            if len(data) < 50_000:
                continue
            path = dest_dir / f"pexels_{vid}.mp4"
            path.write_bytes(data)
            item = {
                "id": vid,
                "page_url": v.get("url", ""),
                "photographer": (v.get("user") or {}).get("name", ""),
                "width": pick.get("width"),
                "height": pick.get("height"),
                "title": "",
            }
            rel = score_relevance(item, keywords)
            files.append(path)
            attrs.append({
                "file": path.name,
                "source_name": "Pexels",
                "source_url": v.get("url", ""),
                "license_tier": "tier1-safe",
                "license_name": "pexels",
                "author": (v.get("user") or {}).get("name", ""),
                "retrieved_at": datetime.now(UTC).isoformat(),
                "relevance_score": rel,
                "query": english_query(keywords),
                "width": pick.get("width"),
                "height": pick.get("height"),
            })
            logger.info(f"Pexels video {vid} -> {path.name} rel={rel}")
    except Exception as exc:  # noqa: BLE001 - P0 falls back to data cards
        logger.warning(f"Pexels fetch failed for {keywords}: {exc}")
    finally:
        if owns:
            await client.aclose()
    _ = time.time()
    return files, attrs
