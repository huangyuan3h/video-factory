"""Channel presenter (pen name) helpers: greeting enforcement + cover label.

The channel presenter is the pen name 「躺平的老黄」 (never a real name).  When a
presenter is active (see :func:`src.presets.resolve_presenter`) the first
narration sentence of segment 0 must be exactly ``大家好，我是{name}。`` followed
immediately by the episode intro.  The LLM is asked for it in the prompts and,
because models drift, :func:`ensure_presenter_greeting` enforces it
deterministically (idempotent) after generation, after the number check and
again after the script review.

:func:`label_image` writes a labelled copy of a chart/title-card image with the
name in the bottom-right corner and never touches the source file.
"""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

#: Bottom-right label colours.
_DARK_TEXT = (0x3A, 0x3A, 0x3A)
_ACCENT = (0xC0, 0x39, 0x2B)
_LIGHT_TEXT = (255, 255, 255)
_PILL_ALPHA = 0.45

#: Leading spoken greeting variants, removed before the exact greeting is
#: prepended.  Each pattern is anchored at the very first clause so a greeting
#: later in the text is never touched.
_GREETING_VARIANTS = (
    re.compile(r"^大家好[，,]?我是[^。！？!?，,]{1,30}[，,。！？!?]?"),
    re.compile(r"^哈喽[，,]?\s*大家好[，,！!。]?"),
    re.compile(r"^大家好[，,！!。]?"),
    re.compile(r"^各位好[，,！!。]?"),
    re.compile(r"^欢迎来到[^。！？!?]*[。！？!?]"),
)


def greeting_for(name: str) -> str:
    """The exact opening sentence for ``name``."""
    return f"大家好，我是{name}。"


def presenter_instruction(name: str) -> str:
    """Prompt instruction asking for the exact presenter greeting (zh)."""
    greeting = greeting_for(name)
    return (
        f"开场第一段的第一句必须原样是“{greeting}”，"
        "紧接着用一句话介绍这一集讲什么（例如“这一集我们来聊聊……”）。"
        "除此之外不要出现主持人/主播自我介绍、头衔或其他称呼。"
    )


def _strip_leading_greeting(text: str) -> str:
    """Drop a leading greeting variant, returning the remaining narration."""
    for pattern in _GREETING_VARIANTS:
        match = pattern.match(text)
        if match:
            return text[match.end():].lstrip()
    return text


def has_presenter_greeting(script, name: str) -> bool:
    """True when segment 0 starts with the exact greeting for ``name``."""
    segments = getattr(script, "segments", None) or []
    if not segments or not name:
        return False
    return bool((getattr(segments[0], "text", "") or "").startswith(greeting_for(name)))


def ensure_presenter_greeting(script, name: str):
    """Guarantee segment 0 opens with the exact greeting (idempotent).

    Mutates and returns ``script``.  A no-op for an empty name or an empty
    segment list.
    """
    if not name:
        return script
    segments = getattr(script, "segments", None) or []
    if not segments:
        return script
    greeting = greeting_for(name)
    first = segments[0]
    text = getattr(first, "text", "") or ""
    if text.startswith(greeting):
        return script
    first.text = greeting + _strip_leading_greeting(text)
    return script


def _font_candidates() -> list[str]:
    """Existing CJK font lookups, in priority order (compose then cover)."""
    candidates: list[str] = []
    try:
        from .compose_service import _find_font_path

        found = _find_font_path()
        if found:
            candidates.append(found)
    except Exception:  # noqa: BLE001 - optional dependency (MoviePy)
        pass
    try:
        from .cover_service import FONT_PATHS

        candidates.extend(FONT_PATHS)
    except Exception:  # noqa: BLE001 - optional dependency (httpx)
        pass
    return candidates


def _load_presenter_font(size: int):
    for path in _font_candidates():
        try:
            return ImageFont.truetype(path, size)
        except Exception:  # noqa: BLE001 - try the next candidate
            continue
    return ImageFont.load_default()


def _mean_luminance(img: Image.Image, box: tuple[int, int, int, int]) -> float:
    left, top, right, bottom = (int(v) for v in box)
    left, top = max(0, left), max(0, top)
    right, bottom = min(img.width, right), min(img.height, bottom)
    if right <= left or bottom <= top:
        return 255.0
    region = img.crop((left, top, right, bottom)).convert("L")
    # Downscale to a single pixel: fast, order-preserving mean.
    return float(region.resize((1, 1), Image.Resampling.BOX).getpixel((0, 0)))


def _has_bottom_right_branding(img: Image.Image, name: str) -> bool:
    """Check if the image already has presenter branding in the bottom-right.

    Returns True when the bottom-right corner contains visual signatures
    consistent with an existing label (accent bar + text or dark pill + text),
    avoiding double-labeling on pre-branded title cards.
    """
    if not name or not name.strip():
        return False

    width, height = img.size
    if width < 100 or height < 100:
        return False

    font_size = max(1, int(round(height * 0.028)))
    margin_x = max(1, int(round(width * 0.035)))
    margin_y = max(1, int(round(height * 0.035)))

    corner_w = max(50, int(round(width * 0.25)))
    corner_h = max(30, int(round(height * 0.15)))
    left = max(0, width - corner_w)
    top = max(0, height - corner_h)
    corner = img.crop((left, top, width, height))

    hsv = corner.convert("HSV")
    h_data, s_data, v_data = hsv.split()
    v_pixels = list(v_data.getdata())
    s_pixels = list(s_data.getdata())
    h_pixels = list(h_data.getdata())

    high_sat_count = sum(1 for s in s_pixels if s > 100)
    total = len(s_pixels)
    if high_sat_count > total * 0.015:
        return True

    v_mean = sum(v_pixels) / total if total > 0 else 0
    threshold = 70 if v_mean >= 128 else 40
    low_v_count = sum(1 for v in v_pixels if v < threshold)
    if low_v_count > total * 0.10:
        return True

    edge_col = max(0, width - margin_x - font_size)
    if edge_col < width - 10:
        edge_region = img.crop((edge_col, max(0, height - corner_h), width, height))
        edge_gray = edge_region.convert("L")
        edge_pixels = list(edge_gray.getdata())
        edge_dark = sum(1 for p in edge_pixels if p < 100)
        if edge_dark > len(edge_pixels) * 0.20:
            return True

    return False


def label_image(src: Path, dst: Path, name: str) -> Path:
    """Write a labelled copy of ``src`` to ``dst`` (source never modified).

    The name is drawn in the bottom-right corner: dark grey text with a thin
    accent bar on a light background, or white text on a rounded
    semi-transparent black pill on a dark background.  Only the corner area is
    touched, so the centre content of a title card stays visible.

    When the source already has branding in the bottom-right corner (e.g. a
    pre-branded Soft Slate title card), the image is copied verbatim without
    adding a second label.
    """
    src = Path(src)
    dst = Path(dst)
    with Image.open(src) as opened:
        img = opened.convert("RGB")

    if _has_bottom_right_branding(img, name):
        dst.parent.mkdir(parents=True, exist_ok=True)
        img.save(dst, "PNG")
        return dst

    width, height = img.size
    font_size = max(1, int(round(height * 0.028)))
    font = _load_presenter_font(font_size)
    draw = ImageDraw.Draw(img)
    text = str(name)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = max(1, bbox[2] - bbox[0])
    text_h = max(1, bbox[3] - bbox[1])
    margin_x = max(1, int(round(width * 0.035)))
    margin_y = max(1, int(round(height * 0.035)))
    x = max(0, width - margin_x - text_w)
    y = max(0, height - margin_y - text_h)

    left = max(0, x - text_h)
    luminance = _mean_luminance(img, (left, max(0, y - text_h), width, height))

    if luminance >= 128:
        bar_w = max(2, int(round(height * 0.004)))
        gap = max(2, int(round(font_size * 0.5)))
        bar_x = max(0, x - bar_w - gap)
        draw.rectangle([bar_x, y, bar_x + bar_w, y + text_h], fill=_ACCENT)
        draw.text((x, y - bbox[1]), text, font=font, fill=_DARK_TEXT)
    else:
        pad = max(2, int(round(font_size * 0.35)))
        pill_x0 = max(0, x - text_h - pad)
        pill = [
            pill_x0,
            max(0, y - pad),
            width - 1,
            min(height - 1, y + text_h + pad),
        ]
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(overlay).rounded_rectangle(
            pill,
            radius=max(1, int(round(text_h * 0.5))),
            fill=(0, 0, 0, int(round(_PILL_ALPHA * 255))),
        )
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        ImageDraw.Draw(img).text((x, y - bbox[1]), text, font=font, fill=_LIGHT_TEXT)

    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "PNG")
    return dst
