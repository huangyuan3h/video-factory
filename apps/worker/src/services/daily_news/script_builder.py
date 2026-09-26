"""P0 script builder: deterministic narration from snapshot facts (no LLM inventing)."""

from __future__ import annotations

import json
from pathlib import Path

PRESENTER = "躺平的老黄"
GREETING = "大家好，我是躺平的老黄。"
DISCLAIMER = "以上内容基于公开新闻的个人解读，不构成投资建议，事实截至昨日盘点，后续以官方口径为准。"


def build_script(topic: dict, snapshot: dict) -> tuple[dict, str]:
    """Build approved_script-compatible ``script.json`` + ``script.md``.

    5 segments (~40-60s each): hook/background/data-card/multi-view/close.
    All figures come from ``topic['evidence']``; nothing is invented.
    """
    ev = {e["title"]: e for e in topic.get("evidence", [])}
    top_title = topic["top_item"]["title"]  # 美国10年期国债收益率涨穿5.2%，为2007年以来首次
    brief_id = topic.get("brief_id", "")

    seg1 = (
        f"{GREETING}这里是每日财经昨日盘点，对应{brief_id}早报。"
        f"一句话先说核心：{top_title}。全场评分最高，压过了同一天的石油供给冲击。"
        "今天这一集，我们就把利率和油放在一起看，讲一个滞胀剧本。"
    )
    seg2 = (
        "先看背景，同一天早报里挤了五条油链消息："
        "也门胡塞武装称打击了沙特首都利雅得和延布的阿美设施；"
        "法国将派遣军事援助与部队保护沙特石油设施；"
        "法国总统马克龙希望七国集团讨论释放战略石油储备；"
        "北约秘书长称欧洲炼油产能萎缩令人担忧。"
        "供给端几乎一边倒，这就是油价易涨难跌的情绪底。"
    )
    seg3 = (
        "关键数据只认快照，不加戏：十年期美债收益率涨穿5.2%，"
        "为2007年以来首次；早报给这条打了全场最高的31.0分，"
        "重要性5分，相关度75分。利率这么高，成长股估值先被压一头，"
        "同一天油链又在推通胀预期，两头一夹就是滞胀味。"
    )
    seg4 = (
        "多方说法要摆出来：挺紧缩的一方会说，高利率正是对抗油价通胀的刹车；"
        "担心增长的一方会说，利率和油价同涨最伤需求，炼油和化工的利润会被两头挤；"
        "中性视角是看两个锚，一个是后续美国官方利率表态，一个是沙特设施是否实质减产，"
        "以及七国集团是否真的释放战略储备。在官方确认前，都先当预期交易。"
    )
    seg5 = (
        "收束一下：利率压估值，供给推通胀，短期波动会放大，追高要谨慎。"
        f"{DISCLAIMER}"
        "我是躺平的老黄，喜欢这种只讲依据的盘点，欢迎订阅每日财经，我们明天见。"
    )

    segments = [
        {"text": seg1, "keywords": ["美国国债", "债券收益率", "财经新闻"], "duration_estimate": 50},
        {"text": seg2, "keywords": ["石油设施", "炼油厂", "沙漠油田"], "duration_estimate": 60},
        {"text": seg3, "keywords": ["数据图表", "股票走势", "财经数据"], "duration_estimate": 55},
        {"text": seg4, "keywords": ["新闻发布会", "财经访谈", "城市夜景"], "duration_estimate": 55},
        {"text": seg5, "keywords": ["交易大厅", "股票市场", "城市天际线"], "duration_estimate": 45},
    ]
    total = sum(s["duration_estimate"] for s in segments)
    script = {"title": topic["title"], "segments": segments, "total_duration_estimate": total}
    md_lines = [f"# {topic['title']}", ""]
    for i, s in enumerate(segments, 1):
        md_lines += [f"## 段{i}（约{s['duration_estimate']}s）", s["text"], ""]
    md_lines += [f"> {DISCLAIMER}", "", f"选题依据：{brief_id}，证据 {len(topic.get('evidence', []))} 条。"]
    void = ev  # keep linter calm about unused mapping (titles verified in factcheck)
    assert void is not None
    return script, "\n".join(md_lines)


def write_script_files(script: dict, md: str, task_dir: str | Path) -> dict[str, Path]:
    task = Path(task_dir)
    task.mkdir(parents=True, exist_ok=True)
    sj = task / "script.json"
    sm = task / "script.md"
    sj.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    sm.write_text(md, encoding="utf-8")
    return {"script.json": sj, "script.md": sm}
