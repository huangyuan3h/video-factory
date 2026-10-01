"""P0 topic picker: one finance contradiction from the morning brief."""

from __future__ import annotations

from .snapshot import brief_id, brief_items


def pick_finance_topic(snapshot: dict) -> dict:
    """Pick the top finance topic (highest-score macro item + oil-chain cluster).

    Returns ``topic.json``-shaped dict with title/entities/event_date/
    evidence_links/angle. Numbers are copied verbatim from the snapshot.
    """
    items = brief_items(snapshot, "morning")
    if not items:
        raise ValueError("morning brief 为空，无法选题（P0 停更）")
    by_score = sorted(items, key=lambda it: float(it.get("score") or 0), reverse=True)
    top = by_score[0]
    # Oil-chain cluster: titles mentioning 阿美/胡塞/石油/炼油/储备.
    keywords = ("阿美", "胡塞", "石油", "炼油", "储备", "沙特", "G7")
    cluster = [it for it in by_score[1:] if any(k in str(it.get("title", "")) for k in keywords)][:4]
    evidence = [top, *cluster]
    entities = ["美国10年期国债", "沙特阿美", "胡塞武装", "法国", "G7战略石油储备", "欧洲炼油"]
    dates = sorted({str(it.get("publishedAt", ""))[:10] for it in evidence if it.get("publishedAt")})
    topic = {
        "title": "昨日盘点：美债10年期收益率涨穿5.2%撞上石油供给冲击",
        "brief_id": brief_id(snapshot, "morning"),
        "entities": entities,
        "event_date": dates[0] if dates else "",
        "event_dates": dates,
        "evidence_links": [it.get("link", "") for it in evidence if it.get("link")],
        "evidence": [
            {
                "title": it.get("title", ""),
                "link": it.get("link", ""),
                "score": it.get("score"),
                "publishedAt": it.get("publishedAt"),
                "aiSummary": it.get("aiSummary", ""),
                "importance": it.get("importance"),
            }
            for it in evidence
        ],
        "angle": "紧缩端5.2%压估值，供给端遇袭+护油+释储预期推通胀，讲透滞胀剧本与风险",
        "top_item": {
            "title": top.get("title", ""),
            "score": top.get("score"),
            "publishedAt": top.get("publishedAt"),
        },
    }
    return topic
