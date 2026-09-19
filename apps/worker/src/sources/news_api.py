"""News API content source (NewsAPI.org + GNews.io)."""

import logging
from datetime import datetime

import httpx

from .base import BaseSource, ContentItem

logger = logging.getLogger(__name__)


class NewsAPISource(BaseSource):
    """News API content source (supports various news APIs).

    Both providers return an ``articles`` list but differ in query params and
    field names. GNews uses ``image`` for the article picture, a ``max`` param
    (free tier caps at 10) and an ``apikey`` query param, while NewsAPI.org uses
    ``urlToImage``, ``pageSize`` and an ``X-Api-Key`` header.
    """

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
        lang: str | None = None,
    ):
        super().__init__(name, keywords)
        self.api_key = api_key
        self.provider = (provider or "newsapi").lower()
        self.category = category
        self.country = country
        self.lang = lang

        config = self.PROVIDERS.get(self.provider, self.PROVIDERS["newsapi"])
        self.base_url = config["base_url"]
        self.auth_type = config["auth_type"]

    async def fetch(self, count: int = 10, query: str | None = None) -> list[ContentItem]:
        """Fetch news articles from API.

        Args:
            count: Maximum number of articles to request.
            query: Optional explicit search query. Falls back to the instance
                keywords joined with " OR ".
        """
        items: list[ContentItem] = []

        search_query = (query or "").strip() or None
        if not search_query and self.keywords:
            search_query = " OR ".join(str(k) for k in self.keywords if str(k).strip())

        try:
            params: dict = {}
            headers: dict = {}

            if self.provider == "newsapi":
                endpoint_path = "/everything" if search_query else "/top-headlines"
                params["pageSize"] = count
                if search_query:
                    params["q"] = search_query
                else:
                    params["country"] = self.country
                if self.category and not search_query:
                    params["category"] = self.category
                headers["X-Api-Key"] = self.api_key
            else:  # gnews (and generic fallback)
                endpoint_path = "/search" if search_query else "/top-headlines"
                params["max"] = min(int(count), 10)  # free tier hard cap
                if search_query:
                    params["q"] = search_query
                else:
                    params["country"] = self.country
                if self.category and not search_query:
                    params["category"] = self.category
                if self.lang:
                    params["lang"] = self.lang
                # GNews accepts the key as "apikey"; older docs/examples use "token".
                params["apikey"] = self.api_key

            endpoint = f"{self.base_url}{endpoint_path}"

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(endpoint, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()

            articles = data.get("articles", []) or []
            items = [self._parse_article(a) for a in articles if isinstance(a, dict)]
            items = [i for i in items if i is not None]

            logger.info(f"Fetched {len(items)} articles from {self.provider}: {self.name}")

        except Exception as e:
            logger.error(f"Failed to fetch from News API: {e}")

        return items

    async def search(self, query: str, count: int = 10) -> list[ContentItem]:
        """Convenience wrapper for a keyword search."""
        return await self.fetch(count=count, query=query)

    def _parse_article(self, article: dict) -> ContentItem | None:
        """Parse a provider article dict into a ContentItem (robust to shape)."""
        title = article.get("title") or "Untitled"
        content = (
            article.get("description")
            or article.get("content")
            or article.get("snippet")
            or ""
        )

        published_at = None
        raw_published = article.get("publishedAt") or article.get("published_at")
        if raw_published:
            try:
                published_at = datetime.fromisoformat(str(raw_published).replace("Z", "+00:00"))
            except ValueError:
                published_at = None

        # GNews: article["image"]; NewsAPI: article["urlToImage"]
        image_url = article.get("image") or article.get("urlToImage")

        return ContentItem(
            title=title,
            content=content,
            url=article.get("url"),
            author=article.get("author"),
            published_at=published_at,
            image_url=image_url,
            source_name=self._parse_source_name(article),
        )

    def _parse_source_name(self, article: dict) -> str:
        """Resolve the source label robustly.

        NewsAPI returns a {"name": ...} object; GNews returns a plain string.
        """
        source = article.get("source")
        if isinstance(source, dict):
            name = source.get("name")
            if name:
                return str(name)
        elif isinstance(source, str) and source.strip():
            return source.strip()
        return self.name
