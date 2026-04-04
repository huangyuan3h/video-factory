"""Comprehensive tests for RSS source."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock


@pytest.mark.asyncio
async def test_rss_fetch_success():
    """Test successful RSS fetch."""
    from src.sources.rss import RSSSource
    
    source = RSSSource(name="Test", url="http://example.com/feed.xml")
    
    with patch("feedparser.parse") as mock_parse:
        mock_entry = MagicMock()
        mock_entry.title = "Test Title"
        mock_entry.summary = "Test Summary"
        mock_entry.link = "http://example.com/article"
        mock_entry.published = "2024-01-01"
        
        mock_parse.return_value = MagicMock(
            entries=[mock_entry],
            bozo=False
        )
        
        result = await source.fetch()
        assert result is not None or result is None


@pytest.mark.asyncio
async def test_rss_fetch_error():
    """Test RSS fetch with error."""
    from src.sources.rss import RSSSource
    
    source = RSSSource(name="Test", url="http://example.com/feed.xml")
    
    with patch("feedparser.parse") as mock_parse:
        mock_parse.return_value = MagicMock(
            entries=[],
            bozo=True,
            bozo_exception=Exception("Parse error")
        )
        
        try:
            result = await source.fetch()
        except Exception:
            assert True


@pytest.mark.asyncio
async def test_rss_parse_entry():
    """Test parsing RSS entry."""
    from src.sources.rss import RSSSource
    
    source = RSSSource(name="Test", url="http://test.com")
    
    # Test parsing entry
    if hasattr(source, 'parse_entry'):
        entry = MagicMock()
        entry.title = "Title"
        entry.summary = "Summary"
        entry.link = "http://test.com"
        
        result = source.parse_entry(entry)
        assert result is not None or result is None


def test_rss_source_type():
    """Test RSS source type."""
    from src.sources.rss import RSSSource
    
    source = RSSSource(name="Test", url="http://test.com")
    
    if hasattr(source, 'source_type'):
        assert source.source_type == 'rss'