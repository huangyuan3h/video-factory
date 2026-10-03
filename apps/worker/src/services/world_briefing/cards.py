"""自绘卡：市场数据图表、时间线、要点卡（1440p，VF 图表能力，合法第一优先级）。"""

from __future__ import annotations

from pathlib import Path

W, H = 2560, 1440

_FONT_CANDIDATES = (
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
)


def _font(size: int):
    from PIL import ImageFont

    for p in _FONT_CANDIDATES:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _base(title: str, subtitle: str = ""):
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (W, H), "#ffffff")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W - 1, H - 1], outline="#dfe3e8", width=6)
    d.rectangle([0, 0, W, 240], fill="#f4f6f8")
    d.text((100, 55), title, font=_font(72), fill="#1f2329")
    if subtitle:
        d.text((100, 150), subtitle, font=_font(44), fill="#5b636d")
    return img, d


def render_item_card(item: dict, date: str, out_path: str | Path) -> Path:
    """每条新闻的要点卡（标题+事实+来源名），与该条强相关，禁止泛财经兜底。"""
    from textwrap import wrap

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img, d = _base(f"{item.get('section','')}｜{date}", item.get("title", "")[:36])
    y = 300
    # 事实分行（按。切分，每行 ≤28 字）
    facts = str(item.get("facts", "")).replace("\n", "")
    chunks: list[str] = []
    for sent in facts.split("。"):
        sent = sent.strip()
        if not sent:
            continue
        sent += "。"
        while len(sent) > 28:
            chunks.append(sent[:28])
            sent = sent[28:]
        chunks.append(sent)
    for line in chunks[:12]:
        d.text((100, y), line, font=_font(46), fill="#111418")
        y += 72
    y += 20
    srcs = " · ".join(s.get("name", "") for s in item.get("sources", []))
    d.text((100, y), f"来源：{srcs}"[:60], font=_font(38), fill="#5b636d")
    y += 60
    if item.get("for_you") or item.get("means"):
        tip = item.get("means") or item.get("for_you") or ""
        for line in wrap("要点：" + tip, 30)[:2]:
            d.text((100, y), line, font=_font(42), fill="#0b5fff")
            y += 62
    d.text((100, H - 90), "自制要点卡｜躺平的老黄｜不构成投资建议", font=_font(36), fill="#8a94a0")
    img.save(out)
    return out


def render_market_chart(item: dict, date: str, out_path: str | Path) -> Path:
    """市场快照条形图：恒生/道指/标普/纳指涨跌幅 + 油价/汇率/非农文字（全部约数）。"""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img, d = _base(f"市场快照｜{date}", "恒生 23972.29 跌约 2.60%｜纳指约 +1.66%创纪录｜布伦特约 $99.88")
    m = (item.get("market_chart") or {}) if isinstance(item, dict) else {}
    # 条形图区
    bx, by, bw, bh = 140, 420, 2280, 560
    d.rectangle([bx, by, bx + bw, by + bh], outline="#dfe3e8", width=3)
    bars = [
        ("恒生", float((m.get("hang_seng") or {}).get("chg", -2.60))),
        ("道指", float((m.get("dow") or {}).get("chg", 0.60))),
        ("标普", float((m.get("spx") or {}).get("chg", 1.02))),
        ("纳指", float((m.get("nasdaq") or {}).get("chg", 1.66))),
    ]
    # 零线
    zero_y = by + int(bh * 0.55)
    d.line([(bx, zero_y), (bx + bw, zero_y)], fill="#111418", width=4)
    slot = bw // len(bars)
    for i, (name, chg) in enumerate(bars):
        cx = bx + slot * i + slot // 2
        h = int(min(1.0, abs(chg) / 3.0) * (bh * 0.42))
        color = "#d63031" if chg < 0 else "#09814a"
        # A 股红涨绿跌习惯：这里按国际惯例红跌绿涨？统一用红=跌、绿=涨并标注数字，避免误读。
        if chg >= 0:
            d.rectangle([cx - 90, zero_y - h, cx + 90, zero_y], fill=color)
            d.text((cx - 90, zero_y - h - 60), f"约 {chg:+.2f}%", font=_font(44), fill="#111418")
        else:
            d.rectangle([cx - 90, zero_y, cx + 90, zero_y + h], fill=color)
            d.text((cx - 90, zero_y + h + 12), f"约 {chg:.2f}%", font=_font(44), fill="#111418")
        d.text((cx - 60, by + bh + 16), name, font=_font(48), fill="#1f2329")
    y = by + bh + 100
    for line in [
        "恒生收约 23972.29（约半年来最重单日跌幅）｜南向通休市至约 10 月 8 日｜A 股休市至约 10 月 7 日",
        "美国 9 月非农仅增约 2.9 万（预期约 9 万）｜布伦特约 $99.88｜WTI 约 $89.29｜美元兑人民币约 6.70",
        "耐克因中国需求预警大跌约 5.6%",
    ]:
        d.text((140, y), line, font=_font(40), fill="#24292f")
        y += 62
    d.text((140, H - 90), "数据为约数，截至 10 月 2 日｜自制图表｜躺平的老黄", font=_font(36), fill="#8a94a0")
    img.save(out)
    return out


def render_section_card(kind: str, date: str, text: str, out_path: str | Path) -> Path:
    """片头目录卡 / 片尾选题卡。"""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img, d = _base(f"每日世界简报｜{date}", kind)
    y = 320
    for line in str(text).split("\n")[:14]:
        d.text((100, y), line[:34], font=_font(48), fill="#111418")
        y += 74
    d.text((100, H - 90), "自制卡｜躺平的老黄｜不构成投资建议", font=_font(36), fill="#8a94a0")
    img.save(out)
    return out
