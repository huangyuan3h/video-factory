"""Publishers package for auto-publishing to social platforms."""

from .base import BasePublisher, PublishResult
from .douyin import DouyinPublisher
from .xiaohongshu import XiaohongshuPublisher

try:
    from .bili import BiliPublisher
except Exception:  # optional dep  # pragma: no cover - import fallback, dep present in test env
    BiliPublisher = None  # type: ignore

try:
    from .youtube import YoutubePublisher
except Exception:  # optional dep  # pragma: no cover - import fallback, dep present in test env
    YoutubePublisher = None  # type: ignore

try:
    from .zhihu import ZhihuPublisher
except Exception:  # playwright import is lazy; keep registry usable  # pragma: no cover - import fallback, dep present in test env
    ZhihuPublisher = None  # type: ignore

try:
    from .toutiao import ToutiaoPublisher
except Exception:  # playwright import is lazy; keep registry usable  # pragma: no cover - import fallback, dep present in test env
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
    "register_publisher",
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


def register_publisher(name: str, cls: type[BasePublisher], *, aliases: tuple[str, ...] = ()) -> type[BasePublisher]:
    """Register a new publishing platform without touching core code.

    Example::

        from src.publishers import BasePublisher, register_publisher

        class MyPublisher(BasePublisher):
            platform_name = "myblog"
            ...  # pure helpers first (parse_*/build_*/validate_*,
                 # is_already_published/should_refuse_publish), Playwright
                 # only inside ``async def`` browser methods.

        register_publisher("myblog", MyPublisher)

    After that ``vf publish --to myblog --dry-run`` discovers it and
    ``get_publisher("myblog")`` constructs it.
    """
    key = name.lower().strip()
    if not key:
        raise ValueError("platform name must not be empty")
    if not (isinstance(cls, type) and issubclass(cls, BasePublisher)):
        raise ValueError(f"register_publisher({name!r}): cls must subclass BasePublisher")
    PUBLISHER_REGISTRY[key] = cls
    for alias in aliases:
        PUBLISHER_REGISTRY[alias.lower().strip()] = cls
    return cls


def get_publisher(platform: str, **kwargs) -> BasePublisher:
    key = platform.lower().strip()
    cls = PUBLISHER_REGISTRY.get(key)
    if not cls:
        raise ValueError(f"Unsupported platform: {platform}. Available: {list(PUBLISHER_REGISTRY)}")
    return cls(**kwargs)


def list_platforms() -> list[str]:
    return sorted(set(PUBLISHER_REGISTRY.keys()))
