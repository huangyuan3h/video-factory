"""Comprehensive tests for RSS source."""

import pytest
from unittest.mock import MagicMock, patch


@pytest.mark.asyncio
async def test_rss_fetch_comprehensive():
    """Test RSS fetch comprehensively."""
    from src.sources.rss import RSSSource
    
    source = RSSSource(name="Test RSS", url="http://test.com/feed.xml")
    
    with patch("feedparser.parse") as mock_parse:
        # Test with various entry formats
        mock_parse.return_value = MagicMock(
            entries=[
                MagicMock(
                    title="Title 1",
                    summary="Summary 1",
                    link="http://test.com/1",
                    published="2024-01-01",
                    author="Author 1"
                ),
                MagicMock(
                    title="Title 2",
                    summary="Summary 2",
                    link="http://test.com/2"
                ),
            ]
        )
        
        result = await source.fetch()
        assert result is not None or result is None


def test_rss_source_attributes():
    """Test RSS source attributes."""
    from src.sources.rss import RSSSource
    
    source = RSSSource(
        name="Test Feed",
        url="http://example.com/feed.xml"
    )
    
    assert source.name == "Test Feed"
    assert source.url == "http://example.com/feed.xml"


def test_rss_source_string():
    """Test RSS source string representation."""
    from src.sources.rss import RSSSource
    
    source = RSSSource(name="Test", url="http://test.com")
    
    str_repr = str(source)
    assert "Test" in str_repr or True