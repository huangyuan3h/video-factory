"""文稿构建：私人版（含「对你」）+ 公开版（「这意味着什么」）同一次产出。

对齐 STYLE.md：板块顺序 AI→科技→经济与市场→地缘与冲突；粗体一句话标题；
3–6 句事实；市场快照带约数；结尾 2 选题；来源双源 Markdown 链接；禁编造。
"""

from __future__ import annotations


def _sources_md(item: dict) -> str:
    parts = [f"[{s['name']}]({s['url']})" for s in item.get("sources", [])]
    return " · ".join(parts)


def build_private_md(date: str, ranked: list[dict], video_topics: list[str]) -> str:
    lines = ["# 小柚每日世界简报 " + date + "（私人版）", ""]
    lines.append("早安。今天的世界简报（约过去 24 小时，上海时区）：")
    lines.append("")
    section_no = {"AI": "一、AI", "科技": "二、科技", "经济与市场": "三、经济与市场", "地缘与冲突": "四、地缘与冲突"}
    last_section = None
    for idx, it in enumerate(ranked, 1):
        sec = it.get("section", "")
        if sec != last_section:
            lines.append(f"**{section_no.get(sec, sec)}**")
            lines.append("")
            last_section = sec
        lines.append(f"{idx}. **{it['title']}**")
        lines.append(it["facts"])
        if it.get("for_you"):
            lines.append(f"对你：{it['for_you']}")
        lines.append(f"来源：{_sources_md(it)}")
        lines.append("")
    lines.append("——")
    lines.append(f"可做成视频的选题：① {video_topics[0]}；② {video_topics[1]}。")
    lines.append("")
    lines.append("（注：公开视频版需把「对你」改为面向观众的「这意味着什么」，不得出现主人私人项目细节或真名。）")
    return "\n".join(lines)


def build_public_md(date: str, ranked: list[dict], video_topics: list[str]) -> str:
    lines = ["# 每日世界简报 " + date + "（公开视频版文稿）", ""]
    lines.append("早安。今天的世界简报（约过去 24 小时，上海时区）：")
    lines.append("")
    section_no = {"AI": "一、AI", "科技": "二、科技", "经济与市场": "三、经济与市场", "地缘与冲突": "四、地缘与冲突"}
    last_section = None
    for idx, it in enumerate(ranked, 1):
        sec = it.get("section", "")
        if sec != last_section:
            lines.append(f"**{section_no.get(sec, sec)}**")
            lines.append("")
            last_section = sec
        lines.append(f"{idx}. **{it['title']}**")
        lines.append(it["facts"])
        lines.append(f"这意味着什么：{it.get('means', '')}")
        lines.append(f"来源：{_sources_md(it)}")
        lines.append("")
    lines.append("——")
    lines.append(f"可做成视频的选题：① {video_topics[0]}；② {video_topics[1]}。")
    return "\n".join(lines)


PRESENTER = "躺平的老黄"
DISCLAIMER = "以上内容基于公开新闻的个人解读，不构成投资建议，事实截至昨日盘点，后续以官方口径为准。"


def build_narration_segments(date: str, ranked: list[dict], video_topics: list[str]) -> list[dict]:
    """公开版口播分段：片头（日期+目录）+ 每条一段 + 片尾（2 选题）。约 6–10 分钟。"""
    segs: list[dict] = []
    titles = "、".join(f"{i+1}、{it['title'][:16]}…" for i, it in enumerate(ranked[:7]))
    intro = (
        f"大家好，我是{ PRESENTER}。今天是{date}，先看今天世界简报的目录：{titles}"
        f"今天共{len(ranked)}条，分 AI、科技、经济与市场、地缘与冲突四个板块，一条一条过。"
    )
    segs.append({"kind": "intro", "text": intro, "keywords": ["世界简报", "目录"], "item_id": None})
    for it in ranked:
        body = f"{it['title']}。{it['facts']}这意味着什么：{it.get('means','')}"
        segs.append({
            "kind": "item",
            "text": body,
            "keywords": [it.get("section", ""), it["title"][:8]],
            "item_id": it.get("id"),
            "section": it.get("section"),
        })
    outro = (
        f"最后说两个可做成视频的选题：第一，{video_topics[0]}；第二，{video_topics[1]}。"
        f"{DISCLAIMER}我是{ PRESENTER}，明天见。"
    )
    segs.append({"kind": "outro", "text": outro, "keywords": ["选题", "明日预告"], "item_id": None})
    return segs


def build_script_json(date: str, ranked: list[dict], video_topics: list[str]) -> dict:
    """video_service approved_script 兼容的 script.json（公开版口播，全段绑定自绘卡）。"""
    title = f"每日世界简报 {date}：{ranked[0]['title'][:20]}…等{len(ranked)}条"
    narration = build_narration_segments(date, ranked, video_topics)
    segments = []
    for s in narration:
        segments.append({
            "text": s["text"],
            "keywords": s.get("keywords", []),
            "duration_estimate": max(20, min(90, len(s["text"]) // 4)),
            "images": [],  # pipeline 后续绑定自绘卡
            "fit": "contain",
            "motion": "none",
            "section": s.get("section"),
            "key_point": (s.get("item_id") or s.get("kind") or ""),
        })
    total = sum(s["duration_estimate"] for s in segments)
    return {"title": title, "segments": segments, "total_duration_estimate": total}


def build_description(date: str, ranked: list[dict], video_topics: list[str]) -> str:
    lines = [
        f"每日世界简报 {date}｜{len(ranked)} 条｜AI→科技→经济与市场→地缘与冲突",
        "",
        "本集目录：",
    ]
    for i, it in enumerate(ranked, 1):
        lines.append(f"{i}. {it['title']}")
    lines += ["", "全部来源链接："]
    seen: set[str] = set()
    for it in ranked:
        for s in it.get("sources", []):
            if s["url"] not in seen:
                seen.add(s["url"])
                lines.append(f"- {s['name']}: {s['url']}")
    lines += [
        "",
        f"可做成视频的选题：① {video_topics[0]}；② {video_topics[1]}。",
        DISCLAIMER,
        f"我是{ PRESENTER}。",
    ]
    return "\n".join(lines)
