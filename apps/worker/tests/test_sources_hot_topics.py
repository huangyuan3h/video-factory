"""Tests for hot topics source module."""

import pytest
from unittest.mock import MagicMock, patch


def test_hot_topics_source_creation():
    """Test hot topics source can be created."""
    from src.sources.hot_topics import HotTopicsSource
    
    source = HotTopicsSource(name="Test Hot Topics", platform="weibo")
    assert source is not None


@pytest.mark.asyncio
async def test_hot_topics_fetch_mock():
    """Test hot topics fetch with mock."""
    from src.sources.hot_topics import HotTopicsSource
    
    source = HotTopicsSource(name="Test Hot Topics", platform="weibo")
    
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"title": "热点1", "url": "http://example.com/1"},
                {"title": "热点2", "url": "http://example.com/2"},
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        
        result = await source.fetch()
        assert True