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


@pytest.mark.asyncio
async def test_pexels_fetch_images_prefers_large2x_and_skips_low_res():
    from pathlib import Path

    from src.services.material import MaterialFetcher

    fetcher = MaterialFetcher(pexels_api_key="k")
    payload = {
        "photos": [
            {
                "id": 1,
                "width": 640,
                "height": 480,
                "src": {"large2x": "http://x/low.jpg", "large": "http://x/low_l.jpg"},
            },
            {
                "id": 2,
                "width": 2400,
                "height": 1600,
                "src": {"large2x": "http://x/hi.jpg", "large": "http://x/hi_l.jpg"},
            },
        ]
    }
    downloaded = []

    async def fake_download(url, name):
        downloaded.append((url, name))
        return Path("/tmp") / name

    with patch("httpx.AsyncClient.get") as mock_get, patch.object(
        fetcher.pexels, "_download_file", new=fake_download
    ):
        mock_response = MagicMock()
        mock_response.json.return_value = payload
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = await fetcher.pexels.fetch_images(["japan"], count=2)

    # Low-res photo dropped; high-res uses the sharp large2x source.
    assert downloaded == [("http://x/hi.jpg", "pexels_2.jpg")]
    assert [p.name for p in result] == ["pexels_2.jpg"]


@pytest.mark.asyncio
async def test_pexels_fetch_images_skips_excluded_ids():
    """Already-used photo ids are skipped; the ranked list is walked further."""
    from pathlib import Path

    from src.services.material import MaterialFetcher

    fetcher = MaterialFetcher(pexels_api_key="k")
    payload = {
        "photos": [
            {"id": 1, "width": 2000, "height": 1000, "src": {"large2x": "http://x/1.jpg"}},
            {"id": 2, "width": 2000, "height": 1000, "src": {"large2x": "http://x/2.jpg"}},
            {"id": 3, "width": 2000, "height": 1000, "src": {"large2x": "http://x/3.jpg"}},
        ]
    }
    downloaded = []

    async def fake_download(url, name):
        downloaded.append((url, name))
        return Path("/tmp") / name

    exclude = {1}
    with patch("httpx.AsyncClient.get") as mock_get, patch.object(
        fetcher.pexels, "_download_file", new=fake_download
    ):
        mock_response = MagicMock()
        mock_response.json.return_value = payload
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = await fetcher.pexels.fetch_images(
            ["japan bubble"], count=5, exclude_ids=exclude
        )

    assert [p.name for p in result] == ["pexels_2.jpg", "pexels_3.jpg"]
    # The caller-owned set now remembers every id used in this task.
    assert exclude == {1, 2, 3}


@pytest.mark.asyncio
async def test_book_fetch_images_dedupes_across_calls():
    """A still used once is never handed out again within the same task."""
    from pathlib import Path

    from src.services.material import MaterialFetcher

    fetcher = MaterialFetcher(pexels_api_key="k")
    still = Path("/tmp/pexels_7.jpg")
    with patch.object(
        fetcher.pexels, "fetch_images", new_callable=AsyncMock, return_value=[still]
    ) as mock_pexels:
        first = await fetcher.fetch_book_images(["bubble economy"], count=1)
        second = await fetcher.fetch_book_images(["bubble economy"], count=1)

    assert first == [still]
    assert second == []
    assert mock_pexels.await_count == 2


@pytest.mark.asyncio
async def test_pexels_fetch_images_skips_literal_soap_bubble_alts():
    """Book path drops literal soap/foam photos when alternatives exist."""
    from pathlib import Path

    from src.services.material import MaterialFetcher

    fetcher = MaterialFetcher(pexels_api_key="k")
    payload = {
        "photos": [
            {
                "id": 1,
                "width": 2000,
                "height": 1000,
                "alt": "soap bubbles floating in water",
                "src": {"large2x": "http://x/bubbles.jpg"},
            },
            {
                "id": 2,
                "width": 2000,
                "height": 1000,
                "alt": "tokyo skyline at dusk",
                "src": {"large2x": "http://x/tokyo.jpg"},
            },
        ]
    }
    downloaded = []

    async def fake_download(url, name):
        downloaded.append((url, name))
        return Path("/tmp") / name

    with patch("httpx.AsyncClient.get") as mock_get, patch.object(
        fetcher.pexels, "_download_file", new=fake_download
    ):
        mock_response = MagicMock()
        mock_response.json.return_value = payload
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = await fetcher.pexels.fetch_images(
            ["japan real estate boom"], count=2, avoid_alt_terms=("bubble", "soap", "foam")
        )

    assert [p.name for p in result] == ["pexels_2.jpg"]
    assert downloaded == [("http://x/tokyo.jpg", "pexels_2.jpg")]
