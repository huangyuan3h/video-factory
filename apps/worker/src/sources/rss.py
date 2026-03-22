"""RSS feed content source."""

import logging
from datetime import datetime

import feedparser
import httpx

from .base import BaseSource, ContentItem

logger = logging.getLogger(__name__)


class RSSSource(BaseSource):
    """RSS/Atom feed content source."""

    def __init__(
        self,
        name: str,
        url: str,
        keywords: list[str] | None = None,
    ):
        super().__init__(name, keywords)
        self.url = url

    async def fetch(self, count: int = 10) -> list[ContentItem]:
        """Fetch content from RSS feed."""
        items = []

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(self.url)
                response.raise_for_status()

            feed = feedparser.parse(response.text)

            for entry in feed.entries[:count]:
                # Parse publication date
                published_at = None
                if hasattr(entry, "published_parsed"):
                    try:
                        published_at = datetime(*entry.published_parsed[:6])
                    except (TypeError, ValueError):
                        pass

                # Get content
                content = ""
                if hasattr(entry, "content"):
                    content = entry.content[0].get("value", "")
                elif hasattr(entry, "summary"):
                    content = entry.summary

                # Clean HTML from content
                content = self._clean_html(content)

                item = ContentItem(
                    title=entry.get("title", "Untitled"),
                    content=content,
                    url=entry.get("link"),
                    author=entry.get("author"),
                    published_at=published_at,
                    source_name=self.name,
                )
                items.append(item)

            logger.info(f"Fetched {len(items)} items from RSS: {self.name}")

        except Exception as e:
            logger.error(f"Failed to fetch RSS feed {self.url}: {e}")

        return self.filter_by_keywords(items)

    def _clean_html(self, text: str) -> str:
        """Remove HTML tags from text."""
        import re
        # Remove HTML tags
        text = re.sub(r"<[^>]+>", "", text)
        # Decode HTML entities
        import html
        text = html.unescape(text)
        return text.strip()
