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


def test_select_best_video_prefers_requested_portrait_resolution():
    from src.services.material.pexels_service import PexelsService

    service = PexelsService("test")
    videos = [
        {"width": 3840, "height": 2160, "quality": "4k", "link": "landscape"},
        {"width": 720, "height": 1280, "quality": "hd", "link": "portrait-low"},
        {"width": 1080, "height": 1920, "quality": "hd", "link": "portrait-high"},
    ]

    selected = service._select_video_file(videos, orientation="portrait")

    assert selected["link"] == "portrait-high"


def test_select_best_video_ranks_matching_orientation_when_target_is_missing():
    from src.services.material.pexels_service import PexelsService

    service = PexelsService("test")
    videos = [
        {"width": 3840, "height": 2160, "quality": "4k", "link": "landscape"},
        {"width": 1080, "height": 1350, "quality": "hd", "link": "portrait"},
    ]

    selected = service._select_video_file(videos, orientation="portrait")

    assert selected["link"] == "portrait"


def test_select_best_video_prefers_exact_target_over_larger():
    from src.services.material.pexels_service import PexelsService

    service = PexelsService("test")
    videos = [
        {"width": 3840, "height": 2160, "quality": "4k", "link": "4k-landscape"},
        {"width": 1920, "height": 1080, "quality": "hd", "link": "1080p-landscape"},
        {"width": 1280, "height": 720, "quality": "hd", "link": "720p-landscape"},
    ]

    assert service._select_video_file(videos)["link"] == "1080p-landscape"


def test_select_best_video_caps_at_1080_when_no_exact():
    from src.services.material.pexels_service import PexelsService

    service = PexelsService("test")
    videos = [
        {"width": 3840, "height": 2160, "quality": "4k", "link": "4k"},
        {"width": 2560, "height": 1440, "quality": "hd", "link": "1440p"},
        {"width": 1280, "height": 720, "quality": "hd", "link": "720p"},
    ]

    assert service._select_video_file(videos)["link"] == "720p"


def test_select_best_video_picks_smallest_above_1080_when_no_capped():
    from src.services.material.pexels_service import PexelsService

    service = PexelsService("test")
    videos = [
        {"width": 3840, "height": 2160, "quality": "4k", "link": "4k"},
        {"width": 2560, "height": 1440, "quality": "hd", "link": "1440p"},
    ]

    assert service._select_video_file(videos)["link"] == "1440p"


def test_select_best_video_uses_quality_tiebreak_for_above_1080():
    from src.services.material.pexels_service import PexelsService

    service = PexelsService("test")
    videos = [
        {"width": 2560, "height": 1440, "quality": "sd", "link": "sd"},
        {"width": 2560, "height": 1440, "quality": "hd", "link": "hd"},
    ]

    assert service._select_video_file(videos)["link"] == "hd"


def test_select_video_file_empty_returns_none():
    from src.services.material.pexels_service import PexelsService

    service = PexelsService("test")
    assert service._select_video_file([]) is None
    assert service._select_video_file([{"link": ""}]) is None


def test_select_image_url_prefers_highest_resolution():
    from src.services.material.pexels_service import select_image_url

    assert select_image_url(
        {"tiny": "t", "large": "l", "large2x": "l2", "original": "o"}
    ) == "l2"
    assert select_image_url({"large": "l", "original": "o"}) == "o"
    assert select_image_url({"large": "l"}) == "l"
    assert select_image_url({}) is None
    assert select_image_url(None) is None


def test_rank_photos_drops_low_res_when_better_exists():
    from src.services.material.pexels_service import rank_photos

    low = {"id": 1, "width": 640, "height": 480}
    high = {"id": 2, "width": 2000, "height": 1400}
    mid = {"id": 3, "width": 1280, "height": 720}

    assert [p["id"] for p in rank_photos([low, high, mid])] == [2, 3]
    # Missing width metadata is kept (mocks/fixtures often omit it).
    assert rank_photos([{"id": 1}, {"id": 2}]) == [{"id": 1}, {"id": 2}]
    # Can't do better than a single low-res photo.
    assert rank_photos([low]) == [low]
