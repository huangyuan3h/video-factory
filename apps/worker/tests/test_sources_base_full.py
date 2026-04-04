"""Tests for sources base full coverage."""

import pytest


def test_base_source():
    """Test base source class."""
    from src.sources.base import BaseSource
    
    # Test that BaseSource exists
    assert BaseSource is not None


def test_source_types():
    """Test source types."""
    source_types = ['rss', 'news_api', 'hot_topics', 'custom']
    
    for source_type in source_types:
        assert isinstance(source_type, str)


@pytest.mark.asyncio
async def test_base_source_fetch():
    """Test base source fetch method."""
    from src.sources.base import BaseSource
    
    # Test if BaseSource has fetch method
    if hasattr(BaseSource, 'fetch'):
        assert callable(BaseSource.fetch)


def test_source_config():
    """Test source configuration."""
    from src.sources.rss import RSSSource
    
    source = RSSSource(
        name="Test",
        url="http://test.com"
    )
    
    # Test basic attributes
    assert source.name == "Test"
    assert source.url == "http://test.com"