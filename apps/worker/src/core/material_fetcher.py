"""Material fetcher for video backgrounds."""

import logging
import tempfile
from pathlib import Path

import aiofiles
import httpx

from ..config import settings

logger = logging.getLogger(__name__)


class MaterialFetcher:
    """Fetch video/image materials from various sources."""

    def __init__(
        self,
        pexels_api_key: str | None = None,
        pixabay_api_key: str | None = None,
        local_assets_dir: Path | None = None,
    ):
        self.pexels_api_key = pexels_api_key or settings.pexels_api_key
        self.pixabay_api_key = pixabay_api_key or settings.pixabay_api_key
        self.local_assets_dir = local_assets_dir or settings.assets_dir

        self.pexels_base_url = "https://api.pexels.com/v1"
        self.pixabay_base_url = "https://pixabay.com/api"

    async def fetch_videos(
        self,
        keywords: list[str],
        count: int = 5,
        source: str = "both",  # online, local, both
    ) -> list[Path]:
        """Fetch video materials based on keywords.

        Args:
            keywords: Keywords for searching
            count: Number of videos to fetch
            source: Source type (online, local, both)

        Returns:
            List of paths to video files
        """
        videos = []

        if source in ("online", "both") and self.pexels_api_key:
            online_videos = await self._fetch_from_pexels(keywords, count)
            videos.extend(online_videos)

        if source in ("local", "both") and self.local_assets_dir:
            local_videos = await self._fetch_from_local(keywords, count)
            videos.extend(local_videos)

        return videos[:count]

    async def fetch_images(
        self,
        keywords: list[str],
        count: int = 10,
        source: str = "both",
    ) -> list[Path]:
        """Fetch image materials based on keywords."""
        images = []

        if source in ("online", "both"):
            if self.pexels_api_key:
                images.extend(await self._fetch_images_from_pexels(keywords, count))
            if self.pixabay_api_key:
                images.extend(await self._fetch_images_from_pixabay(keywords, count))

        if source in ("local", "both") and self.local_assets_dir:
            images.extend(await self._fetch_images_from_local(keywords, count))

        return images[:count]

    async def _fetch_from_pexels(self, keywords: list[str], count: int) -> list[Path]:
        """Fetch videos from Pexels API."""
        if not self.pexels_api_key:
            return []

        query = " ".join(keywords)
        videos = []

        try:
            async with httpx.AsyncClient() as client:
                # Search videos
                response = await client.get(
                    f"{self.pexels_base_url}/videos/search",
                    params={
                        "query": query,
                        "per_page": count,
                        "orientation": "portrait",
                    },
                    headers={"Authorization": self.pexels_api_key},
                )
                response.raise_for_status()
                data = response.json()

                # Download videos
                for video in data.get("videos", []):
                    video_url = video.get("video_files", [{}])[0].get("link")
                    if video_url:
                        path = await self._download_file(video_url, f"pexels_{video['id']}.mp4")
                        if path:
                            videos.append(path)

        except Exception as e:
            logger.error(f"Failed to fetch from Pexels: {e}")

        return videos

    async def _fetch_images_from_pexels(self, keywords: list[str], count: int) -> list[Path]:
        """Fetch images from Pexels API."""
        if not self.pexels_api_key:
            return []

        query = " ".join(keywords)
        images = []

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.pexels_base_url}/search",
                    params={
                        "query": query,
                        "per_page": count,
                        "orientation": "portrait",
                    },
                    headers={"Authorization": self.pexels_api_key},
                )
                response.raise_for_status()
                data = response.json()

                for photo in data.get("photos", []):
                    image_url = photo.get("src", {}).get("large")
                    if image_url:
                        path = await self._download_file(image_url, f"pexels_{photo['id']}.jpg")
                        if path:
                            images.append(path)

        except Exception as e:
            logger.error(f"Failed to fetch images from Pexels: {e}")

        return images

    async def _fetch_images_from_pixabay(self, keywords: list[str], count: int) -> list[Path]:
        """Fetch images from Pixabay API."""
        if not self.pixabay_api_key:
            return []

        query = " ".join(keywords)
        images = []

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    self.pixabay_base_url,
                    params={
                        "key": self.pixabay_api_key,
                        "q": query,
                        "per_page": count,
                        "orientation": "vertical",
                        "image_type": "photo",
                    },
                )
                response.raise_for_status()
                data = response.json()

                for hit in data.get("hits", []):
                    image_url = hit.get("largeImageURL")
                    if image_url:
                        path = await self._download_file(image_url, f"pixabay_{hit['id']}.jpg")
                        if path:
                            images.append(path)

        except Exception as e:
            logger.error(f"Failed to fetch images from Pixabay: {e}")

        return images

    async def _fetch_from_local(self, keywords: list[str], count: int) -> list[Path]:
        """Fetch videos from local assets directory."""
        videos_dir = self.local_assets_dir / "videos"
        if not videos_dir.exists():
            return []

        # Get all video files
        video_files = list(videos_dir.glob("*.mp4")) + list(videos_dir.glob("*.mov"))
        return video_files[:count]

    async def _fetch_images_from_local(self, keywords: list[str], count: int) -> list[Path]:
        """Fetch images from local assets directory."""
        images_dir = self.local_assets_dir / "images"
        if not images_dir.exists():
            return []

        # Get all image files
        image_files = (
            list(images_dir.glob("*.jpg"))
            + list(images_dir.glob("*.jpeg"))
            + list(images_dir.glob("*.png"))
        )
        return image_files[:count]

    async def _download_file(self, url: str, filename: str) -> Path | None:
        """Download a file from URL."""
        try:
            temp_dir = Path(tempfile.mkdtemp())
            output_path = temp_dir / filename

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url)
                response.raise_for_status()

                async with aiofiles.open(output_path, "wb") as f:
                    await f.write(response.content)

            logger.info(f"Downloaded {url} to {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Failed to download {url}: {e}")
            return None
