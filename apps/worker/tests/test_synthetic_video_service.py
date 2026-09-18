"""Tests for ComfyUI synthetic video/animation service."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.config import settings
from src.services import synthetic_video_service as sv


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
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None, files=None):
        if url.endswith("/upload/image"):
            return _FakeResponse({"name": "input.png", "subfolder": ""})
        return _FakeResponse({"prompt_id": "pidv"})

    async def get(self, url, params=None, timeout=None):
        if "/history/" in url:
            return _FakeResponse(
                {
                    "pidv": {
                        "status": {"completed": True},
                        "outputs": {
                            "10": {
                                "gifs": [
                                    {"filename": "out.webm", "subfolder": "", "type": "output"}
                                ]
                            }
                        },
                    }
                }
            )
        if "/view" in url:
            return _FakeResponse(content=b"WEBMDATA")
        return _FakeResponse({})


def test_disabled_by_default(monkeypatch):
    monkeypatch.setattr(settings, "enable_synthetic_video", False)
    assert sv.is_enabled() is False
    assert sv.is_available() is False


@pytest.mark.asyncio
async def test_generate_none_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "enable_synthetic_video", False)
    assert await sv.generate_video_clip("cat") is None
    assert await sv.generate_video_clips(["cat", "dog"]) == []


def test_clamp_dims_multiples_of_32():
    w, h = sv._clamp_dim(1000, 500)
    assert w % 32 == 0 and h % 32 == 0
    assert sv._clamp_dim(5000, 5000) == (1280, 1280)
    assert sv._clamp_dim(10, 10) == (256, 256)


def test_builtin_workflow_has_placeholders_filled():
    wf = sv._default_ltx_t2v("a cat", "", 768, 512, 97, 42, 25.0)
    assert wf["3"]["class_type"] == "KSampler"
    assert wf["4"]["inputs"]["ckpt_name"].endswith(".safetensors")
    assert wf["5"]["inputs"]["width"] == 768
    assert wf["5"]["inputs"]["length"] == 97
    assert wf["6"]["inputs"]["text"] == "a cat"
    assert wf["10"]["class_type"] == "SaveWEBM"


def test_substitute_keeps_scalar_types():
    mapping = {"{{width}}": 768, "{{prompt}}": "hi", "{{seed}}": 7}
    out = sv._substitute({"a": "{{width}}", "b": "x {{prompt}} y", "c": [{"d": "{{seed}}"}]}, mapping)
    assert out["a"] == 768
    assert out["b"] == "x hi y"
    assert out["c"][0]["d"] == 7


def test_load_workflow_from_template(monkeypatch, tmp_path):
    template = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "{{image}}"}},
        "2": {"class_type": "KSampler", "inputs": {"seed": "{{seed}}", "steps": 8}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{prompt}}"}},
    }
    path = tmp_path / "wf.json"
    path.write_text(json.dumps(template), encoding="utf-8")
    monkeypatch.setattr(settings, "synthetic_video_workflow", str(path))
    wf = sv.load_workflow("hello", "", 640, 384, 49, 123, 25.0, "uploaded.png")
    assert wf["1"]["inputs"]["image"] == "uploaded.png"
    assert wf["2"]["inputs"]["seed"] == 123
    assert wf["3"]["inputs"]["text"] == "hello"


def test_load_workflow_bad_template_falls_back(monkeypatch, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(settings, "synthetic_video_workflow", str(bad))
    wf = sv.load_workflow("hi", "", 640, 384, 49, 1, 25.0, None)
    assert "10" in wf  # built-in


@pytest.mark.asyncio
async def test_generate_success(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "enable_synthetic_video", True)
    monkeypatch.setattr(sv, "_system_free_gb", lambda: 100.0)
    with patch.object(sv.httpx, "AsyncClient", _FakeClient), patch(
        "asyncio.sleep", new_callable=AsyncMock
    ), patch.object(sv.tempfile, "mkdtemp", lambda: str(tmp_path)):
        result = await sv.generate_video_clip("a dog running", width=768, height=512)
    assert result is not None
    assert result.exists()
    assert result.read_bytes() == b"WEBMDATA"


@pytest.mark.asyncio
async def test_generate_low_memory(monkeypatch):
    monkeypatch.setattr(settings, "enable_synthetic_video", True)
    monkeypatch.setattr(sv, "_system_free_gb", lambda: 1.0)
    monkeypatch.setattr(sv, "_min_free_gb", lambda: 16.0)
    assert await sv.generate_video_clip("cat") is None


@pytest.mark.asyncio
async def test_generate_breaker(monkeypatch):
    monkeypatch.setattr(settings, "enable_synthetic_video", True)
    monkeypatch.setattr(sv, "_breaker_tripped", True, raising=False)
    try:
        assert await sv.generate_video_clip("cat") is None
    finally:
        monkeypatch.setattr(sv, "_breaker_tripped", False, raising=False)


@pytest.mark.asyncio
async def test_generate_clips_capped(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "enable_synthetic_video", True)
    monkeypatch.setattr(sv, "_max_clips", lambda: 1)
    monkeypatch.setattr(sv, "_system_free_gb", lambda: 100.0)
    with patch.object(sv.httpx, "AsyncClient", _FakeClient), patch(
        "asyncio.sleep", new_callable=AsyncMock
    ), patch.object(sv.tempfile, "mkdtemp", lambda: str(tmp_path)):
        results = await sv.generate_video_clips(["a", "b", "c"], 768, 512)
    assert len(results) == 1


@pytest.mark.asyncio
async def test_upload_image(monkeypatch, tmp_path):
    img = tmp_path / "frame.png"
    img.write_bytes(b"PNGDATA")
    client = _FakeClient()
    name = await sv._upload_image(client, img)
    assert name == "input.png"


@pytest.mark.asyncio
async def test_is_available(monkeypatch):
    monkeypatch.setattr(settings, "enable_synthetic_video", True)
    with patch.object(sv.httpx, "get", return_value=_FakeResponse({}, status_code=200)):
        assert sv.is_available() is True
    with patch.object(sv.httpx, "get", side_effect=RuntimeError("no")):
        assert sv.is_available() is False
