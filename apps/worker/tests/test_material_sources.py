"""Tests for material source normalization and fetching."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.services.material.material_fetcher import (
    FALLBACK_KEYWORDS,
    MaterialFetcher,
    derive_search_terms,
    normalize_sources,
)


def test_normalize_sources_aliases():
    assert normalize_sources("pexels") == {"online"}
    assert normalize_sources("pixabay") == {"online"}
    assert normalize_sources("online") == {"online"}
    assert normalize_sources("local") == {"local"}
    assert normalize_sources("synthetic") == {"synthetic"}
    assert normalize_sources("synthetic_video") == {"synthetic_video"}
    assert normalize_sources("animation") == {"synthetic_video"}


def test_normalize_sources_both_and_unknown():
    # Synthetic is paused by default: "both"/"all"/unknown resolve to real stock.
    assert normalize_sources("both") == {"online", "local"}
    assert normalize_sources("all") == {"online", "local"}
    assert normalize_sources("nonsense") == {"online", "local"}
    assert normalize_sources(None) == {"online", "local"}


def test_normalize_sources_composite():
    assert normalize_sources("pexels,local") == {"online", "local"}
    assert normalize_sources(["pixabay", "synthetic"]) == {"online", "synthetic"}
    assert normalize_sources("") == {"online", "local"}
    # Explicit synthetic opt-in combined with a default alias is honored.
    assert normalize_sources("both,synthetic") == {"online", "local", "synthetic"}


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


def test_fallback_keywords_are_news_safe():
    joined = " ".join(FALLBACK_KEYWORDS).lower()
    for off_topic in ("food", "cooking", "nutrition", "vegetable", "fruit", "fitness"):
        assert off_topic not in joined
    assert "stock market" in FALLBACK_KEYWORDS


def test_derive_search_terms_maps_and_extracts_latin():
    terms = derive_search_terms(["美联储", "APAC market", "未翻译的中文词"])
    assert "federal reserve" in terms
    # latin tokens embedded in a keyword are kept (lowered) for search.
    assert "apac market" in terms
    # CJK-only term with no mapping is dropped, not passed through.
    assert "未翻译的中文词" not in terms


@pytest.mark.asyncio
async def test_online_source_never_calls_synthetic():
    fetcher = MaterialFetcher()
    with patch(
        "src.services.material.material_fetcher.synthetic_generate",
        new_callable=AsyncMock,
        return_value=[Path("/tmp/synth.png")],
    ) as mock_synth, patch(
        "src.services.material.material_fetcher.synthetic_available", return_value=True
    ):
        result = await fetcher.fetch_videos(["股票"], count=1, source="pexels")
    mock_synth.assert_not_awaited()
    assert result == []
