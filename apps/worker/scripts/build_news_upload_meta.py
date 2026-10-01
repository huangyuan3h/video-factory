#!/usr/bin/env python
"""Build YouTube upload meta (title/description/tags) with full attribution.

Usage:
    cd apps/worker
    .venv/bin/python scripts/build_news_upload_meta.py \
        --task-dir ../../data/output/daily_news/mvp-2026-09-25
Writes upload_meta.json next to the task dir.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-dir", required=True, type=Path)
    args = ap.parse_args(argv)
    task = args.task_dir
    topic = json.loads((task / "topic.json").read_text(encoding="utf-8"))
    attr = json.loads((task / "material_attribution.json").read_text(encoding="utf-8"))

    title = f"{topic['title']}｜每日财经"
    lines = [
        "大家好，我是躺平的老黄。这里是每日财经昨日盘点，对应Karios 2026-09-25早报。",
        "",
        "本集只讲快照里的事实：美国10年期国债收益率涨穿5.2%，为2007年以来首次（早报全场最高31.0分）；",
        "同一天油链消息密集：胡塞武装称打击沙特利雅得和延布的阿美设施、法国派兵保护沙特石油设施、",
        "马克龙希望G7讨论释放战略石油储备、北约警告欧洲炼油产能萎缩。利率压估值、供给推通胀，讲透滞胀剧本与风险。",
        "",
        "【素材与授权】",
    ]
    for m in sorted(attr["materials"], key=lambda x: int(x.get("segment", 0))):
        if m.get("license_name") == "pexels":
            lines.append(
                f"· 第{int(m['segment']) + 1}段视频：Pexels（{m.get('author','')}），{m.get('source_url','')}，Pexels License（可商用改编）"
            )
        else:
            lines.append(
                f"· 第{int(m['segment']) + 1}段数据卡：本频道自制（Karios早报快照数据），CC-BY（本频道）"
            )
    lines += [
        "选题/数据来自Karios日报快照，解读为本频道原创。",
        "",
        "以上内容基于公开新闻的个人解读，不构成投资建议。事实截至昨日盘点，后续以官方口径为准。",
        "证据原文：" + " / ".join(topic.get("evidence_links", [])),
    ]
    meta = {
        "title": title[:100],
        "description": "\n".join(lines),
        "tags": ["每日财经", "美债收益率", "石油", "滞胀", "早报", "躺平的老黄"],
        "category_id": "25",
        "privacy": "unlisted",
        "default_language": "zh-CN",
    }
    out = task / "upload_meta.json"
    out.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
