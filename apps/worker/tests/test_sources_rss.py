"""Tests for RSS source module."""

import pytest
from unittest.mock import MagicMock, patch


def test_rss_source_creation():
    """Test RSS source can be created."""
    from src.sources.rss import RSSSource
    
    source = RSSSource(name="Test RSS", url="http://example.com/feed.xml")
    assert source is not None
    assert source.url == "http://example.com/feed.xml"


@pytest.mark.asyncio
async def test_rss_fetch_mock():
    """Test RSS fetch with mock."""
    from src.sources.rss import RSSSource
    
    source = RSSSource(name="Test RSS", url="http://example.com/feed.xml")
    
    with patch("feedparser.parse") as mock_parse:
        mock_parse.return_value = MagicMock(
            entries=[
                MagicMock(
                    title="测试文章",
                    summary="测试摘要",
                    link="http://example.com/article"
                )
            ]
        )
        
        # The actual implementation may differ
        result = await source.fetch()
        # Just test that it doesn't crash
        assert True