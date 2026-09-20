"""News pipeline helpers: fetch GNews articles and download their images.

GNews (free tier) returns article metadata + a single ``image`` URL. There is no
news *video* feed, so for v1 the article images are the background materials.
Stock fallbacks (Pexels/online) are used when images are missing, but synthetic
ComfyUI generation is never used on this path.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from ..config import settings
from ..core.task_logger import TaskLogger
from ..sources.base import ContentItem
from ..sources.news_api import NewsAPISource

logger = logging.getLogger(__name__)

NEWS_IMAGES_DIRNAME = "news_images"

_EXT_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
}

# Several CDNs (e.g. VOA's gdb.voanews.com) return 403 for bare clients; a
# browser-like UA + Referer to the article is enough to get the image.
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_BROWSER_HEADERS = {
    "User-Agent": _BROWSER_UA,
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

_MAGIC_EXT = (
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
    (b"BM", ".bmp"),
)

# Tiny in-process cache so repeated generates don't burn the free quota.
_CACHE: dict[str, tuple[float, list[ContentItem]]] = {}


def is_news_request(request) -> bool:
    """True when the request selects the news pipeline."""
    return str(getattr(request, "content_type", "") or "").strip().lower() == "news"


def _assign(request, attr: str, value) -> None:
    """Set an attribute on a possibly-frozen request object."""
    try:
        setattr(request, attr, value)
    except Exception:
        object.__setattr__(request, attr, value)


def _resolve_query(request) -> str | None:
    """Pick a search seed: explicit news_query > title > content snippet."""
    query = (getattr(request, "news_query", None) or "").strip()
    if query:
        return query
    title = (getattr(request, "title", None) or "").strip()
    if title:
        return title
    content = (getattr(request, "content", None) or "").strip()
    if content:
        return content[:200]
    return None


def _cache_get(key: str) -> list[ContentItem] | None:
    entry = _CACHE.get(key)
    if not entry:
        return None
    ts, items = entry
    if time.time() - ts > max(0, settings.news_cache_ttl_s):
        _CACHE.pop(key, None)
        return None
    return list(items)


def _cache_set(key: str, items: list[ContentItem]) -> None:
    _CACHE[key] = (time.time(), list(items))


def clear_news_cache() -> None:
    """Clear the in-process article cache (used by tests)."""
    _CACHE.clear()


async def _load_articles(request, query: str | None) -> list[ContentItem]:
    """Fetch articles for the request, using a short-lived cache."""
    provider = (getattr(request, "news_provider", None) or settings.news_provider or "gnews").strip().lower()
    # `lang` now maps to the top-level narration language, so fall back to it when
    # a news-specific language was not given (e.g. news + lang=en).
    request_lang = getattr(request, "language", None)
    if request_lang and str(request_lang).strip().lower() in ("", "zh"):
        request_lang = None
    lang = (
        getattr(request, "news_lang", None) or request_lang or settings.news_lang or ""
    ).strip() or None
    country = (getattr(request, "news_country", None) or settings.news_country or "us").strip() or "us"

    requested = getattr(request, "news_max_articles", None) or settings.news_max_articles
    try:
        count = max(1, min(10, int(requested)))
    except (TypeError, ValueError):
        count = max(1, min(10, int(settings.news_max_articles)))

    if provider == "newsapi":
        api_key = settings.news_api_key
    else:
        api_key = settings.gnews_api_key

    if not api_key:
        raise ValueError(
            f"未配置新闻 API Key（provider={provider}）。请设置 GNEWS_API_KEY 后重启 worker。"
        )

    cache_key = f"{provider}:{query or ''}:{lang or ''}:{country}:{count}"
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info(f"News cache hit for {cache_key}")
        return cached

    source = NewsAPISource(
        name="GNews" if provider == "gnews" else provider,
        api_key=api_key,
        provider=provider,
        country=country,
        lang=lang,
    )
    items = await source.fetch(count=count, query=query)
    if items:
        _cache_set(cache_key, items)
    return items


def item_metadata(item: ContentItem) -> dict:
    """Serialise an article's source metadata for persistence/attribution."""
    return {
        "title": item.title,
        "url": item.url,
        "source_name": item.source_name,
        "image_url": item.image_url,
        "published_at": item.published_at.isoformat() if item.published_at else None,
    }


def _origin(url: str) -> str:
    """Return ``scheme://host/`` for a URL, or ``""`` when unparseable."""
    try:
        parts = urlsplit(url or "")
    except Exception:  # noqa: BLE001
        return ""
    if parts.scheme and parts.netloc:
        return f"{parts.scheme}://{parts.netloc}/"
    return ""


def _request_headers(item: ContentItem) -> dict:
    """Browser-like headers; Referer prefers the article URL then image origin."""
    headers = dict(_BROWSER_HEADERS)
    referer = (getattr(item, "url", None) or "").strip() or _origin(
        getattr(item, "image_url", None) or ""
    )
    if referer:
        headers["Referer"] = referer
    return headers


def _sniff_ext(data: bytes) -> str | None:
    """Guess an image extension from magic bytes (used when Content-Type is absent)."""
    if not data:
        return None
    for magic, ext in _MAGIC_EXT:
        if data.startswith(magic):
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def _guess_ext(url: str, content_type, data: bytes | None = None) -> str:
    if isinstance(content_type, str):
        ct = content_type.split(";")[0].strip().lower()
        if ct in _EXT_BY_CONTENT_TYPE:
            return _EXT_BY_CONTENT_TYPE[ct]
    sniffed = _sniff_ext(data or b"")
    if sniffed:
        return sniffed
    match = re.search(r"\.(jpg|jpeg|png|webp|gif|bmp)(?:\?|#|$)", url or "", re.IGNORECASE)
    if match:
        return "." + match.group(1).lower()
    return ".jpg"


async def download_article_images(
    items: list[ContentItem],
    dest_dir: Path,
    task_logger: TaskLogger | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[Path]:
    """Download each article's ``image_url`` into ``dest_dir/news_images``.

    Missing or failed downloads are skipped silently (a warning is logged); the
    caller falls back to online stock imagery.
    """
    dest = Path(dest_dir) / NEWS_IMAGES_DIRNAME
    dest.mkdir(parents=True, exist_ok=True)

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)

    paths: list[Path] = []
    try:
        for idx, item in enumerate(items):
            url = (item.image_url or "").strip()
            if not url:
                continue
            try:
                response = await client.get(url, headers=_request_headers(item))
                status = getattr(response, "status_code", None)
                if isinstance(status, int) and status >= 400:
                    logger.warning(f"Failed to download news image {url}: HTTP {status}")
                    if task_logger:
                        task_logger.warning(f"新闻配图下载失败 (HTTP {status}): {url}")
                    continue
                response.raise_for_status()
                data = response.content or b""
                if not data:
                    continue
                ext = _guess_ext(
                    url, getattr(response, "headers", {}).get("content-type"), data
                )
                digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
                path = dest / f"news_{idx:02d}_{digest}{ext}"
                path.write_bytes(data)
                paths.append(path)
                if task_logger:
                    task_logger.info(f"新闻配图下载成功 {idx + 1}: {path.name} ({len(data)} bytes)")
                    task_logger.set_file(f"news_image_{idx}", path)
            except Exception as e:  # noqa: BLE001 - never fail the whole task on one image
                logger.warning(f"Failed to download news image {url}: {e}")
                if task_logger:
                    task_logger.warning(f"新闻配图下载失败: {e}")
    finally:
        if owns_client:
            await client.aclose()

    return paths


async def resolve_news_content(request, task_dir: Path, task_logger: TaskLogger) -> dict:
    """Enrich a news request with fetched article title/content/images.

    Mutates ``request`` in place (title/content + private ``_news_*`` attrs) and
    persists source metadata to the task status + ``news_articles.json``.
    """
    query = _resolve_query(request)
    task_logger.info(f"新闻检索词: {query or '(top headlines)'}")

    items = await _load_articles(request, query)
    if not items:
        # No articles: honor explicit user content if given, else fail loudly.
        provided = (getattr(request, "content", None) or "").strip()
        if not provided:
            raise ValueError("未获取到新闻文章（GNews 配额/网络/关键词问题），无法生成 news 视频")
        task_logger.warning("未获取到新闻文章，使用用户提供的 title/content，素材走在线图库")
        if not (getattr(request, "title", None) or "").strip():
            first_line = next((ln.strip() for ln in provided.splitlines() if ln.strip()), "News")
            _assign(request, "title", first_line[:80])
        task_logger.set_meta("content_type", "news")
        _assign(request, "_news_images", [])
        return {
            "source_name": None,
            "source_url": None,
            "image_count": 0,
            "articles": [],
        }

    primary = items[0]

    title = (getattr(request, "title", None) or "").strip() or primary.title
    content = (getattr(request, "content", None) or "").strip()
    if not content:
        parts = [primary.title, primary.content]
        content = "\n\n".join(p for p in parts if p)
    # Fold additional article descriptions in so the AI has richer material.
    extras = [i.content for i in items[1:] if i.content]
    if extras:
        content = "\n\n".join([content, *extras])
    content = content[:20000]

    _assign(request, "title", title)
    _assign(request, "content", content)

    task_logger.info(f"选用头条: {title} | 来源: {primary.source_name} | {primary.url}")

    images = await download_article_images(items, Path(task_dir), task_logger)
    _assign(request, "_news_images", images)
    _assign(request, "_news_items", items)
    _assign(request, "_news_source_name", primary.source_name)
    _assign(request, "_news_source_url", primary.url)

    metadata = [item_metadata(i) for i in items]
    task_logger.set_meta("content_type", "news")
    task_logger.set_meta("source_name", primary.source_name)
    task_logger.set_meta("source_url", primary.url)
    task_logger.set_meta("news_articles", metadata)

    sidecar = Path(task_dir) / "news_articles.json"
    try:
        sidecar.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        task_logger.set_file("news_articles", sidecar)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Failed to write news_articles.json: {e}")

    task_logger.info(f"获取到 {len(items)} 篇文章，{len(images)} 张配图")
    return {
        "source_name": primary.source_name,
        "source_url": primary.url,
        "image_count": len(images),
        "articles": metadata,
    }
