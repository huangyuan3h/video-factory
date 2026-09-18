"""Tests for material source normalization and fetching."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.services.material.material_fetcher import MaterialFetcher, normalize_sources


def test_normalize_sources_aliases():
    assert normalize_sources("pexels") == {"online"}
    assert normalize_sources("pixabay") == {"online"}
    assert normalize_sources("online") == {"online"}
    assert normalize_sources("local") == {"local"}
    assert normalize_sources("synthetic") == {"synthetic"}
    assert normalize_sources("synthetic_video") == {"synthetic_video"}
    assert normalize_sources("animation") == {"synthetic_video"}


def test_normalize_sources_both_and_unknown():
    assert normalize_sources("both") == {"online", "local", "synthetic"}
    assert normalize_sources("all") == {"online", "local", "synthetic"}
    assert normalize_sources("nonsense") == {"online", "local", "synthetic"}
    assert normalize_sources(None) == {"online", "local", "synthetic"}


def test_normalize_sources_composite():
    assert normalize_sources("pexels,local") == {"online", "local"}
    assert normalize_sources(["pixabay", "synthetic"]) == {"online", "synthetic"}
    assert normalize_sources("") == {"online", "local", "synthetic"}


@pytest.mark.asyncio
async def test_fetch_videos_pexels_maps_to_online():
    fetcher = MaterialFetcher()
    with patch.object(
        fetcher.pexels, "fetch_videos", new_callable=AsyncMock, return_value=[Path("/tmp/a.mp4")]
    ) as mock_pexels:
        result = await fetcher.fetch_videos(["nature"], count=1, source="pexels")
    mock_pexels.assert_awaited_once()
    assert result == [Path("/tmp/a.mp4")]


@pytest.mark.asyncio
async def test_fetch_images_pixabay_maps_to_online():
    fetcher = MaterialFetcher()
    with patch.object(
        fetcher.pexels, "fetch_images", new_callable=AsyncMock, return_value=[]
    ), patch.object(
        fetcher.pixabay, "fetch_images", new_callable=AsyncMock, return_value=[Path("/tmp/b.jpg")]
    ) as mock_pixabay:
        result = await fetcher.fetch_images(["nature"], count=1, source="pixabay")
    mock_pixabay.assert_awaited_once()
    assert result == [Path("/tmp/b.jpg")]


@pytest.mark.asyncio
async def test_fetch_videos_local_only():
    fetcher = MaterialFetcher()
    with patch.object(
        fetcher.local, "fetch_videos", new_callable=AsyncMock, return_value=[Path("/tmp/l.mp4")]
    ) as mock_local, patch.object(
        fetcher.pexels, "fetch_videos", new_callable=AsyncMock, return_value=[Path("/tmp/x.mp4")]
    ) as mock_pexels:
        result = await fetcher.fetch_videos(["nature"], count=1, source="local")
    mock_local.assert_awaited_once()
    mock_pexels.assert_not_awaited()
    assert result == [Path("/tmp/l.mp4")]


@pytest.mark.asyncio
async def test_fetch_videos_synthetic_fallback():
    fetcher = MaterialFetcher()
    with patch(
        "src.services.material.material_fetcher.synthetic_generate",
        new_callable=AsyncMock,
        return_value=[Path("/tmp/synth.png")],
    ) as mock_synth, patch(
        "src.services.material.material_fetcher.synthetic_available", return_value=True
    ):
        result = await fetcher.fetch_videos(["nature"], count=1, source="synthetic")
    mock_synth.assert_awaited_once()
    assert result == [Path("/tmp/synth.png")]


@pytest.mark.asyncio
async def test_fetch_images_synthetic_fallback():
    fetcher = MaterialFetcher()
    with patch(
        "src.services.material.material_fetcher.synthetic_generate",
        new_callable=AsyncMock,
        return_value=[Path("/tmp/synth.png")],
    ), patch("src.services.material.material_fetcher.synthetic_available", return_value=True):
        result = await fetcher.fetch_images(["nature"], count=1, source="synthetic")
    assert result == [Path("/tmp/synth.png")]


@pytest.mark.asyncio
async def test_fetch_videos_synthetic_animation():
    fetcher = MaterialFetcher()
    with patch(
        "src.services.material.material_fetcher.synthetic_video_generate",
        new_callable=AsyncMock,
        return_value=[Path("/tmp/clip.webm")],
    ) as mock_clip, patch(
        "src.services.material.material_fetcher.synthetic_video_available", return_value=True
    ):
        result = await fetcher.fetch_videos(["nature"], count=1, source="synthetic_video")
    mock_clip.assert_awaited_once()
    assert result == [Path("/tmp/clip.webm")]
