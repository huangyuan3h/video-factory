"""Unit tests for local TTS client, streaming/wav helpers and tts-settings routes."""

from __future__ import annotations

import asyncio
import struct
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src import models  # noqa: F401  (register tables)
from src.config import settings
from src.core.tts import local_client as lc
from src.core.tts import streaming, wav
from src.core.tts.local_client import LocalTTSClient, LocalTTSError
from src.database import Base, get_session
from src.routes import tts_settings

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class _Resp:
    def __init__(
        self,
        status_code: int = 200,
        json_body=None,
        json_error: bool = False,
        headers: dict | None = None,
        content: bytes = b"",
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._json = json_body
        self._json_error = json_error
        self.headers = headers or {}
        self.content = content
        self.text = text

    def json(self):
        if self._json_error:
            raise ValueError("not json")
        return self._json


def _fake_http(*, get_resp=None, get_error=None, post_resp=None, post_error=None):
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(side_effect=get_error) if get_error else AsyncMock(return_value=get_resp)
    client.post = (
        AsyncMock(side_effect=post_error) if post_error else AsyncMock(return_value=post_resp)
    )
    return client


def _patch_http(fake):
    return patch("src.core.tts.local_client.httpx.AsyncClient", return_value=fake)


# --------------------------------------------------------------------------- #
# LocalTTSClient construction / urls
# --------------------------------------------------------------------------- #


def test_construction_defaults_and_urls():
    c = LocalTTSClient(base_url="http://localhost:8000/")
    assert c.base_url == "http://localhost:8000"
    assert c.speech_url == "http://localhost:8000/v1/audio/speech"
    assert c.models_url == "http://localhost:8000/v1/models"
    assert c.voices_url == "http://localhost:8000/v1/voices"
    assert c.health_url == "http://localhost:8000/health"
    assert c.api_key == "local"
    assert c.language == "Chinese"
    assert c.speed == 1.0


def test_construction_v1_base_urls_and_overrides():
    c = LocalTTSClient(
        base_url="http://localhost:9000/v1/",
        model="m",
        voice="v",
        sample_rate=8000,
        response_format="pcm",
        timeout_s=5,
        api_key="",
        language="",
        speed="1.5",
    )
    assert c.speech_url == "http://localhost:9000/v1/audio/speech"
    assert c.models_url == "http://localhost:9000/v1/models"
    assert c.voices_url == "http://localhost:9000/v1/voices"
    assert c.health_url == "http://localhost:9000/health"
    assert c.api_key == "local"
    assert c.language == "Chinese"
    assert c.speed == 1.5


# --------------------------------------------------------------------------- #
# LocalTTSClient.health
# --------------------------------------------------------------------------- #


async def test_health_ok():
    fake = _fake_http(get_resp=_Resp(200, json_body={"data": [{"id": "x"}]}))
    with _patch_http(fake):
        assert await LocalTTSClient(base_url="http://h").health() is True


async def test_health_non_200_and_bad_json_and_not_list():
    for resp in (_Resp(500, json_body={"data": []}), _Resp(200, json_error=True), _Resp(200, json_body={"data": "nope"})):
        fake = _fake_http(get_resp=resp)
        with _patch_http(fake):
            assert await LocalTTSClient(base_url="http://h").health() is False


async def test_health_http_error():
    fake = _fake_http(get_error=httpx.HTTPError("boom"))
    with _patch_http(fake):
        assert await LocalTTSClient(base_url="http://h").health() is False


# --------------------------------------------------------------------------- #
# LocalTTSClient.upstream_status
# --------------------------------------------------------------------------- #


async def test_upstream_status_ok():
    body = {"status": "ok", "backend": {"name": "spark"}, "device": {"type": "cuda"}}
    fake = _fake_http(get_resp=_Resp(200, json_body=body))
    with _patch_http(fake):
        out = await LocalTTSClient(base_url="http://h").upstream_status()
    assert out == {"status": "ok", "backend": {"name": "spark"}, "device": {"type": "cuda"}}


async def test_upstream_status_non_dict_backend_device():
    body = {"status": "ok", "backend": "x", "device": None}
    fake = _fake_http(get_resp=_Resp(200, json_body=body))
    with _patch_http(fake):
        out = await LocalTTSClient(base_url="http://h").upstream_status()
    assert out == {"status": "ok", "backend": {}, "device": {}}


async def test_upstream_status_failures():
    for resp in (_Resp(404, json_body={}), _Resp(200, json_error=True), _Resp(200, json_body=["x"])):
        fake = _fake_http(get_resp=resp)
        with _patch_http(fake):
            assert await LocalTTSClient(base_url="http://h").upstream_status() is None
    fake = _fake_http(get_error=httpx.HTTPError("boom"))
    with _patch_http(fake):
        assert await LocalTTSClient(base_url="http://h").upstream_status() is None


# --------------------------------------------------------------------------- #
# LocalTTSClient.list_voices
# --------------------------------------------------------------------------- #


async def test_list_voices_upstream_success():
    body = {
        "voices": [
            {"id": "a", "name": "A", "language": "English"},
            {"voice_id": "b"},
            {"name": "C"},
            "not-a-dict",
            {"id": "clone:zzz"},
            {"id": ""},
        ],
        "languages": ["English", "Chinese"],
    }
    fake = _fake_http(get_resp=_Resp(200, json_body=body))
    with _patch_http(fake):
        out = await LocalTTSClient(base_url="http://h").list_voices()
    assert out["source"] == "upstream"
    assert [v["id"] for v in out["voices"]] == ["a", "b", "C"]
    assert out["languages"] == ["English", "Chinese"]


async def test_list_voices_upstream_fallback_branches():
    for resp in (
        _Resp(500, json_body={}),
        _Resp(200, json_error=True),
    ):
        fake = _fake_http(get_resp=resp)
        with _patch_http(fake):
            out = await LocalTTSClient(base_url="http://h").list_voices()
        assert out["source"] == "builtin"
        assert out["voices"] == lc.BUILTIN_VOICES
        assert out["languages"] == lc.BUILTIN_LANGUAGES
    fake = _fake_http(get_error=httpx.HTTPError("boom"))
    with _patch_http(fake):
        out = await LocalTTSClient(base_url="http://h").list_voices()
    assert out["source"] == "builtin"


async def test_list_voices_empty_upstream_lists_fall_back_to_builtin_voices():
    for body in ({"data": []}, {"voices": []}):
        fake = _fake_http(get_resp=_Resp(200, json_body=body))
        with _patch_http(fake):
            out = await LocalTTSClient(base_url="http://h").list_voices()
        assert out["source"] == "upstream"
        assert out["voices"] == lc.BUILTIN_VOICES
        assert out["languages"] == lc.BUILTIN_LANGUAGES


async def test_list_voices_uses_data_key():
    body = {"data": [{"id": "d1"}]}
    fake = _fake_http(get_resp=_Resp(200, json_body=body))
    with _patch_http(fake):
        out = await LocalTTSClient(base_url="http://h").list_voices()
    assert out["voices"][0]["id"] == "d1"
    assert out["voices"][0]["language"] == "Auto"


# --------------------------------------------------------------------------- #
# LocalTTSClient.synthesize
# --------------------------------------------------------------------------- #


async def test_synthesize_empty_text_short_circuits():
    fake = _fake_http()
    with _patch_http(fake):
        out = await LocalTTSClient(base_url="http://h").synthesize("   ")
    assert out == (b"", "audio/wav")
    fake.post.assert_not_called()


async def test_synthesize_success_bytes_and_media_type():
    resp = _Resp(200, headers={"content-type": "audio/wav; charset=binary"}, content=b"RIFFdata")
    fake = _fake_http(post_resp=resp)
    with _patch_http(fake):
        data, media = await LocalTTSClient(base_url="http://h").synthesize("hi")
    assert data == b"RIFFdata"
    assert media == "audio/wav"
    payload = fake.post.call_args.kwargs["json"]
    assert payload["input"] == "hi"


async def test_synthesize_strips_lone_surrogates():
    resp = _Resp(200, headers={"content-type": "audio/wav"}, content=b"RIFF")
    fake = _fake_http(post_resp=resp)
    with _patch_http(fake):
        await LocalTTSClient(base_url="http://h").synthesize("a\ud800b")
    assert fake.post.call_args.kwargs["json"]["input"] == "ab"


async def test_synthesize_non_200_raises():
    resp = _Resp(500, text="upstream down")
    fake = _fake_http(post_resp=resp)
    with _patch_http(fake):
        with pytest.raises(LocalTTSError):
            await LocalTTSClient(base_url="http://h").synthesize("hi")


async def test_synthesize_request_exception_raises():
    fake = _fake_http(post_error=httpx.ConnectError("refused"))
    with _patch_http(fake):
        with pytest.raises(LocalTTSError):
            await LocalTTSClient(base_url="http://h").synthesize("hi")


async def test_synthesize_empty_audio_raises():
    resp = _Resp(200, headers={"content-type": "audio/wav"}, content=b"")
    fake = _fake_http(post_resp=resp)
    with _patch_http(fake):
        with pytest.raises(LocalTTSError):
            await LocalTTSClient(base_url="http://h").synthesize("hi")


async def test_synthesize_pcm_wrapped_to_wav():
    resp = _Resp(200, headers={"content-type": "audio/pcm"}, content=b"\x01\x02\x03\x04")
    fake = _fake_http(post_resp=resp)
    with _patch_http(fake):
        data, media = await LocalTTSClient(base_url="http://h").synthesize("hi")
    assert media == "audio/wav"
    assert data.startswith(b"RIFF")


async def test_synthesize_octet_stream_wrapped():
    resp = _Resp(200, headers={"content-type": "application/octet-stream"}, content=b"\xaa\xbb")
    fake = _fake_http(post_resp=resp)
    with _patch_http(fake):
        data, media = await LocalTTSClient(base_url="http://h").synthesize("hi")
    assert media == "audio/wav"
    assert data.startswith(b"RIFF")


async def test_synthesize_missing_content_type_detection():
    cases = [
        (b"RIFFxxxx", "audio/wav"),
        (b"ID3xxxx", "audio/mpeg"),
        (b"\xff\xfbxx", "audio/mpeg"),
        (b"\x00\x01\x02\x03", "application/octet-stream"),
    ]
    for content, expected in cases:
        resp = _Resp(200, headers={}, content=content)
        fake = _fake_http(post_resp=resp)
        with _patch_http(fake):
            data, media = await LocalTTSClient(base_url="http://h").synthesize("hi")
        assert media == expected


async def test_synthesize_speed_clamped_and_override():
    resp = _Resp(200, headers={"content-type": "audio/wav"}, content=b"RIFF")
    fake = _fake_http(post_resp=resp)
    c = LocalTTSClient(base_url="http://h", speed=10)
    with _patch_http(fake):
        await c.synthesize("hi")
    assert fake.post.call_args.kwargs["json"]["speed"] == 4.0
    with _patch_http(fake):
        await c.synthesize("hi", speed=0.1, voice="v2", language="English")
    payload = fake.post.call_args.kwargs["json"]
    assert payload["speed"] == 0.25
    assert payload["voice"] == "v2"
    assert payload["language"] == "English"


# --------------------------------------------------------------------------- #
# streaming
# --------------------------------------------------------------------------- #


def test_chunk_for_tts_empty_and_short():
    assert streaming.chunk_for_tts("") == []
    assert streaming.chunk_for_tts("   ") == []
    assert streaming.chunk_for_tts("hello") == ["hello"]


def test_chunk_for_tts_splits_on_sentence_boundaries():
    text = "山一。山二。山三。山四。"
    chunks = streaming.chunk_for_tts(text, max_chars=10)
    assert chunks == ["山一。山二。山三。", "山四。"]
    assert all(len(c) <= 10 for c in chunks)


def test_chunk_for_tts_hard_split_without_separators():
    chunks = streaming.chunk_for_tts("a" * 25, max_chars=10)
    assert chunks == ["a" * 10, "a" * 10, "a" * 5]
    assert all(len(c) <= 10 for c in chunks)


def test_chunk_for_tts_rejects_early_separator():
    text = "。 " + "b" * 25
    chunks = streaming.chunk_for_tts(text, max_chars=10)
    assert all(len(c) <= 10 for c in chunks)
    assert "".join(chunks).replace(" ", "").startswith("。")


def test_pad_silence_non_wav_appends_zero_bytes():
    n = int(0.001 * streaming.SAMPLE_RATE)
    out = streaming.pad_silence(b"abcd", seconds=0.001)
    assert out == b"abcd" + b"\x00\x00" * n


def test_pad_silence_valid_wav_updates_header():
    pcm = b"\x01\x00" * 10
    w = wav.pcm16_mono_to_wav(pcm, sample_rate=streaming.SAMPLE_RATE)
    n = int(0.001 * streaming.SAMPLE_RATE)
    out = streaming.pad_silence(w, seconds=0.001)
    assert len(out) == len(w) + n * 2
    assert int.from_bytes(out[4:8], "little") == len(out) - 8
    assert int.from_bytes(out[40:44], "little") == len(pcm) + n * 2


def test_pad_silence_inconsistent_wav_sizes_keeps_concat():
    w = bytearray(wav.pcm16_mono_to_wav(b"\x01\x00" * 10, sample_rate=streaming.SAMPLE_RATE))
    w[4:8] = (999).to_bytes(4, "little")
    w = bytes(w)
    n = int(0.001 * streaming.SAMPLE_RATE)
    out = streaming.pad_silence(w, seconds=0.001)
    assert out == w + b"\x00\x00" * n


def test_iter_stream_blocks_framing():
    w1 = b"AAAA"
    w2 = b"BBBB"
    blocks = list(streaming.iter_stream_blocks([w1, w2]))
    assert blocks[-1] == struct.pack(">I", 0)
    assert blocks[0] == struct.pack(">I", len(streaming.pad_silence(w1))) + streaming.pad_silence(w1)
    assert blocks[1] == struct.pack(">I", len(w2)) + w2


# --------------------------------------------------------------------------- #
# wav
# --------------------------------------------------------------------------- #


def test_pcm16_mono_to_wav_empty_and_header():
    assert wav.pcm16_mono_to_wav(b"") == b""
    pcm = b"\x10\x20" * 4
    blob = wav.pcm16_mono_to_wav(pcm, sample_rate=16000)
    assert blob[:4] == b"RIFF"
    assert blob[8:16] == b"WAVEfmt "
    fields = struct.unpack("<IHHIIHH", blob[16:36])
    fmt_size, audio_format, channels, rate, byte_rate, block_align, bits = fields
    assert fmt_size == 16
    assert audio_format == 1
    assert channels == 1
    assert rate == 16000
    assert byte_rate == 16000 * 2
    assert block_align == 2
    assert bits == 16
    assert blob[36:40] == b"data"
    assert int.from_bytes(blob[40:44], "little") == len(pcm)
    assert int.from_bytes(blob[4:8], "little") == 36 + len(pcm)
    assert blob[44:] == pcm


def test_wav_to_pcm16_mono_empty_and_non_wav():
    assert wav.wav_to_pcm16_mono(b"") == b""
    assert wav.wav_to_pcm16_mono(b"ID3mp3data") == b"ID3mp3data"
    assert wav.wav_to_pcm16_mono(b"RIFF") == b"RIFF"


def test_wav_to_pcm16_mono_round_trip():
    pcm = b"\x01\x02\x03\x04"
    blob = wav.pcm16_mono_to_wav(pcm, sample_rate=24000)
    assert wav.wav_to_pcm16_mono(blob) == pcm


def test_wav_to_pcm16_mono_skips_extra_chunks():
    pcm = b"\x09\x08\x07"
    fmt = struct.pack("<4sIHHIIHH", b"fmt ", 16, 1, 1, 16000, 32000, 2, 16)
    list_chunk = b"LIST" + struct.pack("<I", 4) + b"abcd"
    data_chunk = b"data" + struct.pack("<I", len(pcm)) + pcm
    blob = b"RIFF" + struct.pack("<I", 0) + b"WAVE" + fmt + list_chunk + data_chunk
    assert wav.wav_to_pcm16_mono(blob) == pcm


def test_wav_to_pcm16_mono_odd_chunk_padding():
    pcm = b"\x05\x06"
    fmt = struct.pack("<4sIHHIIHH", b"fmt ", 16, 1, 1, 16000, 32000, 2, 16)
    odd = b"LIST" + struct.pack("<I", 3) + b"abc" + b"\x00"
    data_chunk = b"data" + struct.pack("<I", len(pcm)) + pcm
    blob = b"RIFF" + struct.pack("<I", 0) + b"WAVE" + fmt + odd + data_chunk
    assert wav.wav_to_pcm16_mono(blob) == pcm


def test_wav_to_pcm16_mono_no_data_chunk():
    fmt = struct.pack("<4sIHHIIHH", b"fmt ", 16, 1, 1, 16000, 32000, 2, 16)
    blob = b"RIFF" + struct.pack("<I", 0) + b"WAVE" + fmt
    assert wav.wav_to_pcm16_mono(blob) == blob[44:]


# --------------------------------------------------------------------------- #
# tts_settings: DB fixture
# --------------------------------------------------------------------------- #


async def _prepare_db(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


@pytest.fixture
def api(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'tts.db'}")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    asyncio.run(_prepare_db(engine))

    app = FastAPI()
    app.include_router(tts_settings.router, prefix="/api/tts-settings")

    async def override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = override
    client = TestClient(app)
    yield client
    asyncio.run(engine.dispose())


class _FakeEdge:
    def __init__(self, voice=None, rate=None):
        self.voice = voice
        self.rate = rate

    async def synthesize(self, text, output_path=None, voice=None):
        Path(output_path).write_bytes(b"ID3fake")
        return Path(output_path)


class _FailingEdge:
    def __init__(self, voice=None, rate=None):
        pass

    async def synthesize(self, text, output_path=None, voice=None):
        raise RuntimeError("edge down")


# --------------------------------------------------------------------------- #
# tts_settings: GET / PUT
# --------------------------------------------------------------------------- #


def test_get_creates_default(api):
    resp = api.get("/api/tts-settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["voice"] == "zh-CN-XiaoxiaoNeural"
    assert body["data"]["is_default"] is True
    first_id = body["data"]["id"]

    resp2 = api.get("/api/tts-settings")
    assert resp2.json()["data"]["id"] == first_id


def test_put_updates_existing(api):
    created = api.get("/api/tts-settings").json()["data"]
    resp = api.put("/api/tts-settings", json={"voice": "v2", "rate": "+20%"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] == created["id"]
    assert data["voice"] == "v2"
    assert data["rate"] == "+20%"


def test_put_autocreates_when_missing(api):
    resp = api.put("/api/tts-settings", json={"test_text": "hi"})
    assert resp.status_code == 200
    assert resp.json()["data"]["test_text"] == "hi"


# --------------------------------------------------------------------------- #
# tts_settings: POST /test
# --------------------------------------------------------------------------- #


def test_test_route_local_success(api):
    fake = AsyncMock()
    fake.synthesize = AsyncMock(return_value=(b"RIFFaudio", "audio/wav"))
    with patch.object(tts_settings, "_local_client", return_value=fake):
        resp = api.post("/api/tts-settings/test", json={"test_text": "你好"})
    assert resp.status_code == 200
    assert resp.content == b"RIFFaudio"
    assert "wav" in resp.headers["content-type"]


def test_test_route_local_error_is_503(api):
    fake = AsyncMock()
    fake.synthesize = AsyncMock(side_effect=LocalTTSError("nope"))
    with patch.object(tts_settings, "_local_client", return_value=fake):
        resp = api.post("/api/tts-settings/test", json={"test_text": "你好"})
    assert resp.status_code == 503


def test_test_route_local_unexpected_is_500(api):
    fake = AsyncMock()
    fake.synthesize = AsyncMock(side_effect=RuntimeError("boom"))
    with patch.object(tts_settings, "_local_client", return_value=fake):
        resp = api.post("/api/tts-settings/test", json={"test_text": "你好"})
    assert resp.status_code == 500


def test_test_route_edge_success(api):
    with patch.object(tts_settings, "_local_client", return_value=None), patch.object(
        tts_settings, "EdgeTTSProvider", _FakeEdge
    ):
        resp = api.post("/api/tts-settings/test", json={"test_text": "hi", "voice": "v"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("audio/mpeg")


def test_test_route_edge_failure_is_500(api):
    with patch.object(tts_settings, "_local_client", return_value=None), patch.object(
        tts_settings, "EdgeTTSProvider", _FailingEdge
    ):
        resp = api.post("/api/tts-settings/test", json={"test_text": "hi"})
    assert resp.status_code == 500


# --------------------------------------------------------------------------- #
# tts_settings: GET /voices
# --------------------------------------------------------------------------- #


def test_voices_local_branch(api):
    fake = AsyncMock()
    fake.list_voices = AsyncMock(
        return_value={"voices": [{"id": "a", "name": "A"}], "languages": ["English"], "source": "upstream"}
    )
    with patch.object(tts_settings, "_local_client", return_value=fake):
        resp = api.get("/api/tts-settings/voices")
    assert resp.status_code == 200
    assert resp.json()["data"]["source"] == "upstream"


def test_voices_edge_branch(api):
    fake_provider = MagicMock()
    fake_provider.list_voices.return_value = {"zh-CN-XiaoxiaoNeural": "Xiaoxiao"}
    with patch.object(tts_settings, "_local_client", return_value=None), patch.object(
        tts_settings, "EdgeTTSProvider", fake_provider
    ):
        resp = api.get("/api/tts-settings/voices")
    assert resp.status_code == 200
    assert resp.json()["data"] == {"zh-CN-XiaoxiaoNeural": "Xiaoxiao"}


# --------------------------------------------------------------------------- #
# tts_settings: GET /status
# --------------------------------------------------------------------------- #


def test_status_no_local(api):
    with patch.object(tts_settings, "_local_client", return_value=None):
        resp = api.get("/api/tts-settings/status")
    body = resp.json()
    assert body["backend"] == "edge-tts"
    assert body["configured"] is False


def _fake_local(status=True):
    fake = MagicMock()
    fake.model = "spark-tts-0.5b"
    fake.voice = "spark:female"
    fake.language = "Chinese"
    fake.speed = 1.0
    fake.sample_rate = 16000
    fake.base_url = "http://hq:8000"
    fake.speech_url = "http://hq:8000/v1/audio/speech"
    fake.health = AsyncMock(return_value=status)
    fake.upstream_status = AsyncMock(
        return_value={
            "status": "ok",
            "backend": {"name": "spark", "model_id": "m1"},
            "device": {"type": "cuda"},
        }
    )
    return fake


def test_status_local_reachable(api):
    with patch.object(tts_settings, "_local_client", return_value=_fake_local(True)):
        resp = api.get("/api/tts-settings/status")
    body = resp.json()
    assert body["backend"] == "local"
    assert body["configured"] is True
    assert body["upstream_engine"] == "spark"
    assert body["upstream_model"] == "m1"
    assert body["upstream_device"] == "cuda"


def test_status_local_unreachable(api):
    fake = _fake_local(False)
    with patch.object(tts_settings, "_local_client", return_value=fake):
        resp = api.get("/api/tts-settings/status")
    body = resp.json()
    assert body["configured"] is False
    assert body["upstream_engine"] is None


# --------------------------------------------------------------------------- #
# tts_settings: POST /speak
# --------------------------------------------------------------------------- #


def test_speak_empty_text_400(api):
    resp = api.post("/api/tts-settings/speak", json={"text": " "})
    assert resp.status_code == 400


def test_speak_too_long_413(api):
    resp = api.post("/api/tts-settings/speak", json={"text": "a" * 1801})
    assert resp.status_code == 413


def test_speak_client_none_503(api):
    with patch.object(tts_settings, "_local_client", return_value=None):
        resp = api.post("/api/tts-settings/speak", json={"text": "hello"})
    assert resp.status_code == 503


def test_speak_success_headers(api):
    fake = AsyncMock()
    fake.speech_url = "http://h/v1/audio/speech"
    fake.synthesize = AsyncMock(return_value=(b"RIFFdata", "audio/wav"))
    with patch.object(tts_settings, "_local_client", return_value=fake):
        resp = api.post("/api/tts-settings/speak", json={"text": "hello", "voice": "spark:female"})
    assert resp.status_code == 200
    assert resp.content == b"RIFFdata"
    assert resp.headers["X-TTS-Backend"] == "local"
    assert resp.headers["X-TTS-Engine"] == "spark-hq"


def test_speak_local_error_503(api):
    fake = AsyncMock()
    fake.speech_url = "http://h/v1/audio/speech"
    fake.synthesize = AsyncMock(side_effect=LocalTTSError("down"))
    with patch.object(tts_settings, "_local_client", return_value=fake):
        resp = api.post("/api/tts-settings/speak", json={"text": "hello"})
    assert resp.status_code == 503


def test_speak_unexpected_error_502(api):
    fake = AsyncMock()
    fake.speech_url = "http://h/v1/audio/speech"
    fake.synthesize = AsyncMock(side_effect=RuntimeError("boom"))
    with patch.object(tts_settings, "_local_client", return_value=fake):
        resp = api.post("/api/tts-settings/speak", json={"text": "hello"})
    assert resp.status_code == 502


# --------------------------------------------------------------------------- #
# tts_settings: POST /speak-stream
# --------------------------------------------------------------------------- #


def test_speak_stream_empty_400(api):
    resp = api.post("/api/tts-settings/speak-stream", json={"text": " "})
    assert resp.status_code == 400


def test_speak_stream_client_none_503(api):
    with patch.object(tts_settings, "_local_client", return_value=None):
        resp = api.post("/api/tts-settings/speak-stream", json={"text": "hello"})
    assert resp.status_code == 503


def test_speak_stream_framed_blocks(api):
    fake = AsyncMock()
    fake.speech_url = "http://h/v1/audio/speech"
    fake.synthesize = AsyncMock(return_value=(b"ABCD", "audio/wav"))
    with patch.object(tts_settings, "_local_client", return_value=fake):
        resp = api.post("/api/tts-settings/speak-stream", json={"text": "你好"})
    assert resp.status_code == 200
    assert resp.headers["X-TTS-Backend"] == "local"
    content = resp.content
    assert content[:4] == struct.pack(">I", 4)
    assert content[4:8] == b"ABCD"
    assert content[8:] == struct.pack(">I", 0)


def test_speak_stream_chunk_error_skipped(api):
    fake = AsyncMock()
    fake.speech_url = "http://h/v1/audio/speech"
    fake.synthesize = AsyncMock(side_effect=LocalTTSError("down"))
    with patch.object(tts_settings, "_local_client", return_value=fake):
        resp = api.post("/api/tts-settings/speak-stream", json={"text": "你好"})
    assert resp.status_code == 200
    assert resp.content == struct.pack(">I", 0)


# --------------------------------------------------------------------------- #
# tts_settings: POST /voices/register
# --------------------------------------------------------------------------- #


def _register(api, *, voice_id="myvoice", transcript="hello", blob=b"wavbytes"):
    return api.post(
        "/api/tts-settings/voices/register",
        data={"voice_id": voice_id, "transcript": transcript},
        files={"file": ("ref.wav", blob, "audio/wav")},
    )


def test_register_invalid_voice_id(api):
    assert _register(api, voice_id="1Bad Id").status_code == 422


def test_register_empty_transcript(api):
    assert _register(api, transcript="   ").status_code == 422


def test_register_empty_file(api):
    assert _register(api, blob=b"").status_code == 422


def test_register_too_large(api):
    assert _register(api, blob=b"x" * (20 * 1024 * 1024 + 1)).status_code == 422


def test_register_success(api, tmp_path, monkeypatch):
    voice_dir = tmp_path / "voice"
    voices_file = tmp_path / "nested" / "spark-voices.json"
    monkeypatch.setattr(tts_settings, "_VOICE_DIR", voice_dir)
    monkeypatch.setattr(tts_settings, "_VOICES_FILE", voices_file)
    monkeypatch.setattr(tts_settings.shutil, "which", lambda _name: None)

    resp = _register(api, voice_id="MyVoice", transcript=" 转写文本 ")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "spark:myvoice"
    assert body["registered"] is True
    assert (voice_dir / "myvoice.wav").read_bytes() == b"wavbytes"
    import json as _json

    saved = _json.loads(voices_file.read_text())
    assert saved["myvoice"]["text"] == "转写文本"


async def test_spark_voices_fallback_and_mapping():
    failing = AsyncMock()
    failing.list_voices = AsyncMock(side_effect=RuntimeError("x"))
    out = await tts_settings._spark_voices(failing)
    assert out == tts_settings._SPARK_VOICES_FALLBACK

    empty = AsyncMock()
    empty.list_voices = AsyncMock(return_value={"voices": []})
    assert await tts_settings._spark_voices(empty) == tts_settings._SPARK_VOICES_FALLBACK

    good = AsyncMock()
    good.list_voices = AsyncMock(
        return_value={"voices": [{"id": "v1", "name": "V One"}, {"name": "no-id"}, "bad"]}
    )
    mapped = await tts_settings._spark_voices(good)
    assert mapped == [{"id": "v1", "name": "Spark · V One", "language": "Chinese"}]


# --------------------------------------------------------------------------- #
# tts_settings: _local_client / helpers / validators
# --------------------------------------------------------------------------- #


def test_local_client_hq_branch(monkeypatch):
    monkeypatch.setattr(settings, "vllm_tts_hq_url", "http://hq:8000")
    monkeypatch.setattr(settings, "vllm_tts_url", "http://unused:9000")
    c = tts_settings._local_client()
    assert isinstance(c, LocalTTSClient)
    assert c.base_url == "http://hq:8000"
    assert c.model == "spark-tts-0.5b"
    assert c.voice == "spark:female"


def test_local_client_url_branch(monkeypatch):
    monkeypatch.setattr(settings, "vllm_tts_hq_url", "")
    monkeypatch.setattr(settings, "vllm_tts_url", "http://local:9000")
    c = tts_settings._local_client()
    assert isinstance(c, LocalTTSClient)
    assert c.base_url == "http://local:9000"
    assert c.model == settings.tts_model


def test_local_client_none_branch(monkeypatch):
    monkeypatch.setattr(settings, "vllm_tts_hq_url", "")
    monkeypatch.setattr(settings, "vllm_tts_url", "")
    assert tts_settings._local_client() is None


def test_clean_lone_surrogates():
    assert tts_settings._clean_lone_surrogates("a\ud800b") == "ab"
    assert tts_settings._clean_lone_surrogates("\udc00x") == "x"
    assert tts_settings._clean_lone_surrogates(123) == 123
    assert tts_settings._clean_lone_surrogates(None) is None


def test_speak_request_validator_strips_surrogates():
    req = tts_settings.SpeakRequest(text="a\ud800b")
    assert req.text == "ab"


def test_speak_request_validator_rejects_all_surrogate():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        tts_settings.SpeakRequest(text="\ud800")


def test_generate_id():
    a = tts_settings.generate_id()
    assert isinstance(a, str) and len(a) == 16
