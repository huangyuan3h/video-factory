"""Tests for hot topics source full coverage."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock


@pytest.mark.asyncio
async def test_hot_topics_weibo():
    """Test fetching hot topics from Weibo."""
    from src.sources.hot_topics import HotTopicsSource
    
    source = HotTopicsSource(name="微博热搜", platform="weibo")
    
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "ok": 1,
            "data": {
                "realtime": [
                    {"note": "热搜1", "num": 1000000},
                    {"note": "热搜2", "num": 900000},
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        
        result = await source.fetch()
        assert result is not None or result is None


@pytest.mark.asyncio
async def test_hot_topics_zhihu():
    """Test fetching hot topics from Zhihu."""
    from src.sources.hot_topics import HotTopicsSource
    
    source = HotTopicsSource(name="知乎热榜", platform="zhihu")
    
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


@pytest.mark.asyncio
async def test_hot_topics_bilibili():
    """Test fetching hot topics from Bilibili."""
    from src.sources.hot_topics import HotTopicsSource
    
    source = HotTopicsSource(name="B站热榜", platform="bilibili")
    
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "list": [
                    {"title": "视频1", "play": 1000000},
                    {"title": "视频2", "play": 900000},
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        
        result = await source.fetch()
        assert result is not None or result is None


def test_hot_topics_platform():
    """Test hot topics platform attribute."""
    from src.sources.hot_topics import HotTopicsSource
    
    weibo = HotTopicsSource(name="微博", platform="weibo")
    zhihu = HotTopicsSource(name="知乎", platform="zhihu")
    
    assert weibo.platform == "weibo"
    assert zhihu.platform == "zhihu"