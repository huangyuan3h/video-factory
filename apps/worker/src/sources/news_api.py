"""News API content source."""

import logging
from datetime import datetime

import httpx

from .base import BaseSource, ContentItem

logger = logging.getLogger(__name__)


class NewsAPISource(BaseSource):
    """News API content source (supports various news APIs)."""

    # Common news API endpoints
    PROVIDERS = {
        "newsapi": {
            "base_url": "https://newsapi.org/v2",
            "auth_type": "header",  # header or param
        },
        "gnews": {
            "base_url": "https://gnews.io/api/v4",
            "auth_type": "param",
        },
    }

    def __init__(
        self,
        name: str,
        api_key: str,
        provider: str = "newsapi",
        keywords: list[str] | None = None,
        category: str | None = None,
        country: str = "us",
    ):
        super().__init__(name, keywords)
        self.api_key = api_key
        self.provider = provider
        self.category = category
        self.country = country

        config = self.PROVIDERS.get(provider, self.PROVIDERS["newsapi"])
        self.base_url = config["base_url"]
        self.auth_type = config["auth_type"]

    async def fetch(self, count: int = 10) -> list[ContentItem]:
        """Fetch news articles from API."""
        items = []

        try:
            params = {
                "pageSize": count,
                "country": self.country,
            }

            if self.keywords:
                params["q"] = " OR ".join(self.keywords)
            if self.category:
                params["category"] = self.category

            headers = {}

            if self.provider == "newsapi":
                endpoint = f"{self.base_url}/top-headlines"
                headers["X-Api-Key"] = self.api_key
            elif self.provider == "gnews":
                endpoint = f"{self.base_url}/top-headlines"
                params["token"] = self.api_key
            else:
                endpoint = f"{self.base_url}/top-headlines"

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(endpoint, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()

            # Parse response based on provider
            articles = data.get("articles", [])

            for article in articles:
                published_at = None
                if article.get("publishedAt"):
                    try:
                        published_at = datetime.fromisoformat(
                            article["publishedAt"].replace("Z", "+00:00")
                        )
                    except ValueError:
                        pass

                item = ContentItem(
                    title=article.get("title", "Untitled"),
                    content=article.get("description", "") or article.get("content", ""),
                    url=article.get("url"),
                    author=article.get("author"),
                    published_at=published_at,
                    image_url=article.get("urlToImage"),
                    source_name=article.get("source", {}).get("name", self.name),
                )
                items.append(item)

            logger.info(f"Fetched {len(items)} articles from News API: {self.name}")

        except Exception as e:
            logger.error(f"Failed to fetch from News API: {e}")

        return items
