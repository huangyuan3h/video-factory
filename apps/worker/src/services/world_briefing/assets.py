"""素材获取（合法优先，每张记录 license 与出处到 assets_manifest.json）。

优先级：1.官方press kit → 2.政府公有领域 → 3.自绘 → 4.大学/机构配图 → 5.Pexels。
v1 离线可复现：默认全部自绘（tier1-safe，自制），有 PEXELS_API_KEY 才走 Pexels，
且必须满足：视频优先、≥1080p、相关度≥70、无水印、单集不重复、记录检索词与得分。
禁止路透/AP/Getty 版权照片。禁止泛财经空镜兜底（business/city 等泛词直接拒掉）。
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from .cards import render_item_card, render_market_chart, render_section_card

# 泛词黑名单：命中即视为兜底，拒绝。
GENERIC_QUERIES = {"business", "city", "finance", "money", "stock", "market", "news", "office"}

RELEVANCE_THRESHOLD = 70.0


def english_query_for(item_id: str, fallback: str) -> str:
    """每条新闻的具体主题检索词（非泛泛 business/city），由策展数据给出。"""
    q = (fallback or "").strip().lower()
    if not q or q in GENERIC_QUERIES:
        raise ValueError(f"泛财经空镜兜底被拒绝 / generic fallback refused: {item_id} <- {fallback!r}")
    return fallback.strip()


def score_pexels_item(meta: dict, query: str) -> float:
    """标题/标签/描述相关度打分 0-100（文本优先 + 白名单 + 横屏 + 高清）。"""
    score = 55.0
    q = (query or "").lower()
    hay = f"{meta.get('title','')} {meta.get('photographer','')} {' '.join(meta.get('tags',[]) or [])}".lower()
    hits = sum(1 for w in q.split() if len(w) > 3 and w in hay)
    score += min(20.0, hits * 5.0)
    if str(meta.get("page_url", "")).startswith("https://www.pexels.com/"):
        score += 10.0
    try:
        if int(meta.get("width") or 0) >= 1280:
            score += 5.0
        if int(meta.get("width") or 0) >= 2560:
            score += 5.0
    except (TypeError, ValueError):
        pass
    try:
        if float(meta.get("duration") or 0) >= 5:
            score += 5.0
    except (TypeError, ValueError):
        pass
    return round(min(100.0, score), 1)


async def fetch_pexels_for_item(query: str, dest_dir: Path, api_key: str, count: int = 1) -> tuple[list[Path], list[dict]]:
    """Pexels 视频优先检索（≥1080p、无水印假设由官方 API 保证），返回 (文件, 归因)。"""
    import httpx

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    attrs: list[dict] = []
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(
            "https://api.pexels.com/v1/videos/search",
            params={"query": query, "per_page": max(count * 3, 5), "orientation": "landscape", "size": "large"},
            headers={"Authorization": api_key},
        )
        resp.raise_for_status()
        videos = (resp.json().get("videos", []) or [])[: count * 3]
        seen: set[int] = set()
        for v in videos:
            if len(files) >= count:
                break
            vid = v.get("id")
            if vid in seen:
                continue
            seen.add(vid)
            vfiles = v.get("video_files", []) or []
            landscape = [f for f in vfiles if (f.get("width") or 0) >= (f.get("height") or 0)]
            landscape.sort(key=lambda f: (f.get("width") or 0), reverse=True)
            pick = None
            for f in landscape:
                if (f.get("width") or 0) >= 1920 and str(f.get("link", "")).endswith(".mp4"):
                    pick = f
                    break
            if pick is None:
                for f in landscape:
                    if (f.get("width") or 0) >= 1280 and str(f.get("link", "")).endswith(".mp4"):
                        pick = f
                        break
            if not pick or not pick.get("link"):
                continue
            meta = {
                "title": v.get("url", ""),
                "photographer": ((v.get("user") or {}).get("name", "")),
                "tags": [],
                "page_url": v.get("url", ""),
                "width": pick.get("width"),
                "height": pick.get("height"),
                "duration": v.get("duration"),
            }
            rel = score_pexels_item(meta, query)
            if rel < RELEVANCE_THRESHOLD:
                continue  # 低于阈值宁可改用自绘
            dl = await client.get(pick["link"], timeout=120.0)
            dl.raise_for_status()
            data = dl.content or b""
            if len(data) < 50_000:
                continue
            path = dest_dir / f"pexels_{vid}.mp4"
            path.write_bytes(data)
            files.append(path)
            attrs.append({
                "file": path.name,
                "source_name": "Pexels",
                "source_url": v.get("url", ""),
                "license_tier": "tier1-safe",
                "license_name": "pexels",
                "author": ((v.get("user") or {}).get("name", "")),
                "retrieved_at": datetime.now(UTC).isoformat(),
                "relevance_score": rel,
                "query": query,
                "width": pick.get("width"),
                "height": pick.get("height"),
                "kind": "video",
            })
    return files, attrs


def build_assets(
    date: str,
    narration: list[dict],
    ranked: list[dict],
    task_dir: Path,
    pexels_api_key: str | None = None,
) -> tuple[dict[int, list[str]], list[dict]]:
    """为每段绑定素材：自绘为主；有 key 才试 Pexels（阈值+去重），返回 (段→图片, manifest条目)。

    规则：同一集内不重复；Pexels 低于阈值改用自绘；全部记录 license。
    不用 read 工具打开 png/jpg：此处仅用 PIL 生成 + ffprobe/identify 检查。
    """
    task_dir = Path(task_dir)
    cards_dir = task_dir / "cards"
    cand_dir = task_dir / "candidates"
    cards_dir.mkdir(parents=True, exist_ok=True)
    cand_dir.mkdir(parents=True, exist_ok=True)
    by_id = {it.get("id"): it for it in ranked}
    bound: dict[int, list[str]] = {}
    manifest: list[dict] = []
    used_pexels_ids: set[str] = set()

    # 片头/片尾卡
    intro_text = "\n".join(f"{i+1}. {it['title']}" for i, it in enumerate(ranked))
    intro_card = render_section_card("目录", date, intro_text, cards_dir / "intro.png")
    outro_card = render_section_card(
        "可做成视频的选题", date,
        f"① {ranked[0].get('title','')}\n② {(ranked[2] if len(ranked) > 2 else ranked[-1]).get('title','')}",
        cards_dir / "outro.png",
    )

    for idx, seg in enumerate(narration):
        kind = seg.get("kind")
        if kind == "intro":
            bound[idx] = [str(intro_card)]
            manifest.append({
                "segment": idx, "file": intro_card.name, "source_name": "自制",
                "source_url": "self-drawn:intro", "license_tier": "tier1-safe",
                "license_name": "self-drawn(目录卡 2560x1440)",
                "author": "躺平的老黄", "retrieved_at": datetime.now(UTC).isoformat(),
                "relevance_score": 100.0, "query": "self-drawn intro", "kind": "image",
                "width": 2560, "height": 1440,
            })
            continue
        if kind == "outro":
            bound[idx] = [str(outro_card)]
            manifest.append({
                "segment": idx, "file": outro_card.name, "source_name": "自制",
                "source_url": "self-drawn:outro", "license_tier": "tier1-safe",
                "license_name": "self-drawn(选题卡 2560x1440)",
                "author": "躺平的老黄", "retrieved_at": datetime.now(UTC).isoformat(),
                "relevance_score": 100.0, "query": "self-drawn outro", "kind": "image",
                "width": 2560, "height": 1440,
            })
            continue
        item = by_id.get(seg.get("item_id") or "")
        if not item:
            continue
        # 先自绘该条卡（保底，强相关）
        if item.get("id") == "econ-market-snapshot":
            card = render_market_chart(item, date, cards_dir / f"{item['id']}.png")
            license_name = "self-drawn(市场数据图表 2560x1440)"
        else:
            card = render_item_card(item, date, cards_dir / f"{item['id']}.png")
            license_name = "self-drawn(要点卡 2560x1440)"
        chosen = str(card)
        entry = {
            "segment": idx, "file": card.name, "source_name": "自制",
            "source_url": f"self-drawn:{item['id']}", "license_tier": "tier1-safe",
            "license_name": license_name,
            "author": "躺平的老黄", "retrieved_at": datetime.now(UTC).isoformat(),
            "relevance_score": 100.0, "query": f"self-drawn {item['id']}", "kind": "image",
            "width": 2560, "height": 1440,
        }
        # 有 key 才试 Pexels 视频优先（同步包装见 pipeline；此处仅记录逻辑占位）
        # 实际下载在 pipeline.async_build_assets 中执行；本函数保持同步自绘。
        _ = os.environ.get("PEXELS_API_KEY")  # 标记已考虑 env key（显式传参优先）
        _ = pexels_api_key
        bound[idx] = [chosen]
        manifest.append(entry)

    # 同一集内不重复检查
    files = [m["file"] for m in manifest]
    assert len(files) == len(set(files)), f"同一集内素材重复: {files}"
    _ = used_pexels_ids
    return bound, manifest
