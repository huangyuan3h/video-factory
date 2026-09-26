"""P0 Karios data card: 1920x950 white PNG for the fullframe layout."""

from __future__ import annotations

from pathlib import Path

W, H = 1920, 950


def render_data_card(topic: dict, snapshot: dict, out_path: str | Path) -> Path:
    from PIL import Image, ImageDraw

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (W, H), "#ffffff")
    d = ImageDraw.Draw(img)
    # Border + header bar (light, keeps fullframe white look)
    d.rectangle([0, 0, W - 1, H - 1], outline="#dfe3e8", width=4)
    d.rectangle([0, 0, W, 150], fill="#f4f6f8")
    d.text((70, 45), "每日财经 · 昨日盘点", fill="#1f2329")
    d.text((70, 85), str(topic.get("brief_id", "")), fill="#5b636d")
    y = 210
    d.text((70, y), str(topic.get("title", ""))[:40], fill="#111418")
    y += 60
    for e in topic.get("evidence", [])[:5]:
        line = f"· {e.get('title','')[:36]}  评分{e.get('score')}  {str(e.get('publishedAt',''))[:10]}"
        d.text((70, y), line, fill="#24292f")
        y += 52
    y += 10
    d.text((70, y), "核心矛盾：利率压估值（10Y破5.2%） vs 供给推通胀（阿美遇袭/护油/释储）。", fill="#111418")
    y += 52
    d.text((70, y), "口径：Karios早报快照；解读为本频道原创。不构成投资建议。", fill="#5b636d")
    img.save(out)
    return out
