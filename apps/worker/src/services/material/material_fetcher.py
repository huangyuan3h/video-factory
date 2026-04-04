"""Material fetcher facade for video backgrounds."""

import logging
from pathlib import Path

from .pexels_service import PexelsService
from .pixabay_service import PixabayService
from .local_assets_service import LocalAssetsService

logger = logging.getLogger(__name__)


KEYWORD_TRANSLATIONS = {
    "体检报告": "medical report",
    "焦虑": "anxiety",
    "健康饮食": "healthy food",
    "燕麦": "oatmeal",
    "糙米": "brown rice",
    "血糖监测": "blood sugar",
    "鸡胸肉": "chicken breast",
    "三文鱼": "salmon",
    "脂肪肝": "liver health",
    "西兰花": "broccoli",
    "黑木耳": "mushroom",
    "低卡料理": "healthy meal",
    "橙子": "orange",
    "蓝莓": "blueberry",
    "杏仁": "almond",
    "冬瓜": "winter melon",
    "肾结石": "health",
    "超市购物": "grocery shopping",
    "程序员": "programmer",
    "电脑屏幕": "computer screen",
    "代码滚动": "coding",
    "音频波形": "audio",
    "耳机": "headphones",
    "进度条": "progress",
    "勾选符号": "checkmark",
    "服务器机房": "server room",
    "成功手势": "success",
    "大拇指": "thumbs up",
    "离开背影": "walking away",
    "下载图标": "download",
    "思维导图": "mind map",
    "打字动作": "typing",
    "拍摄现场": "filming",
    "摄影器材": "camera equipment",
    "灯光布置": "lighting",
    "剪辑软件": "video editing",
    "波形图": "waveform",
    "手指滑动屏幕": "touch screen",
    "成品展示": "showcase",
    "点赞手势": "like",
    "关注按钮": "subscribe",
    "写字特写": "writing",
    "咖啡时光": "coffee",
    "办公场景": "office",
    "思考特写": "thinking",
    "视频创作": "video creation",
    "脚本构思": "writing",
    "健康食材合集": "healthy ingredients",
    "健康餐盘": "healthy plate",
    "剥开橙子": "peeling orange",
    "蓝莓特写": "blueberries",
    "手抓杏仁": "handful almonds",
    "清炒西兰花": "broccoli cooking",
    "凉拌黑木耳": "mushroom salad",
    "冬瓜汤": "soup",
    "鸡胸肉沙拉": "chicken salad",
    "香煎三文鱼": "grilled salmon",
    "肝脏健康": "liver",
    "血糖": "blood sugar",
    "血压": "blood pressure",
}


FALLBACK_KEYWORDS = [
    "healthy food",
    "cooking",
    "nutrition",
    "vegetables",
    "fruits",
    "wellness",
    "fitness",
    "nature",
    "lifestyle",
]


class MaterialFetcher:
    """Fetch video/image materials from various sources."""

    def __init__(
        self,
        pexels_api_key: str | None = None,
        pixabay_api_key: str | None = None,
        local_assets_dir: Path | None = None,
    ):
        self.pexels = PexelsService(pexels_api_key)
        self.pixabay = PixabayService(pixabay_api_key)
        self.local = LocalAssetsService(local_assets_dir)

    def _translate_keywords(self, keywords: list[str]) -> list[str]:
        """Translate Chinese keywords to English."""
        translated = []
        for kw in keywords:
            if kw in KEYWORD_TRANSLATIONS:
                translated.append(KEYWORD_TRANSLATIONS[kw])
            elif any("\u4e00" <= c <= "\u9fff" for c in kw):
                logger.info(f"No translation for: {kw}")
            else:
                translated.append(kw)
        return translated if translated else FALLBACK_KEYWORDS[:3]

    async def fetch_videos(
        self,
        keywords: list[str],
        count: int = 5,
        source: str = "both",
    ) -> list[Path]:
        """Fetch video materials based on keywords."""
        videos = []
        english_keywords = self._translate_keywords(keywords)
        logger.info(f"Translated keywords: {english_keywords}")

        if source in ("online", "both"):
            online_videos = await self.pexels.fetch_videos(english_keywords, count)
            videos.extend(online_videos)

            if not videos:
                logger.info("No videos found, trying fallback keywords")
                for fallback in FALLBACK_KEYWORDS[:3]:
                    fallback_videos = await self.pexels.fetch_videos([fallback], count // 3 + 1)
                    videos.extend(fallback_videos)
                    if len(videos) >= count:
                        break

        if source in ("local", "both"):
            local_videos = await self.local.fetch_videos(count)
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
        english_keywords = self._translate_keywords(keywords)
        logger.info(f"Translated keywords for images: {english_keywords}")

        if source in ("online", "both"):
            images.extend(await self.pexels.fetch_images(english_keywords, count))
            images.extend(await self.pixabay.fetch_images(english_keywords, count))

            if not images:
                logger.info("No images found, trying fallback keywords")
                for fallback in FALLBACK_KEYWORDS[:3]:
                    fallback_images = await self.pexels.fetch_images([fallback], count // 3 + 1)
                    images.extend(fallback_images)
                    if len(images) >= count:
                        break

        if source in ("local", "both"):
            local_images = await self.local.fetch_images(count)
            images.extend(local_images)

        return images[:count]