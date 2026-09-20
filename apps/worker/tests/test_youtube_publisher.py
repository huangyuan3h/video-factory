"""Tests for the YouTube publisher and publisher registry."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.publishers import get_publisher, list_platforms
from src.publishers.base import PublishResult
from src.publishers.youtube import YoutubePublisher


def test_registry():
    platforms = list_platforms()
    assert "douyin" in platforms
    assert "youtube" in platforms
    assert "xhs" in platforms


def test_get_publisher_unknown():
    with pytest.raises(ValueError):
        get_publisher("myspace")


def test_get_publisher_known():
    pub = get_publisher("youtube", credentials=None)
    assert pub.platform_name == "YouTube"


def test_youtube_properties():
    pub = YoutubePublisher()
    assert pub.platform_name == "YouTube"
    assert pub.login_url.startswith("https://")
    assert pub.upload_url.startswith("https://")
    assert pub.supports_folder() is True


@pytest.mark.asyncio
async def test_check_login_variants():
    assert await YoutubePublisher(credentials=None).check_login() is False
    assert await YoutubePublisher(credentials=json.dumps({"refresh_token": "x"})).check_login() is True
    assert await YoutubePublisher(credentials="not-json").check_login() is False


@pytest.mark.asyncio
async def test_list_folders_without_credentials():
    folders = await YoutubePublisher().list_folders()
    assert folders == []


@pytest.mark.asyncio
async def test_create_folder_without_credentials():
    result = await YoutubePublisher().create_folder("My Playlist")
    assert result is None


@pytest.mark.asyncio
async def test_upload_fails_without_credentials(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"data")
    result = await YoutubePublisher().upload(video, "Title", description="d")
    assert isinstance(result, PublishResult)
    assert result.success is False
    assert result.platform == "YouTube"
    assert "凭据" in (result.error or "")


@pytest.mark.asyncio
async def test_list_folders_propagates_error_when_credentials_present():
    pub = YoutubePublisher(credentials=json.dumps({"refresh_token": "x"}))
    with patch.object(pub, "_list_playlists_real", new_callable=AsyncMock, side_effect=RuntimeError("no libs")):
        with pytest.raises(RuntimeError, match="no libs"):
            await pub.list_folders()
