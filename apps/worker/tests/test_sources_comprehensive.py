"""Comprehensive tests for sources module."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime


class TestSourcesComprehensive:
    """Comprehensive tests for sources module."""

    def test_base_source_methods(self):
        """Test BaseSource methods."""
        from src.sources.base import BaseSource, ContentItem
        
        class TestSource(BaseSource):
            async def fetch(self, count=10):
                return []
        
        source = TestSource(name="Test", keywords=["python", "test"])
        
        items = [
            ContentItem(title="Python Tutorial", content="Learn Python", source_name="Test"),
            ContentItem(title="JavaScript Guide", content="Learn JS", source_name="Test"),
        ]
        
        filtered = source.filter_by_keywords(items)
        assert len(filtered) == 1

    def test_content_item_all_fields(self):
        """Test ContentItem with all fields."""
        from src.sources.base import ContentItem
        
        item = ContentItem(
            title="Test Title",
            content="Test Content",
            url="http://test.com",
            author="Test Author",
            published_at=datetime.now(),
            image_url="http://test.com/image.jpg",
            source_name="Test Source"
        )
        
        assert item.title == "Test Title"
        assert item.author == "Test Author"

    @pytest.mark.asyncio
    async def test_rss_source_fetch_mock(self):
        """Test RSS source fetch with mock."""
        from src.sources.rss import RSSSource
        
        source = RSSSource(name="Test", url="http://test.com/rss")
        
        mock_response = MagicMock()
        mock_response.text = """
        <rss>
            <channel>
                <item>
                    <title>Test</title>
                    <link>http://test.com</link>
                    <description>Content</description>
                </item>
            </channel>
        </rss>
        """
        mock_response.raise_for_status = MagicMock()
        
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            
            items = await source.fetch(count=5)

    @pytest.mark.asyncio
    async def test_hot_topics_fetch_mock(self):
        """Test hot topics fetch with mock."""
        from src.sources.hot_topics import HotTopicsSource
        
        source = HotTopicsSource(name="Test", platform="zhihu")
        
        mock_response = MagicMock()
        mock_response.text = '{"data": [{"target": {"title": "Test", "id": "123"}}]}'
        mock_response.raise_for_status = MagicMock()
        
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            
            items = await source.fetch(count=5)

    def test_news_api_source(self):
        """Test NewsAPISource."""
        from src.sources.news_api import NewsAPISource
        
        source = NewsAPISource(name="Test", api_key="test-key")
        assert source.api_key == "test-key"


class TestNewsAPISource:
    """Tests for NewsAPISource."""

    def test_news_api_init(self):
        """Test NewsAPISource initialization."""
        from src.sources.news_api import NewsAPISource
        
        source = NewsAPISource(name="Test News", api_key="key")
        assert source.name == "Test News"
        assert source.api_key == "key"

    @pytest.mark.asyncio
    async def test_news_api_fetch_no_key(self):
        """Test NewsAPISource fetch without key."""
        from src.sources.news_api import NewsAPISource
        
        source = NewsAPISource(name="Test", api_key=None)
        items = await source.fetch(count=5)
        assert items == []

    @pytest.mark.asyncio
    async def test_news_api_fetch_with_mock(self):
        """Test NewsAPISource fetch with mock."""
        from src.sources.news_api import NewsAPISource
        
        source = NewsAPISource(name="Test", api_key="test-key")
        
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "articles": [
                {"title": "Test", "description": "Content", "url": "http://test.com"}
            ]
        }
        mock_response.raise_for_status = MagicMock()
        
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            
            items = await source.fetch(count=5)


class TestAIClientCoverage:
    """Tests for AI client coverage."""

    def test_ai_client_init(self):
        """Test AIClient initialization."""
        from src.core.ai_client import AIClient
        
        client = AIClient(
            base_url="http://test",
            api_key="key",
            model="model"
        )
        assert client.base_url == "http://test"
        assert client.model == "model"


class TestVideoGeneratorCoverage:
    """Tests for VideoGenerator coverage."""

    def test_video_generator_init(self):
        """Test VideoGenerator initialization."""
        from src.core.video_generator import VideoGenerator
        
        gen = VideoGenerator()
        assert gen is not None