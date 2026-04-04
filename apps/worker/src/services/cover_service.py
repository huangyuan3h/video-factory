"""Cover image generation service."""

import asyncio
import logging
import random
import tempfile
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

from ..core.task_logger import TaskLogger
from .material.material_fetcher import KEYWORD_TRANSLATIONS

logger = logging.getLogger(__name__)

FONT_PATHS = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]


async def _fetch_background(
    keywords: list[str],
    pexels_api_key: str | None,
    task_logger: TaskLogger,
) -> Path | None:
    """Fetch background image from Pexels."""
    if not pexels_api_key:
        return None
    
    search_term = keywords[0] if keywords else "abstract"
    
    if search_term in KEYWORD_TRANSLATIONS:
        search_term = KEYWORD_TRANSLATIONS[search_term]
    
    task_logger.info(f"搜索封面背景: {search_term}")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                "https://api.pexels.com/v1/search",
                params={
                    "query": search_term,
                    "per_page": 5,
                    "orientation": "portrait",
                },
                headers={"Authorization": pexels_api_key},
            )
            response.raise_for_status()
            data = response.json()
            
            photos = data.get("photos", [])
            if photos:
                photo = random.choice(photos[:3])
                image_url = photo.get("src", {}).get("large")
                
                if image_url:
                    task_logger.info(f"下载背景图片: {photo.get('id')}")
                    img_response = await client.get(image_url)
                    img_response.raise_for_status()
                    
                    temp_path = Path(tempfile.mkdtemp()) / "bg.jpg"
                    with open(temp_path, "wb") as f:
                        f.write(img_response.content)
                    return temp_path
    except Exception as e:
        task_logger.warning(f"获取背景图片失败: {e}")
    
    return None


def _create_gradient_background(width: int, height: int) -> Image.Image:
    """Create a gradient background image."""
    img = Image.new("RGB", (width, height), (30, 30, 50))
    
    for y in range(height):
        r = int(30 + (y / height) * 20)
        g = int(30 + (y / height) * 30)
        b = int(50 + (y / height) * 50)
        for x in range(width):
            img.putpixel((x, y), (r, g, b))
    
    return img


def _load_font(font_size: int, task_logger: TaskLogger) -> ImageFont.FreeTypeFont | None:
    """Try to load a Chinese font."""
    for font_path in FONT_PATHS:
        try:
            font = ImageFont.truetype(font_path, font_size)
            task_logger.info(f"使用字体: {font_path}")
            return font
        except Exception:
            continue
    
    task_logger.warning("使用默认字体")
    return None


def _wrap_text(
    title: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    draw: ImageDraw.ImageDraw,
) -> list[str]:
    """Wrap text to fit within max_width."""
    lines = []
    current_line = ""
    
    for char in title:
        test_line = current_line + char
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = char
    
    if current_line:
        lines.append(current_line)
    
    return lines


def _draw_cover_image(
    bg_path: Path | None,
    title: str,
    resolution: tuple[int, int],
    task_logger: TaskLogger,
    task_dir: Path,
) -> Path:
    """Draw the cover image synchronously."""
    width, height = resolution
    font_size = int(height * 0.06)
    
    if bg_path and bg_path.exists():
        task_logger.info("使用下载的背景图片")
        img = Image.open(bg_path)
        img = img.resize((width, height), Image.Resampling.LANCZOS)
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 150))
        img = img.convert("RGBA")
        img = Image.alpha_composite(img, overlay)
        img = img.convert("RGB")
    else:
        task_logger.info("创建渐变背景")
        img = _create_gradient_background(width, height)
    
    draw = ImageDraw.Draw(img)
    font = _load_font(font_size, task_logger)
    
    if not font:
        font = ImageFont.load_default()
    
    max_width = width - 100
    lines = _wrap_text(title, font, max_width, draw)
    
    line_height = font_size * 1.5
    total_text_height = len(lines) * line_height
    y_offset = (height - total_text_height) // 2
    
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        text_width = bbox[2] - bbox[0]
        x = (width - text_width) // 2
        
        draw.text((x + 4, y_offset + 4), line, font=font, fill=(0, 0, 0))
        draw.text((x, y_offset), line, font=font, fill=(255, 255, 255))
        y_offset += line_height
    
    draw.rectangle([60, height - 100, width - 60, height - 85], fill=(255, 255, 255, 200))
    
    output_path = task_dir / "cover.png"
    img.save(output_path, "PNG", quality=95)
    task_logger.info(f"封面图已生成: {output_path}")
    
    return output_path


async def generate_cover_image(
    task_dir: Path,
    task_logger: TaskLogger,
    title: str,
    keywords: list[str],
    pexels_api_key: str | None,
    resolution: tuple[int, int],
) -> Path:
    """Generate cover image with title and background from Pexels."""
    bg_path = await _fetch_background(keywords, pexels_api_key, task_logger)
    
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _draw_cover_image,
        bg_path,
        title,
        resolution,
        task_logger,
        task_dir,
    )