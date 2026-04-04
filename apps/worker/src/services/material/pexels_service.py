"""Pexels API service for fetching videos and images."""

import logging
import tempfile
from pathlib import Path

import aiofiles
import httpx

logger = logging.getLogger(__name__)


class PexelsService:
    """Fetch videos and images from Pexels API."""

    BASE_URL = "https://api.pexels.com/v1"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    async def fetch_videos(
        self,
        keywords: list[str],
        count: int = 5,
    ) -> list[Path]:
        """Fetch videos from Pexels API."""
        if not self.api_key:
            return []

        query = " ".join(keywords)
        videos = []

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(
                    f"{self.BASE_URL}/videos/search",
                    params={
                        "query": query,
                        "per_page": count,
                        "orientation": "portrait",
                    },
                    headers={"Authorization": self.api_key},
                )
                response.raise_for_status()
                data = response.json()
                
                total = data.get("total_results", 0)
                logger.info(f"Pexels found {total} videos for '{query}'")

                for video in data.get("videos", []):
                    video_files = video.get("video_files", [])
                    selected_file = self._select_video_file(video_files)
                    
                    if selected_file and selected_file.get("link"):
                        path = await self._download_file(
                            selected_file["link"], f"pexels_{video['id']}.mp4"
                        )
                        if path:
                            videos.append(path)

        except Exception as e:
            logger.error(f"Failed to fetch from Pexels: {e}")

        return videos

    async def fetch_images(
        self,
        keywords: list[str],
        count: int = 10,
    ) -> list[Path]:
        """Fetch images from Pexels API."""
        if not self.api_key:
            return []

        query = " ".join(keywords)
        images = []

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(
                    f"{self.BASE_URL}/search",
                    params={
                        "query": query,
                        "per_page": count,
                        "orientation": "portrait",
                    },
                    headers={"Authorization": self.api_key},
                )
                response.raise_for_status()
                data = response.json()
                
                total = data.get("total_results", 0)
                logger.info(f"Pexels found {total} images for '{query}'")

                for photo in data.get("photos", []):
                    image_url = photo.get("src", {}).get("large")
                    if image_url:
                        path = await self._download_file(
                            image_url, f"pexels_{photo['id']}.jpg"
                        )
                        if path:
                            images.append(path)

        except Exception as e:
            logger.error(f"Failed to fetch images from Pexels: {e}")

        return images

    def _select_video_file(self, video_files: list[dict]) -> dict | None:
        """Select the best video file (prefer 1080p portrait)."""
        if not video_files:
            return None
        
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