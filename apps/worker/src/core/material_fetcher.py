"""Material fetcher for video backgrounds."""

import logging
import tempfile
from pathlib import Path

import aiofiles
import httpx

from ..config import settings

logger = logging.getLogger(__name__)


# Chinese to English keyword mapping for better search results
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

# Fallback keywords when search returns no results
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
        self.pexels_api_key = pexels_api_key or settings.pexels_api_key
        self.pixabay_api_key = pixabay_api_key or settings.pixabay_api_key
        self.local_assets_dir = local_assets_dir or settings.assets_dir

        self.pexels_base_url = "https://api.pexels.com/v1"
        self.pixabay_base_url = "https://pixabay.com/api"

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

        # Translate keywords
        english_keywords = self._translate_keywords(keywords)
        logger.info(f"Translated keywords: {english_keywords}")

        if source in ("online", "both") and self.pexels_api_key:
            online_videos = await self._fetch_from_pexels(english_keywords, count)
            videos.extend(online_videos)

            # Fallback to generic keywords if no results
            if not videos:
                logger.info("No videos found, trying fallback keywords")
                for fallback in FALLBACK_KEYWORDS[:3]:
                    fallback_videos = await self._fetch_from_pexels([fallback], count // 3 + 1)
                    videos.extend(fallback_videos)
                    if len(videos) >= count:
                        break

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

        # Translate keywords
        english_keywords = self._translate_keywords(keywords)
        logger.info(f"Translated keywords for images: {english_keywords}")

        if source in ("online", "both"):
            if self.pexels_api_key:
                images.extend(await self._fetch_images_from_pexels(english_keywords, count))
            if self.pixabay_api_key:
                images.extend(await self._fetch_images_from_pixabay(english_keywords, count))

            # Fallback to generic keywords if no results
            if not images:
                logger.info("No images found, trying fallback keywords")
                for fallback in FALLBACK_KEYWORDS[:3]:
                    if self.pexels_api_key:
                        fallback_images = await self._fetch_images_from_pexels([fallback], count // 3 + 1)
                        images.extend(fallback_images)
                    if len(images) >= count:
                        break

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
            async with httpx.AsyncClient(timeout=60.0) as client:
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
                
                total = data.get("total_results", 0)
                logger.info(f"Pexels found {total} videos for '{query}'")

                for video in data.get("videos", []):
                    video_files = video.get("video_files", [])
                    # Prefer 1080p resolution
                    selected_file = None
                    for vf in video_files:
                        if vf.get("width") == 1080 and vf.get("height") == 1920:
                            selected_file = vf
                            break
                    if not selected_file and video_files:
                        selected_file = video_files[0]
                    
                    if selected_file and selected_file.get("link"):
                        path = await self._download_file(selected_file["link"], f"pexels_{video['id']}.mp4")
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
            async with httpx.AsyncClient(timeout=60.0) as client:
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
                
                total = data.get("total_results", 0)
                logger.info(f"Pexels found {total} images for '{query}'")

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
            async with httpx.AsyncClient(timeout=60.0) as client:
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
                
                total = data.get("totalHits", 0)
                logger.info(f"Pixabay found {total} images for '{query}'")

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

        video_files = list(videos_dir.glob("*.mp4")) + list(videos_dir.glob("*.mov"))
        return video_files[:count]

    async def _fetch_images_from_local(self, keywords: list[str], count: int) -> list[Path]:
        """Fetch images from local assets directory."""
        images_dir = self.local_assets_dir / "images"
        if not images_dir.exists():
            return []

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