"""Deep tests for sources init."""

import pytest


def test_sources_all():
    """Test all sources can be imported."""
    from src.sources import RSSSource, HotTopicsSource, NewsAPISource
    
    assert RSSSource is not None
    assert HotTopicsSource is not None
    assert NewsAPISource is not None


def test_create_all_sources():
    """Test creating all source types."""
    from src.sources import RSSSource, HotTopicsSource, NewsAPISource
    
    rss = RSSSource(name="RSS", url="http://test.com")
    hot = HotTopicsSource(name="Hot", platform="weibo")
    news = NewsAPISource(name="News", api_key="test")
    
    assert rss is not None
    assert hot is not None
    assert news is not None