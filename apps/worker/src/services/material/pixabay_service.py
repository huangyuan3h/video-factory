"""Pixabay API service for fetching images."""

import logging
import tempfile
from pathlib import Path

import aiofiles
import httpx

logger = logging.getLogger(__name__)


class PixabayService:
    """Fetch images from Pixabay API."""

    BASE_URL = "https://pixabay.com/api"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    async def fetch_images(
        self,
        keywords: list[str],
        count: int = 10,
    ) -> list[Path]:
        """Fetch images from Pixabay API."""
        if not self.api_key:
            return []

        query = " ".join(keywords)
        images = []

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(
                    self.BASE_URL,
                    params={
                        "key": self.api_key,
                        "q": query,
                        "per_page": count,
                        "orientation": "vertical",
                        "image_type": "photo",
                    },
                )
                response.raise_for_status()
                data = response.json()
                
                total = data.get("totalHits", 0)
                logger.info(f"Pixabay found {total} images for '{query}'")

                for hit in data.get("hits", []):
                    image_url = hit.get("largeImageURL")
                    if image_url:
                        path = await self._download_file(
                            image_url, f"pixabay_{hit['id']}.jpg"
                        )
                        if path:
                            images.append(path)

        except Exception as e:
            logger.error(f"Failed to fetch images from Pixabay: {e}")

        return images

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