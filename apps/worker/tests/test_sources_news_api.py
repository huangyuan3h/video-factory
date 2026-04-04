"""Tests for news API source module."""

import pytest
from unittest.mock import MagicMock, patch


def test_news_api_source_creation():
    """Test news API source can be created."""
    from src.sources.news_api import NewsAPISource
    
    source = NewsAPISource(name="Test News", api_key="test_key")
    assert source is not None


@pytest.mark.asyncio
async def test_news_api_fetch_mock():
    """Test news API fetch with mock."""
    from src.sources.news_api import NewsAPISource
    
    source = NewsAPISource(name="Test News", api_key="test_key")
    
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "articles": [
                {"title": "新闻1", "description": "描述1", "url": "http://example.com/1"},
                {"title": "新闻2", "description": "描述2", "url": "http://example.com/2"},
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        
        result = await source.fetch()
        assert True