"""Service layer for video generation."""

from .compose_service import compose_video
from .cover_service import generate_cover_image
from .material import MaterialFetcher
from .settings_service import get_active_ai_client, get_general_settings
from .video_service import run_video_generation, video_tasks

__all__ = [
    "get_active_ai_client",
    "get_general_settings",
    "generate_cover_image",
    "compose_video",
    "run_video_generation",
    "video_tasks",
    "MaterialFetcher",
]
