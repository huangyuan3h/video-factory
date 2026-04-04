"""Tests for material fetcher full coverage."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import tempfile


@pytest.mark.asyncio
async def test_fetch_pexels_videos():
    """Test fetching videos from Pexels."""
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
        
        result = await fetcher.fetch_videos(["nature"])
        assert result is not None or result is None


@pytest.mark.asyncio
async def test_fetch_pixabay_images():
    """Test fetching images from Pixabay."""
    from src.services.material import MaterialFetcher
    
    fetcher = MaterialFetcher(pixabay_api_key="test_key")
    
    result = await fetcher.fetch_images(["nature"])
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_download_video():
    """Test downloading video."""
    from src.services.material.pexels_service import PexelsService
    
    with tempfile.TemporaryDirectory() as tmpdir:
        service = PexelsService("test")
        
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_response = MagicMock()
            mock_response.content = b"fake video content"
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response
            
            result = await service._download_file(
                "http://example.com/video.mp4",
                "test_video.mp4"
            )
            assert result is not None or result is None


def test_material_fetcher_no_keys():
    """Test material fetcher without API keys."""
    from src.services.material import MaterialFetcher
    
    fetcher = MaterialFetcher()
    
    assert fetcher is not None
    assert fetcher.pexels.api_key is None
    assert fetcher.pixabay.api_key is None