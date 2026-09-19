"""Pexels API service for fetching videos and images."""

import logging
import tempfile
from pathlib import Path

import aiofiles
import httpx

logger = logging.getLogger(__name__)

# Prefer the sharpest sources Pexels offers. `large2x`/`original` are ~2x the
# long edge of `large`, which keeps 1080p/portrait videos from looking soft.
IMAGE_SRC_PREFERENCE = ("large2x", "original", "large")

# Stills narrower than this are skipped when better candidates exist.
MIN_IMAGE_WIDTH = 1280


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
        videos = []
        used = set(exclude_ids or ())

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(
                    f"{self.BASE_URL}/videos/search",
                    params={
                        "query": query,
                        "per_page": min(80, max(count * 3, count)) if used else count,
                        "orientation": orientation,
                    },
                    headers={"Authorization": self.api_key},
                )
                response.raise_for_status()
                data = response.json()
                
                total = data.get("total_results", 0)
                logger.info(f"Pexels found {total} videos for '{query}'")

                for video in data.get("videos", []):
                    if len(videos) >= count:
                        break
                    video_id = video.get("id")
                    if video_id is not None and video_id in used:
                        continue
                    video_files = video.get("video_files", [])
                    selected_file = self._select_video_file(video_files)
                    
                    if selected_file and selected_file.get("link"):
                        path = await self._download_file(
                            selected_file["link"], f"pexels_{video['id']}.mp4"
                        )
                        if path:
                            videos.append(path)
                            if video_id is not None:
                                used.add(video_id)
                                if exclude_ids is not None:
                                    exclude_ids.add(video_id)

        except Exception as e:
            logger.error(f"Failed to fetch from Pexels: {e}")

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
        images = []
        used = set(exclude_ids or ())

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(
                    f"{self.BASE_URL}/search",
                    params={
                        "query": query,
                        # Fetch extra candidates so low-res results and
                        # already-used ids can be skipped without falling short.
                        "per_page": min(80, max(count * 3, 15) if used else max(count, 15)),
                        "orientation": orientation,
                    },
                    headers={"Authorization": self.api_key},
                )
                response.raise_for_status()
                data = response.json()
                
                total = data.get("total_results", 0)
                logger.info(f"Pexels found {total} images for '{query}'")

                for photo in rank_photos(data.get("photos", [])):
                    if len(images) >= count:
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
                        path = await self._download_file(
                            image_url, f"pexels_{photo['id']}.jpg"
                        )
                        if path:
                            images.append(path)
                            if photo_id is not None:
                                used.add(photo_id)
                                if exclude_ids is not None:
                                    exclude_ids.add(photo_id)

        except Exception as e:
            logger.error(f"Failed to fetch images from Pexels: {e}")

        return images

    def _select_video_file(self, video_files: list[dict]) -> dict | None:
        """Select the best video file (prefer 1920x1080 landscape)."""
        if not video_files:
            return None
        
        # Prefer landscape 1920x1080
        for vf in video_files:
            if vf.get("width") == 1920 and vf.get("height") == 1080:
                return vf
        for vf in video_files:
            if vf.get("width") == 1080 and vf.get("height") == 1920:
                return vf
        
        return video_files[0]

    async def _download_file(self, url: str, filename: str) -> Path | None:
        """Download a file from URL."""
        try:
            temp_dir = Path(tempfile.mkdtemp())
            output_path = temp_dir / filename

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(url)
                response.raise_for_status()

                async with aiofiles.open(output_path, "wb") as f:
                    await f.write(response.content)

            logger.info(f"Downloaded {filename} ({len(response.content)} bytes)")
            return output_path

        except Exception as e:
            logger.error(f"Failed to download {url}: {e}")
            return None