"""Hot topics/trending content source."""

import logging
import re

import httpx
from bs4 import BeautifulSoup

from .base import BaseSource, ContentItem

logger = logging.getLogger(__name__)


class HotTopicsSource(BaseSource):
    """Hot topics/trending content from various platforms."""

    PLATFORMS = {
        "weibo": {
            "name": "Weibo Hot Search",
            "url": "https://s.weibo.com/top/summary",
            "parser": "_parse_weibo",
        },
        "zhihu": {
            "name": "Zhihu Hot Topics",
            "url": "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total",
            "parser": "_parse_zhihu",
        },
        "douyin": {
            "name": "Douyin Hot",
            "url": "https://www.douyin.com/discover",
            "parser": "_parse_douyin",
        },
    }

    def __init__(
        self,
        name: str,
        platform: str = "weibo",
        keywords: list[str] | None = None,
    ):
        super().__init__(name, keywords)
        self.platform = platform

        config = self.PLATFORMS.get(platform, self.PLATFORMS["weibo"])
        self.url = config["url"]
        self.parser_name = config["parser"]

    async def fetch(self, count: int = 10) -> list[ContentItem]:
        """Fetch trending topics."""
        items = []

        try:
            parser = getattr(self, self.parser_name, None)
            if not parser:
                logger.error(f"No parser for platform: {self.platform}")
                return items

            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
            ) as client:
                response = await client.get(self.url)
                response.raise_for_status()

            items = await parser(response.text, count)

            logger.info(f"Fetched {len(items)} trending items from {self.platform}")

        except Exception as e:
            logger.error(f"Failed to fetch hot topics from {self.platform}: {e}")

        return self.filter_by_keywords(items)

    async def _parse_weibo(self, html: str, count: int) -> list[ContentItem]:
        """Parse Weibo hot search."""
        items = []
        soup = BeautifulSoup(html, "lxml")

        # Weibo hot search structure
        rows = soup.select("tbody tr")[:count]

        for row in rows:
            try:
                title_elem = row.select_one("td a")
                if not title_elem:
                    continue

                title = title_elem.get_text(strip=True)
                href = title_elem.get("href", "")
                url = f"https://s.weibo.com{href}" if href.startswith("/") else href

                # Get heat score
                heat_elem = row.select_one("td span")
                heat = heat_elem.get_text(strip=True) if heat_elem else ""

                item = ContentItem(
                    title=title,
                    content=f"Weibo hot topic with {heat} discussions",
                    url=url,
                    source_name="Weibo",
                )
                items.append(item)

            except Exception as e:
                logger.debug(f"Failed to parse Weibo item: {e}")
                continue

        return items

    async def _parse_zhihu(self, json_str: str, count: int) -> list[ContentItem]:
        """Parse Zhihu hot topics."""
        items = []

        try:
            import json
            data = json.loads(json_str)

            for item in data.get("data", [])[:count]:
                target = item.get("target", {})

                content_item = ContentItem(
                    title=target.get("title", "Untitled"),
                    content=target.get("excerpt", ""),
                    url=f"https://www.zhihu.com/question/{target.get('id', '')}",
                    source_name="Zhihu",
                )
                items.append(content_item)

        except Exception as e:
            logger.error(f"Failed to parse Zhihu response: {e}")

        return items

    async def _parse_douyin(self, html: str, count: int) -> list[ContentItem]:
        """Parse Douyin trending (basic implementation)."""
        # Douyin requires more complex handling with cookies
        # This is a basic placeholder
        items = []

        try:
            # Look for trending data in embedded JSON
            match = re.search(r"_ROUTER_DATA\s*=\s*(\{.*?\})", html)
            if match:
                import json
                data = json.loads(match.group(1))

                # Parse trending data structure
                # This varies by Douyin's current page structure

        except Exception as e:
            logger.debug(f"Failed to parse Douyin response: {e}")

        return items
