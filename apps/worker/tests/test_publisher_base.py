"""Tests for the BasePublisher helpers using a fake Playwright."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.publishers.base import BasePublisher, PublishResult


class _El:
    def __init__(self):
        self.files = None

    async def set_input_files(self, path):
        self.files = path


class _FakePage:
    def __init__(self):
        self.url = "about:blank"
        self.goto_calls = []
        self.clicks = []

    async def goto(self, url):
        self.url = url
        self.goto_calls.append(url)

    async def query_selector(self, selector):
        return _El()

    async def wait_for_selector(self, selector, timeout=0):
        return _El()

    async def click(self, selector):
        self.clicks.append(selector)

    async def fill(self, selector, text):
        return None


class _FakeContext:
    def __init__(self):
        self.added = None

    async def add_cookies(self, cookies):
        self.added = cookies

    async def cookies(self):
        return [{"name": "n", "value": "v"}]

    async def new_page(self):
        return _FakePage()


class _FakeBrowser:
    def __init__(self):
        self.closed = False

    async def new_context(self, **kwargs):
        return _FakeContext()

    async def close(self):
        self.closed = True


class _FakeChromium:
    async def launch(self, **kwargs):
        return _FakeBrowser()


class _FakePW:
    chromium = _FakeChromium()


class _FakePWMgr:
    async def start(self):
        return _FakePW()


class DummyPublisher(BasePublisher):
    @property
    def platform_name(self):
        return "Dummy"

    @property
    def login_url(self):
        return "http://dummy/login"

    @property
    def upload_url(self):
        return "http://dummy/upload"

    async def check_login(self):
        return self._logged_in

    async def upload(self, video_path, title, description=None, tags=None, **kwargs):
        return PublishResult(success=True, platform=self.platform_name)


@pytest.fixture(autouse=True)
def patch_playwright():
    with patch("src.publishers.base.async_playwright", return_value=_FakePWMgr()):
        yield


@pytest.mark.asyncio
async def test_init_browser_and_save_cookies():
    pub = DummyPublisher()
    await pub.init_browser()
    assert pub.browser is not None
    cookies = await pub.save_cookies()
    assert json.loads(cookies)[0]["name"] == "n"
    await pub.close_browser()
    assert pub.browser is None


@pytest.mark.asyncio
async def test_init_browser_with_cookies():
    pub = DummyPublisher(cookies=json.dumps([{"name": "a", "value": "b"}]))
    await pub.init_browser()
    assert pub.context.added == [{"name": "a", "value": "b"}]
    await pub.close_browser()


@pytest.mark.asyncio
async def test_load_cookies_invalid(caplog):
    pub = DummyPublisher(cookies="not-json")
    await pub.init_browser()
    assert pub.browser is not None
    await pub.close_browser()


@pytest.mark.asyncio
async def test_helpers():
    pub = DummyPublisher()
    await pub.init_browser()
    await pub.wait_for_selector("div")
    await pub.click("button")
    await pub.fill("input", "text")
    await pub.upload_file("input[type=file]", Path("/tmp/v.mp4"))
    assert pub.page.clicks == ["button"]
    await pub.close_browser()


@pytest.mark.asyncio
async def test_login_success():
    pub = DummyPublisher()
    pub._logged_in = True
    with patch("src.publishers.base.asyncio.sleep", new_callable=AsyncMock):
        assert await pub.login(timeout=5) is True
    await pub.close_browser()


@pytest.mark.asyncio
async def test_login_timeout():
    pub = DummyPublisher()
    pub._logged_in = False
    with patch("src.publishers.base.asyncio.sleep", new_callable=AsyncMock):
        assert await pub.login(timeout=0) is False
    await pub.close_browser()


@pytest.mark.asyncio
async def test_upload_file_helper():
    pub = DummyPublisher()
    await pub.init_browser()
    await pub.upload_file("input", Path("/tmp/x.mp4"))
    await pub.close_browser()
