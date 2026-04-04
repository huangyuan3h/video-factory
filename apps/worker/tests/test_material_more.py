"""More tests for material fetcher."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_fetch_from_pixabay():
    """Test fetching from Pixabay."""
    from src.services.material import MaterialFetcher
    
    fetcher = MaterialFetcher(pixabay_api_key="test_key")
    
    result = await fetcher.fetch_images(["test"])
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_fetch_images():
    """Test fetching images."""
    from src.services.material import MaterialFetcher
    
    fetcher = MaterialFetcher(pexels_api_key="test_key")
    
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "photos": [
                {
                    "id": 1,
                    "src": {
                        "large": "http://example.com/image.jpg"
                    }
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        
        result = await fetcher.fetch_images(["test"])
        assert isinstance(result, list)


def test_material_fetcher_with_keys():
    """Test material fetcher with API keys."""
    from src.services.material import MaterialFetcher
    
    fetcher = MaterialFetcher(
        pexels_api_key="pexels_key",
        pixabay_api_key="pixabay_key"
    )
    
    assert fetcher is not None
    assert fetcher.pexels.api_key == "pexels_key"
    assert fetcher.pixabay.api_key == "pixabay_key"