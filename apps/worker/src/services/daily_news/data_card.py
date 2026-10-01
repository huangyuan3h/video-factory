"""P0 Karios data card: 1920x950 white PNG for the fullframe layout."""

from __future__ import annotations

from pathlib import Path

W, H = 1920, 950

_FONT_CANDIDATES = (
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
)


def _font(size: int):
    from PIL import ImageFont

    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def render_data_card(topic: dict, snapshot: dict, out_path: str | Path) -> Path:
    from PIL import Image, ImageDraw

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (W, H), "#ffffff")
    d = ImageDraw.Draw(img)
    f_title = _font(56)
    f_sub = _font(36)
    f_body = _font(40)
    f_small = _font(34)
    # Border + header bar (light, keeps fullframe white look)
    d.rectangle([0, 0, W - 1, H - 1], outline="#dfe3e8", width=4)
    d.rectangle([0, 0, W, 170], fill="#f4f6f8")
    d.text((70, 40), "每日财经 · 昨日盘点", font=f_title, fill="#1f2329")
    d.text((70, 115), str(topic.get("brief_id", "")), font=f_sub, fill="#5b636d")
    y = 220
    d.text((70, y), str(topic.get("title", ""))[:32], font=f_body, fill="#111418")
    y += 70
    for e in topic.get("evidence", [])[:5]:
        line = f"· {e.get('title','')[:30]} 评分{e.get('score')} {str(e.get('publishedAt',''))[:10]}"
        d.text((70, y), line, font=f_small, fill="#24292f")
        y += 56
    y += 16
    d.text((70, y), "核心矛盾：利率压估值（10Y破5.2%）vs 供给推通胀。", font=f_body, fill="#111418")
    y += 66
    d.text((70, y), "口径：Karios早报快照；解读为本频道原创。不构成投资建议。", font=f_small, fill="#5b636d")
    img.save(out)
    return out
