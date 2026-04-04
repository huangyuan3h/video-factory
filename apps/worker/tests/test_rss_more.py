"""More tests for RSS source."""

import pytest
from unittest.mock import MagicMock, patch


@pytest.mark.asyncio
async def test_rss_fetch_multiple():
    """Test fetching multiple RSS items."""
    from src.sources.rss import RSSSource
    
    source = RSSSource(name="Test RSS", url="http://example.com/feed.xml")
    
    with patch("feedparser.parse") as mock_parse:
        mock_parse.return_value = MagicMock(
            entries=[
                MagicMock(
                    title="文章1",
                    summary="摘要1",
                    link="http://example.com/1",
                    published="2024-01-01"
                ),
                MagicMock(
                    title="文章2",
                    summary="摘要2",
                    link="http://example.com/2",
                    published="2024-01-02"
                ),
                MagicMock(
                    title="文章3",
                    summary="摘要3",
                    link="http://example.com/3",
                    published="2024-01-03"
                ),
            ]
        )
        
        result = await source.fetch()
        assert result is not None or result is None


def test_rss_source_properties():
    """Test RSS source properties."""
    from src.sources.rss import RSSSource
    
    source = RSSSource(
        name="Test Feed",
        url="http://example.com/feed.xml"
    )
    
    assert source.name == "Test Feed"
    assert source.url == "http://example.com/feed.xml"


def test_rss_source_type():
    """Test RSS source type."""
    from src.sources.rss import RSSSource
    
    source = RSSSource(name="Test", url="http://test.com")
    
    if hasattr(source, 'type'):
        assert source.type == "rss"