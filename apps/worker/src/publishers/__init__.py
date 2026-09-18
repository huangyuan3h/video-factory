"""Publishers package for auto-publishing to social platforms."""

from .base import BasePublisher, PublishResult
from .douyin import DouyinPublisher
from .xiaohongshu import XiaohongshuPublisher

try:
    from .youtube import YoutubePublisher
except Exception:  # optional dep
    YoutubePublisher = None  # type: ignore

__all__ = [
    "BasePublisher",
    "PublishResult",
    "DouyinPublisher",
    "XiaohongshuPublisher",
    "YoutubePublisher",
]

# Registry for extensibility — add new platforms here
PUBLISHER_REGISTRY: dict[str, type[BasePublisher]] = {
    "douyin": DouyinPublisher,
    "xiaohongshu": XiaohongshuPublisher,
    "xhs": XiaohongshuPublisher,
}
if YoutubePublisher is not None:
    PUBLISHER_REGISTRY["youtube"] = YoutubePublisher
    PUBLISHER_REGISTRY["yt"] = YoutubePublisher


def get_publisher(platform: str, **kwargs) -> BasePublisher:
    key = platform.lower().strip()
    cls = PUBLISHER_REGISTRY.get(key)
    if not cls:
        raise ValueError(f"Unsupported platform: {platform}. Available: {list(PUBLISHER_REGISTRY)}")
    return cls(**kwargs)


def list_platforms() -> list[str]:
    return sorted(set(PUBLISHER_REGISTRY.keys()))
