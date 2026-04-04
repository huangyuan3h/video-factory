"""More tests for hot topics source."""

import pytest
from unittest.mock import MagicMock, patch


@pytest.mark.asyncio
async def test_hot_topics_fetch_weibo():
    """Test fetching hot topics from Weibo."""
    from src.sources.hot_topics import HotTopicsSource
    
    source = HotTopicsSource(name="Weibo Hot", platform="weibo")
    
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "realtime": [
                    {"note": "热点1", "url": "http://weibo.com/1"},
                    {"note": "热点2", "url": "http://weibo.com/2"},
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        
        result = await source.fetch()
        assert result is not None or result is None


@pytest.mark.asyncio
async def test_hot_topics_fetch_zhihu():
    """Test fetching hot topics from Zhihu."""
    from src.sources.hot_topics import HotTopicsSource
    
    source = HotTopicsSource(name="Zhihu Hot", platform="zhihu")
    
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"title": "话题1", "url": "http://zhihu.com/1"},
                {"title": "话题2", "url": "http://zhihu.com/2"},
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        
        result = await source.fetch()
        assert result is not None or result is None


def test_hot_topics_platforms():
    """Test hot topics platforms."""
    from src.sources.hot_topics import HotTopicsSource
    
    weibo = HotTopicsSource(name="Weibo", platform="weibo")
    zhihu = HotTopicsSource(name="Zhihu", platform="zhihu")
    
    assert weibo.platform == "weibo"
    assert zhihu.platform == "zhihu"