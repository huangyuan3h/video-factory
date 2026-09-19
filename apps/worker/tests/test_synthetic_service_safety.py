"""Safety-focused tests for ComfyUI synthetic generation.

These tests lock in the guards that prevent ComfyUI from freezing the host:
synthetic must be opt-in and must refuse to run on low memory.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import settings
from src.services import synthetic_service as ss


class _FakeResponse:
    def __init__(self, json_data=None, content=b"", status_code=200):
        self._json = json_data or {}
        self.content = content
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    """Minimal async httpx.AsyncClient stand-in."""

    def __init__(self, *args, **kwargs):
        self.pages = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None):
        return _FakeResponse({"prompt_id": "pid-1"})

    async def get(self, url, params=None, timeout=None):
        if "/history/" in url:
            return _FakeResponse(
                {
                    "pid-1": {
                        "status": {"completed": True},
                        "outputs": {
                            "9": {
                                "images": [
                                    {"filename": "out.png", "subfolder": "", "type": "output"}
                                ]
                            }
                        },
                    }
                }
            )
        if "/view" in url:
            return _FakeResponse(content=b"PNGDATA")
        return _FakeResponse({})


def test_disabled_by_default(monkeypatch):
    monkeypatch.setattr(settings, "enable_synthetic", False)
    assert ss.is_enabled() is False
    assert ss.is_available() is False


@pytest.mark.asyncio
async def test_generate_returns_none_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "enable_synthetic", False)
    assert await ss.generate_image("cat") is None
    assert await ss.generate_images(["cat", "dog"]) == []


def test_clamp_dim():
    assert ss._clamp_dim(1920, 1080) == (1024, 768)  # MAX_HEIGHT raised for portrait
    assert ss._clamp_dim(100, 100) == (256, 256)
    # even dimensions, multiples of 8
    w, h = ss._clamp_dim(1000, 500)
    assert w % 8 == 0 and h % 8 == 0


def test_workflow_structure():
    wf = ss._sd35_workflow("a cat", 1024, 576, seed=42)
    assert wf["3"]["class_type"] == "KSampler"
    assert wf["4"]["inputs"]["ckpt_name"].endswith(".safetensors")
    assert wf["3"]["inputs"]["seed"] == 42
    assert wf["5"]["inputs"]["width"] == 1024
    assert wf["9"]["class_type"] == "SaveImage"


def test_system_free_gb_uses_psutil(monkeypatch):
    fake = MagicMock()
    fake.virtual_memory.return_value.available = 8 * (1024 ** 3)
    with patch.dict("sys.modules", {"psutil": fake}):
        assert ss._system_free_gb() == pytest.approx(8.0, abs=0.1)


@pytest.mark.asyncio
async def test_generate_low_memory_skips(monkeypatch):
    monkeypatch.setattr(settings, "enable_synthetic", True)
    monkeypatch.setattr(ss, "_system_free_gb", lambda: 1.0)
    monkeypatch.setattr(ss, "_min_free_gb", lambda: 12.0)
    assert await ss.generate_image("cat") is None


@pytest.mark.asyncio
async def test_generate_breaker_tripped(monkeypatch):
    monkeypatch.setattr(settings, "enable_synthetic", True)
    monkeypatch.setattr(ss, "_breaker_tripped", True, raising=False)
    try:
        assert await ss.generate_image("cat") is None
    finally:
        monkeypatch.setattr(ss, "_breaker_tripped", False, raising=False)


@pytest.mark.asyncio
async def test_generate_success(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "enable_synthetic", True)
    monkeypatch.setattr(ss, "_system_free_gb", lambda: 100.0)
    monkeypatch.setattr(ss.tempfile, "mkdtemp", lambda: str(tmp_path))
    with patch.object(ss.httpx, "AsyncClient", _FakeClient), patch(
        "asyncio.sleep", new_callable=AsyncMock
    ):
        result = await ss.generate_image("a nice cat", 1024, 576)
    assert result is not None
    assert result.exists()
    assert result.read_bytes() == b"PNGDATA"


@pytest.mark.asyncio
async def test_generate_images_capped(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "enable_synthetic", True)
    monkeypatch.setattr(ss, "_max_images", lambda: 1)
    monkeypatch.setattr(ss, "_system_free_gb", lambda: 100.0)
    monkeypatch.setattr(ss.tempfile, "mkdtemp", lambda: str(tmp_path))
    with patch.object(ss.httpx, "AsyncClient", _FakeClient), patch(
        "asyncio.sleep", new_callable=AsyncMock
    ):
        results = await ss.generate_images(["a", "b", "c"], 1024, 576)
    assert len(results) == 1


@pytest.mark.asyncio
async def test_is_available_enabled(monkeypatch):
    monkeypatch.setattr(settings, "enable_synthetic", True)
    with patch.object(ss.httpx, "get", return_value=_FakeResponse({}, status_code=200)):
        assert ss.is_available() is True
    with patch.object(ss.httpx, "get", side_effect=RuntimeError("nope")):
        assert ss.is_available() is False
