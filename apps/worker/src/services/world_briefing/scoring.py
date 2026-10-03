"""去重聚类 + 重要性×新颖性×相关度打分排序（保留理由）。"""

from __future__ import annotations

import re


def _norm(title: str) -> str:
    t = re.sub(r"\s+", "", str(title or ""))
    t = re.sub(r"[「」『』\"'“”·，,。！!？?：:；;（）()—\-]", "", t)
    return t.lower()


def dedupe_cluster(items: list[dict]) -> list[dict]:
    """同一事件多源合并：标题归一化相同或高度重叠的合并为一条（保留多源）。"""
    seen: dict[str, dict] = {}
    out: list[dict] = []
    for it in items:
        key = _norm(it.get("title", ""))[:24]
        # 同一 section 内 key 相同才合并（跨板块不合并）
        ckey = f"{it.get('section')}|{key}"
        if ckey in seen:
            prev = seen[ckey]
            for s in it.get("sources", []):
                if s.get("url") not in {x.get("url") for x in prev.get("sources", [])}:
                    prev.setdefault("sources", []).append(s)
            # 合并数字
            for n in it.get("numbers", []):
                if n not in prev.setdefault("numbers", []):
                    prev["numbers"].append(n)
            prev.setdefault("merged", []).append(it.get("id"))
        else:
            cp = dict(it)
            cp["sources"] = list(it.get("sources", []))
            seen[ckey] = cp
            out.append(cp)
    return out


def score_item(it: dict, weights: dict | None = None) -> tuple[float, str]:
    """加权打分（权重见 config/news_sources.yaml），保留理由。"""
    w = weights or {"importance": 0.5, "novelty": 0.25, "relevance": 0.25}
    imp = float(it.get("importance", 5))
    nov = float(it.get("novelty", 5))
    rel = float(it.get("relevance", 5))
    score = imp * w["importance"] + nov * w["novelty"] + rel * w["relevance"]
    reason = (
        f"重要性{imp:.1f}×{w['importance']}＋新颖性{nov:.1f}×{w['novelty']}"
        f"＋相关度{rel:.1f}×{w['relevance']}＝{score:.2f}"
        f"｜{it.get('section')}｜{it.get('title','')[:24]}…"
    )
    return round(score, 2), reason


def rank_items(items: list[dict], weights: dict | None = None, top_n: int = 10) -> tuple[list[dict], list[dict]]:
    """去重→打分→排序，返回 (ranked, rank_log)。"""
    uniq = dedupe_cluster(items)
    scored: list[dict] = []
    log: list[dict] = []
    for it in uniq:
        s, reason = score_item(it, weights)
        cp = dict(it)
        cp["score"] = s
        cp["score_reason"] = reason
        scored.append(cp)
        log.append({"id": it.get("id"), "title": it.get("title"), "score": s, "reason": reason})
    # 板块顺序优先（AI→科技→经济与市场→地缘与冲突），板块内按分排序
    order = {"AI": 0, "科技": 1, "经济与市场": 2, "地缘与冲突": 3}
    scored.sort(key=lambda x: (order.get(x.get("section"), 9), -x["score"]))
    log.sort(key=lambda x: -x["score"])
    return scored[:top_n], log
