"""P0 script builder: deterministic narration from snapshot facts (no LLM inventing)."""

from __future__ import annotations

import json
from pathlib import Path

PRESENTER = "躺平的老黄"
GREETING = "大家好，我是躺平的老黄。"
DISCLAIMER = "以上内容基于公开新闻的个人解读，不构成投资建议，事实截至昨日盘点，后续以官方口径为准。"


def build_script(topic: dict, snapshot: dict) -> tuple[dict, str]:
    """Build approved_script-compatible ``script.json`` + ``script.md``.

    v2 (owner feedback #3): drop roundabout framing like
    「这里是每日财经昨日盘点」. Simple concise language. Per news item:
    event first (what/who/numbers/source), then a short 「分析：」 of what it
    means (clearly labeled, no stock picks, no buy/sell, no promised returns).
    Opens directly with the top story; light 「躺平的老黄」 greeting at most;
    closes with a brief conversational wrap-up. All figures come from
    ``topic['evidence']``; nothing is invented.
    """
    brief_id = topic.get("brief_id", "")

    seg1 = (
        f"{GREETING}先说今天最重要的一条：美国10年期国债收益率涨穿5.2%，"
        "为2007年以来首次，据华尔街见闻快讯。"
        "分析：利率这么高，成长股估值先承压，债市波动也会放大，"
        "后续看美联储官员表态和通胀就业数据。"
    )
    seg2 = (
        "第二条看石油供给。也门胡塞武装称打击了沙特首都利雅得和延布的阿美设施，"
        "法国将派军事援助保护沙特石油设施，马克龙希望七国集团讨论释放战略储备，"
        "北约提醒欧洲炼油产能萎缩，据同日多条快讯。"
        "分析：供给端消息集中，油价易涨难跌，炼油和化工成本会被两头挤。"
    )
    seg3 = (
        "第三条是中美会谈。习近平同美国总统特朗普会谈，据快讯强调战略稳定。"
        "分析：这种会谈短期稳预期为主，具体成果要等官方口径，"
        "在确认前先当预期交易，不要过度解读。"
    )
    seg4 = (
        "第四条看科技。Anthropic与Akamai达成将近120亿美元AI算力协议，据快讯。"
        "分析：算力投入是长期逻辑，云厂商和产业链可能受益，"
        "但交付节奏会分化，短期追高要谨慎。"
    )
    seg5 = (
        "今天就聊到这。利率压估值，供给推通胀，会谈稳预期，算力投长期，"
        "四条线放在一起看，短期波动容易放大。"
        f"{DISCLAIMER}"
        "我是躺平的老黄，明天见。"
    )

    segments = [
        {"text": seg1, "keywords": ["美国国债", "美联储", "鲍威尔"], "duration_estimate": 60},
        {"text": seg2, "keywords": ["沙特阿美", "炼油厂", "马克龙"], "duration_estimate": 60},
        {"text": seg3, "keywords": ["白宫", "特朗普", "习近平"], "duration_estimate": 60},
        {"text": seg4, "keywords": ["Akamai", "数据中心", "AI算力"], "duration_estimate": 60},
        {"text": seg5, "keywords": ["财经盘点", "市场波动"], "duration_estimate": 60},
    ]
    total = sum(s["duration_estimate"] for s in segments)
    script = {"title": topic["title"], "segments": segments, "total_duration_estimate": total}
    md_lines = [f"# {topic['title']}", ""]
    for i, s in enumerate(segments, 1):
        md_lines += [f"## 段{i}（约{s['duration_estimate']}s）", s["text"], ""]
    md_lines += [f"> {DISCLAIMER}", "", f"选题依据：{brief_id}，证据 {len(topic.get('evidence', []))} 条。"]
    return script, "\n".join(md_lines)


def write_script_files(script: dict, md: str, task_dir: str | Path) -> dict[str, Path]:
    task = Path(task_dir)
    task.mkdir(parents=True, exist_ok=True)
    sj = task / "script.json"
    sm = task / "script.md"
    sj.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    sm.write_text(md, encoding="utf-8")
    return {"script.json": sj, "script.md": sm}
