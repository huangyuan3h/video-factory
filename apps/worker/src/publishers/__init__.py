"""Publishers package for auto-publishing to social platforms."""

from .base import BasePublisher, PublishResult
from .douyin import DouyinPublisher
from .xiaohongshu import XiaohongshuPublisher

try:
    from .bili import BiliPublisher
except Exception:  # optional dep
    BiliPublisher = None  # type: ignore

try:
    from .youtube import YoutubePublisher
except Exception:  # optional dep
    YoutubePublisher = None  # type: ignore

try:
    from .zhihu import ZhihuPublisher
except Exception:  # playwright import is lazy; keep registry usable
    ZhihuPublisher = None  # type: ignore

try:
    from .toutiao import ToutiaoPublisher
except Exception:  # playwright import is lazy; keep registry usable
    ToutiaoPublisher = None  # type: ignore

__all__ = [
    "BasePublisher",
    "PublishResult",
    "DouyinPublisher",
    "XiaohongshuPublisher",
    "BiliPublisher",
    "YoutubePublisher",
    "ZhihuPublisher",
    "ToutiaoPublisher",
]

# Registry for extensibility — add new platforms here
PUBLISHER_REGISTRY: dict[str, type[BasePublisher]] = {
    "douyin": DouyinPublisher,
    "xiaohongshu": XiaohongshuPublisher,
    "xhs": XiaohongshuPublisher,
}
if BiliPublisher is not None:
    PUBLISHER_REGISTRY["bilibili"] = BiliPublisher
    PUBLISHER_REGISTRY["bili"] = BiliPublisher
if YoutubePublisher is not None:
    PUBLISHER_REGISTRY["youtube"] = YoutubePublisher
    PUBLISHER_REGISTRY["yt"] = YoutubePublisher
if ZhihuPublisher is not None:
    PUBLISHER_REGISTRY["zhihu"] = ZhihuPublisher
if ToutiaoPublisher is not None:
    PUBLISHER_REGISTRY["toutiao"] = ToutiaoPublisher
    PUBLISHER_REGISTRY["tt"] = ToutiaoPublisher


def get_publisher(platform: str, **kwargs) -> BasePublisher:
    key = platform.lower().strip()
    cls = PUBLISHER_REGISTRY.get(key)
    if not cls:
        raise ValueError(f"Unsupported platform: {platform}. Available: {list(PUBLISHER_REGISTRY)}")
    return cls(**kwargs)


def list_platforms() -> list[str]:
    return sorted(set(PUBLISHER_REGISTRY.keys()))
