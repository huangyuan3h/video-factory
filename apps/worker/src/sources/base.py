"""Base class for content sources."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class ContentItem:
    """A piece of content from a source."""

    title: str
    content: str
    url: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    image_url: Optional[str] = None
    source_name: Optional[str] = None


class BaseSource(ABC):
    """Abstract base class for content sources."""

    def __init__(
        self,
        name: str,
        keywords: Optional[list[str]] = None,
    ):
        self.name = name
        self.keywords = keywords or []

    @abstractmethod
    async def fetch(self, count: int = 10) -> list[ContentItem]:
        """Fetch content items from the source.

        Args:
            count: Maximum number of items to fetch

        Returns:
            List of ContentItem objects
        """
        pass

    def filter_by_keywords(self, items: list[ContentItem]) -> list[ContentItem]:
        """Filter content items by keywords."""
        if not self.keywords:
            return items

        filtered = []
        for item in items:
            text = f"{item.title} {item.content}".lower()
            if any(kw.lower() in text for kw in self.keywords):
                filtered.append(item)

        return filtered