"""Pexels API service for fetching videos and images."""

import asyncio
import logging
import tempfile
import time
from pathlib import Path

import aiofiles
import httpx

logger = logging.getLogger(__name__)

# Prefer the sharpest sources Pexels offers. `large2x`/`original` are ~2x the
# long edge of `large`, which keeps 1080p/portrait videos from looking soft.
IMAGE_SRC_PREFERENCE = ("large2x", "original", "large")

# Stills narrower than this are skipped when better candidates exist.
MIN_IMAGE_WIDTH = 1280

VIDEO_TARGET_RESOLUTIONS = {
    "landscape": (1920, 1080),
    "portrait": (1080, 1920),
    "square": (1080, 1080),
}
VIDEO_QUALITY_RANK = {"sd": 1, "hd": 3, "uhd": 4, "4k": 4}

# 2026-10-02 polish: slow Pexels downloads (sequential 60s timeout, no cache).
# - In-memory search cache (TTL 5 min) so repeated segment queries reuse JSON.
# - Concurrent file downloads (max 4) via gather + semaphore.
# - Tighter timeouts: 15s search, 30s file (fail fast, fallback to next source).
SEARCH_TIMEOUT_S = 15.0
DOWNLOAD_TIMEOUT_S = 30.0
SEARCH_CACHE_TTL_S = 300
DOWNLOAD_CONCURRENCY = 4

_SEARCH_CACHE: dict[tuple, tuple[float, dict]] = {}
_DOWNLOAD_SEM = asyncio.Semaphore(DOWNLOAD_CONCURRENCY)


def _cache_key(endpoint: str, query: str, per_page: int, orientation: str) -> tuple:
    return (endpoint, query, per_page, orientation)


def _cache_get(key: tuple) -> dict | None:
    entry = _SEARCH_CACHE.get(key)
    if not entry:
        return None
    ts, data = entry
    if time.monotonic() - ts > SEARCH_CACHE_TTL_S:
        _SEARCH_CACHE.pop(key, None)
        return None
    return data


def _cache_set(key: tuple, data: dict) -> None:
    # Cap size to avoid unbounded growth in long episodes.
    if len(_SEARCH_CACHE) > 200:
        _SEARCH_CACHE.clear()
    _SEARCH_CACHE[key] = (time.monotonic(), data)


def clear_pexels_cache() -> None:
    """Clear the in-memory Pexels search cache (tests)."""
    _SEARCH_CACHE.clear()


def select_image_url(src: dict | None) -> str | None:
    """Pick the highest-quality URL available in a Pexels ``src`` dict."""
    src = src or {}
    for key in IMAGE_SRC_PREFERENCE:
        url = src.get(key)
        if url:
            return url
    return None


def photo_width(photo: dict | None) -> int:
    """Best-effort width for a Pexels photo (0 when metadata is absent)."""
    if not photo:
        return 0
    try:
        width = int(photo.get("width") or 0)
    except (TypeError, ValueError):
        width = 0
    return width


def alt_matches(photo: dict | None, terms: tuple[str, ...] | list[str] | None) -> bool:
    """True when a photo's ``alt`` text mentions any avoided term.

    Used by the book path to drop literal soap/foam/bubble results when the
    chapter is economic history and better candidates exist.
    """
    if not photo or not terms:
        return False
    alt = str(photo.get("alt") or "").lower()
    if not alt:
        return False
    return any(str(term).lower() in alt for term in terms if term)


def _number(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _video_orientation_matches(width: float, height: float, orientation: str) -> bool:
    if width <= 0 or height <= 0:
        return False
    if orientation == "portrait":
        return height > width
    if orientation == "square":
        return abs(width / height - 1.0) <= 0.12
    return width > height


def rank_photos(photos: list[dict]) -> list[dict]:
    """Order photos best-first, dropping low-res ones when better exist.

    Width metadata is frequently missing in fixtures/mocks, so photos without
    it are kept as acceptable fallbacks and sorted last.
    """
    photos = list(photos or [])
    if not photos:
        return []
    if any(photo_width(p) > 0 for p in photos):
        acceptable = [
            p for p in photos if photo_width(p) == 0 or photo_width(p) >= MIN_IMAGE_WIDTH
        ]
        if acceptable:
            photos = acceptable
    return sorted(photos, key=photo_width, reverse=True)


class PexelsService:
    """Fetch videos and images from Pexels API."""

    BASE_URL = "https://api.pexels.com/v1"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    async def fetch_videos(
        self,
        keywords: list[str],
        count: int = 5,
        orientation: str = "landscape",
        exclude_ids: set[int] | None = None,
    ) -> list[Path]:
        """Fetch videos from Pexels API.

        ``exclude_ids`` works like in :meth:`fetch_images` so a task never
        reuses the same clip id across segments.
        """
        if not self.api_key:
            return []

        query = " ".join(keywords)
        used = set(exclude_ids or ())

        try:
            per_page = min(80, max(count * 3, count)) if used else count
            key = _cache_key("videos/search", query, per_page, orientation)
            data = _cache_get(key)
            if data is None:
                async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT_S) as client:
                    response = await client.get(
                        f"{self.BASE_URL}/videos/search",
                        params={
                            "query": query,
                            "per_page": per_page,
                            "orientation": orientation,
                        },
                        headers={"Authorization": self.api_key},
                    )
                    response.raise_for_status()
                    data = response.json()
                    _cache_set(key, data)
            else:
                logger.info(f"Pexels video cache hit for '{query}'")

            total = data.get("total_results", 0)
            logger.info(f"Pexels found {total} videos for '{query}'")

            # Collect candidates first, then download concurrently (max 4).
            candidates: list[tuple[str, str, int | None]] = []
            for video in data.get("videos", []):
                if len(candidates) >= count:
                    break
                video_id = video.get("id")
                if video_id is not None and video_id in used:
                    continue
                video_files = video.get("video_files", [])
                selected_file = self._select_video_file(video_files, orientation=orientation)
                if selected_file:
                    logger.info(
                        f"Pexels selected video {video.get('id')}: "
                        f"{selected_file.get('width')}x{selected_file.get('height')} "
                        f"({selected_file.get('quality') or 'unknown'})"
                    )

                if selected_file and selected_file.get("link"):
                    candidates.append(
                        (selected_file["link"], f"pexels_{video['id']}.mp4", video_id)
                    )

            async def _one(link: str, filename: str) -> Path | None:
                async with _DOWNLOAD_SEM:
                    return await self._download_file(link, filename)

            paths = await asyncio.gather(
                *[_one(link, fn) for link, fn, _vid in candidates]
            )
            videos: list[Path] = []
            for ( _link, _fn, video_id), path in zip(candidates, paths):
                if path:
                    videos.append(path)
                    if video_id is not None:
                        used.add(video_id)
                        if exclude_ids is not None:
                            exclude_ids.add(video_id)

        except Exception as e:
            logger.error(f"Failed to fetch from Pexels: {e}")
            return []

        return videos

    async def fetch_images(
        self,
        keywords: list[str],
        count: int = 10,
        orientation: str = "landscape",
        exclude_ids: set[int] | None = None,
        avoid_alt_terms: tuple[str, ...] | list[str] | None = None,
    ) -> list[Path]:
        """Fetch images from Pexels API.

        ``exclude_ids`` is a caller-owned set of already-used photo ids (one per
        episode). Photos in it are skipped and the ranked list is walked further;
        ids downloaded here are added back to it so repeated calls never reuse a
        still. The candidate pool is widened when exclusions are in play.
        ``avoid_alt_terms`` skips photos whose ``alt`` text is a literal
        soap/foam match (see the book visual-safe path).
        """
        if not self.api_key:
            return []

        query = " ".join(keywords)
        used = set(exclude_ids or ())

        try:
            per_page = min(80, max(count * 3, 15) if used else max(count, 15))
            key = _cache_key("search", query, per_page, orientation)
            data = _cache_get(key)
            if data is None:
                async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT_S) as client:
                    response = await client.get(
                        f"{self.BASE_URL}/search",
                        params={
                            "query": query,
                            # Fetch extra candidates so low-res results and
                            # already-used ids can be skipped without falling short.
                            "per_page": per_page,
                            "orientation": orientation,
                        },
                        headers={"Authorization": self.api_key},
                    )
                    response.raise_for_status()
                    data = response.json()
                    _cache_set(key, data)
            else:
                logger.info(f"Pexels image cache hit for '{query}'")

            total = data.get("total_results", 0)
            logger.info(f"Pexels found {total} images for '{query}'")

            candidates: list[tuple[str, str, int | None]] = []
            for photo in rank_photos(data.get("photos", [])):
                if len(candidates) >= count:
                    break
                photo_id = photo.get("id")
                if photo_id is not None and photo_id in used:
                    continue
                if alt_matches(photo, avoid_alt_terms):
                    logger.info(
                        f"Skip literal stock photo {photo_id}: alt={photo.get('alt')!r}"
                    )
                    continue
                image_url = select_image_url(photo.get("src"))
                if image_url:
                    candidates.append((image_url, f"pexels_{photo['id']}.jpg", photo_id))

            async def _one(link: str, filename: str) -> Path | None:
                async with _DOWNLOAD_SEM:
                    return await self._download_file(link, filename)

            paths = await asyncio.gather(
                *[_one(link, fn) for link, fn, _pid in candidates]
            )
            images: list[Path] = []
            for (_link, _fn, photo_id), path in zip(candidates, paths):
                if path:
                    images.append(path)
                    if photo_id is not None:
                        used.add(photo_id)
                        if exclude_ids is not None:
                            exclude_ids.add(photo_id)

        except Exception as e:
            logger.error(f"Failed to fetch images from Pexels: {e}")
            return []

        return images

    def _select_video_file(
        self, video_files: list[dict], orientation: str = "landscape"
    ) -> dict | None:
        """Select a file matching the requested orientation, capped near 1080p.

        Preference order:
        1. exact target resolution for the orientation;
        2. otherwise the largest file whose short side is <= 1080 (never 4K);
        3. if every candidate is above 1080, the smallest one above 1080.
        Quality rank then fps break ties.
        """
        candidates = [
            video_file
            for video_file in (video_files or [])
            if isinstance(video_file, dict) and video_file.get("link")
        ]
        if not candidates:
            return None

        target_width, target_height = VIDEO_TARGET_RESOLUTIONS.get(
            orientation, VIDEO_TARGET_RESOLUTIONS["landscape"]
        )
        matching_orientation = [
            video_file
            for video_file in candidates
            if _video_orientation_matches(
                _number(video_file.get("width")),
                _number(video_file.get("height")),
                orientation,
            )
        ]
        pool = matching_orientation or candidates

        def area(video_file: dict) -> float:
            return _number(video_file.get("width")) * _number(video_file.get("height"))

        def quality_key(video_file: dict) -> tuple[int, float]:
            quality = str(video_file.get("quality") or "").lower()
            return (VIDEO_QUALITY_RANK.get(quality, 0), _number(video_file.get("fps")))

        exact_resolution = [
            video_file
            for video_file in pool
            if _number(video_file.get("width")) == target_width
            and _number(video_file.get("height")) == target_height
        ]
        if exact_resolution:
            return max(exact_resolution, key=lambda f: (area(f), quality_key(f)))

        capped = [
            video_file
            for video_file in pool
            if 0 < min(
                _number(video_file.get("width")), _number(video_file.get("height"))
            ) <= 1080
        ]
        if capped:
            return max(capped, key=lambda f: (area(f), quality_key(f)))

        above = [
            video_file
            for video_file in pool
            if min(_number(video_file.get("width")), _number(video_file.get("height"))) > 1080
        ]
        if above:
            return min(above, key=lambda f: (area(f), tuple(-v for v in quality_key(f))))

        return max(pool, key=lambda f: (area(f), quality_key(f)))

    async def _download_file(self, url: str, filename: str) -> Path | None:
        """Download a file from URL (30s timeout, concurrent via semaphore)."""
        try:
            temp_dir = Path(tempfile.mkdtemp())
            output_path = temp_dir / filename

            async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT_S) as client:
                response = await client.get(url)
                response.raise_for_status()

                async with aiofiles.open(output_path, "wb") as f:
                    await f.write(response.content)

            logger.info(f"Downloaded {filename} ({len(response.content)} bytes)")
            return output_path

        except Exception as e:
            logger.error(f"Failed to download {url}: {e}")
            return None
