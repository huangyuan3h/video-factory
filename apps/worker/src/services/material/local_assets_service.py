"""Local assets service for fetching videos and images."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class LocalAssetsService:
    """Fetch videos and images from local assets directory."""

    def __init__(self, assets_dir: Path | None = None):
        self.assets_dir = assets_dir

    async def fetch_videos(self, count: int = 5) -> list[Path]:
        """Fetch videos from local assets directory."""
        if not self.assets_dir:
            return []

        videos_dir = self.assets_dir / "videos"
        if not videos_dir.exists():
            return []

        video_files = list(videos_dir.glob("*.mp4")) + list(videos_dir.glob("*.mov"))
        return video_files[:count]

    async def fetch_images(self, count: int = 10) -> list[Path]:
        """Fetch images from local assets directory."""
        if not self.assets_dir:
            return []

        images_dir = self.assets_dir / "images"
        if not images_dir.exists():
            return []

        image_files = (
            list(images_dir.glob("*.jpg"))
            + list(images_dir.glob("*.jpeg"))
            + list(images_dir.glob("*.png"))
        )
        return image_files[:count]