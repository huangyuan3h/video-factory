"""Tests for material fetcher module."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


def test_material_fetcher_creation():
    """Test material fetcher can be created."""
    from src.services.material import MaterialFetcher
    
    fetcher = MaterialFetcher(pexels_api_key="test", pixabay_api_key="test")
    assert fetcher is not None


def test_material_fetcher_without_keys():
    """Test material fetcher without API keys."""
    from src.services.material import MaterialFetcher
    
    fetcher = MaterialFetcher()
    assert fetcher is not None


@pytest.mark.asyncio
async def test_fetch_pexels_mock():
    """Test fetching from Pexels with mock."""
    from src.services.material import MaterialFetcher
    
    fetcher = MaterialFetcher(pexels_api_key="test_key")
    
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "videos": [
                {
                    "id": 1,
                    "video_files": [
                        {"link": "http://example.com/video.mp4", "quality": "hd"}
                    ]
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        
        result = await fetcher.fetch_videos(["test"])
        assert True


def test_select_best_video():
    """Test video selection logic."""
    from src.services.material.pexels_service import PexelsService
    
    service = PexelsService("test")
    
    videos = [
        {"width": 1920, "height": 1080, "link": "url1"},
        {"width": 1280, "height": 720, "link": "url2"},
    ]
    
    selected = service._select_video_file(videos)
    assert selected is not None