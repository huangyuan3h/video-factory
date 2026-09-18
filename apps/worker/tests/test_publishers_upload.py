"""Tests for Douyin / Xiaohongshu Playwright upload flows using a fake page."""

from unittest.mock import AsyncMock, patch

import pytest

from src.publishers.douyin import DouyinPublisher
from src.publishers.xiaohongshu import XiaohongshuPublisher


class _FakeElement:
    def __init__(self):
        self.filled = []
        self.clicked = 0

    async def fill(self, text):
        self.filled.append(text)

    async def click(self):
        self.clicked += 1

    async def get_attribute(self, name):
        return "https://example.com/post/1"

    async def query_selector(self, selector):
        return _FakeElement()

    async def set_input_files(self, path):
        return None


class _FakePage:
    def __init__(self):
        self.url = "https://creator.example.com/"
        self.goto_calls = []

    async def goto(self, url):
        self.url = url
        self.goto_calls.append(url)

    async def query_selector(self, selector):
        low = selector.lower()
        if "progress" in low or "uploading" in low:
            return None
        return _FakeElement()

    async def wait_for_selector(self, selector, timeout=0):
        return _FakeElement()


@pytest.mark.asyncio
async def test_douyin_upload_success(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"data")
    pub = DouyinPublisher()
    pub.page = _FakePage()
    with patch.object(pub, "init_browser", new_callable=AsyncMock), patch.object(
        pub, "check_login", new_callable=AsyncMock, return_value=True
    ), patch("src.publishers.douyin.asyncio.sleep", new_callable=AsyncMock):
        result = await pub.upload(video, "Title", description="desc", tags=["a"])
    assert result.success is True
    assert result.platform == "Douyin"


@pytest.mark.asyncio
async def test_douyin_upload_not_logged_in(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"data")
    pub = DouyinPublisher()
    pub.page = _FakePage()
    with patch.object(pub, "init_browser", new_callable=AsyncMock), patch.object(
        pub, "check_login", new_callable=AsyncMock, return_value=False
    ):
        result = await pub.upload(video, "Title")
    assert result.success is False
    assert "login" in (result.error or "").lower()


def test_douyin_list_folders_and_props():
    pub = DouyinPublisher()
    assert pub.supports_folder() is True
    assert pub.platform_name == "Douyin"
    import asyncio

    assert asyncio.run(pub.list_folders())


@pytest.mark.asyncio
async def test_xiaohongshu_upload_success(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"data")
    pub = XiaohongshuPublisher()
    pub.page = _FakePage()
    with patch.object(pub, "init_browser", new_callable=AsyncMock), patch.object(
        pub, "check_login", new_callable=AsyncMock, return_value=True
    ), patch("src.publishers.xiaohongshu.asyncio.sleep", new_callable=AsyncMock):
        result = await pub.upload(video, "Title", description="desc", tags=["a"])
    assert result.success is True
    assert result.platform == "Xiaohongshu"


@pytest.mark.asyncio
async def test_xiaohongshu_upload_not_logged_in(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"data")
    pub = XiaohongshuPublisher()
    pub.page = _FakePage()
    with patch.object(pub, "init_browser", new_callable=AsyncMock), patch.object(
        pub, "check_login", new_callable=AsyncMock, return_value=False
    ):
        result = await pub.upload(video, "Title")
    assert result.success is False


def test_xiaohongshu_props():
    pub = XiaohongshuPublisher()
    assert pub.supports_folder() is True
    assert pub.platform_name == "Xiaohongshu"
