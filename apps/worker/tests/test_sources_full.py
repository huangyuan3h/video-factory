"""Full tests for sources module."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime


class TestRSSSource:
    """Tests for RSSSource class."""

    def test_rss_source_import(self):
        """Test RSSSource import."""
        from src.sources.rss import RSSSource
        assert RSSSource is not None

    def test_rss_source_init(self):
        """Test RSSSource initialization."""
        from src.sources.rss import RSSSource
        
        source = RSSSource(
            name="Test RSS",
            url="http://test.com/rss",
            keywords=["test"]
        )
        assert source.name == "Test RSS"
        assert source.url == "http://test.com/rss"
        assert source.keywords == ["test"]

    def test_rss_source_clean_html(self):
        """Test _clean_html method."""
        from src.sources.rss import RSSSource
        
        source = RSSSource(name="Test", url="http://test.com/rss")
        
        html = "<p>Hello <b>World</b></p>"
        cleaned = source._clean_html(html)
        assert "<p>" not in cleaned
        assert "<b>" not in cleaned

    def test_rss_source_clean_html_entities(self):
        """Test _clean_html with HTML entities."""
        from src.sources.rss import RSSSource
        
        source = RSSSource(name="Test", url="http://test.com/rss")
        
        html = "Hello &amp; World"
        cleaned = source._clean_html(html)
        assert "&amp;" not in cleaned

    @pytest.mark.asyncio
    async def test_rss_source_fetch_error(self):
        """Test fetch when HTTP error occurs."""
        from src.sources.rss import RSSSource
        
        source = RSSSource(name="Test", url="http://test.com/rss")
        
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock()
            mock_client.return_value.__aenter__.get = AsyncMock()
            mock_client.return_value.__aenter__.get.side_effect = Exception("Connection error")
            
            items = await source.fetch(count=5)
            assert items == []

    @pytest.mark.asyncio
    async def test_rss_source_fetch_success(self):
        """Test fetch with successful response."""
        from src.sources.rss import RSSSource
        
        source = RSSSource(name="Test", url="http://test.com/rss")
        
        mock_response = MagicMock()
        mock_response.text = """
        <rss>
            <channel>
                <item>
                    <title>Test Item</title>
                    <link>http://test.com/item1</link>
                    <description>Test description</description>
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


class TestSourcesInit:
    """Tests for sources __init__.py."""

    def test_sources_init_imports(self):
        """Test sources module imports."""
        from src.sources import RSSSource, HotTopicsSource, NewsAPISource
        
        assert RSSSource is not None
        assert HotTopicsSource is not None
        assert NewsAPISource is not None

    def test_sources_all_exports(self):
        """Test __all__ exports."""
        from src.sources import __all__
        
        assert "RSSSource" in __all__
        assert "HotTopicsSource" in __all__
        assert "NewsAPISource" in __all__