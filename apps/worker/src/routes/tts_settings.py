"""TTS settings management routes — edge-tts + local OpenAI-compatible.

Backward-compatible with original:
  GET  /api/tts-settings         -> default TTSSetting
  PUT  /api/tts-settings         -> update
  POST /api/tts-settings/test    -> synthesize test audio (FileResponse)
  GET  /api/tts-settings/voices  -> list voices

New (ported from Fae-v2):
  GET  /api/tts-settings/status        -> local TTS health + engine info
  POST /api/tts-settings/speak         -> single-shot synthesis (raw audio)
  POST /api/tts-settings/speak-stream  -> chunked streaming (u32be WAV blocks)
  POST /api/tts-settings/voices/register -> clone voice via reference wav
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import struct
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, BeforeValidator, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..core.tts.edge_provider import EdgeTTSProvider
from ..core.tts.local_client import BUILTIN_LANGUAGES, BUILTIN_VOICES, LocalTTSClient, LocalTTSError
from ..core.tts.speakable import clip_for_local_tts, to_speakable_text
from ..core.tts.streaming import chunk_for_tts, pad_silence
from ..database import get_session
from ..models import TTSSetting
from ..schemas import ApiResponse, TTSSettingResponse, TTSSettingTestRequest, TTSSettingUpdate

logger = logging.getLogger(__name__)

router = APIRouter()

_REPO_ROOT = Path(__file__).resolve().parents[4]
_VOICE_DIR = Path(settings.spark_voice_dir) if Path(settings.spark_voice_dir).is_absolute() else _REPO_ROOT / settings.spark_voice_dir
_VOICES_FILE = Path(settings.spark_voices_file) if Path(settings.spark_voices_file).is_absolute() else _REPO_ROOT / settings.spark_voices_file
_VOICE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_LONE_SURROGATE_RE = re.compile(r"[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]")
_HQ_VOICE_PREFIX = "spark:"
_MAX_CHARS = 120  # safety net, UI already chunks ~60

# Built-in Spark fallback (mirrors Fae spark-voices.json defaults)
_SPARK_VOICES_FALLBACK: list[dict[str, str]] = [
    {"id": "spark:female", "name": "Spark · 女声（高质量）", "language": "Chinese"},
    {"id": "spark:male", "name": "Spark · 男声（高质量）", "language": "Chinese"},
    {"id": "spark:female-fast", "name": "Spark · 女声偏快", "language": "Chinese"},
]


def generate_id() -> str:
    import hashlib
    import time as _time
    return hashlib.md5(f"{_time.time()}".encode()).hexdigest()[:16]


async def get_or_create_default_tts_setting(session: AsyncSession) -> TTSSetting:
    result = await session.execute(select(TTSSetting).where(TTSSetting.is_default == True))  # noqa: E712
    setting = result.scalar_one_or_none()
    if not setting:
        setting = TTSSetting(
            id=generate_id(),
            voice="zh-CN-XiaoxiaoNeural",
            rate="+0%",
            test_text="你好，这是一个语音测试。",
            is_default=True,
        )
        session.add(setting)
        await session.commit()
        await session.refresh(setting)
    return setting


def _local_client() -> LocalTTSClient | None:
    """Return LocalTTSClient if local TTS is configured, else None."""
    hq = (settings.vllm_tts_hq_url or "").strip()
    if hq:
        return LocalTTSClient(
            base_url=hq,
            model="spark-tts-0.5b",
            voice="spark:female",
            sample_rate=16000,
            response_format="wav",
            timeout_s=settings.tts_timeout_s,
            language="Chinese",
            speed=1.0,
        )
    url = (settings.vllm_tts_url or "").strip()
    if url:
        return LocalTTSClient(
            base_url=url,
            model=settings.tts_model,
            voice=settings.tts_voice,
            sample_rate=settings.tts_sample_rate,
            response_format=settings.tts_response_format,
            timeout_s=settings.tts_timeout_s,
            language=settings.tts_language,
            speed=settings.tts_speed,
        )
    return None


def _clean_lone_surrogates(value: object) -> object:
    if isinstance(value, str):
        return _LONE_SURROGATE_RE.sub("", value)
    return value


class SpeakRequest(BaseModel):
    text: Annotated[str, BeforeValidator(_clean_lone_surrogates)] = Field(min_length=1, max_length=8000)
    voice: str | None = None
    speed: float | None = Field(default=None, ge=0.25, le=4.0)
    language: str | None = None


# ---- Backward-compatible routes ----


@router.get("", response_model=ApiResponse[TTSSettingResponse])
async def get_tts_setting(session: AsyncSession = Depends(get_session)):
    setting = await get_or_create_default_tts_setting(session)
    return ApiResponse(success=True, data=TTSSettingResponse.model_validate(setting))


@router.put("", response_model=ApiResponse[TTSSettingResponse])
async def update_tts_setting(data: TTSSettingUpdate, session: AsyncSession = Depends(get_session)):
    setting = await get_or_create_default_tts_setting(session)
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(setting, key, value)
    await session.commit()
    await session.refresh(setting)
    return ApiResponse(success=True, data=TTSSettingResponse.model_validate(setting))


@router.post("/test")
async def test_tts_voice(data: TTSSettingTestRequest, session: AsyncSession = Depends(get_session)):
    setting = await get_or_create_default_tts_setting(session)
    voice = data.voice or setting.voice
    rate = data.rate or setting.rate
    test_text = data.test_text or setting.test_text or "你好，这是一个语音测试。"

    # If local TTS is configured, prefer it; else fall back to edge-tts
    client = _local_client()
    if client is not None:
        # Use local TTS path for test
        cleaned = to_speakable_text(test_text) or test_text
        try:
            audio, media_type = await client.synthesize(cleaned, voice=voice, speed=settings.tts_speed, language=settings.tts_language)
            # Write to temp for FileResponse compat: synthesize returned bytes
            tmp = Path(tempfile.mktemp(suffix=".wav" if "wav" in media_type else ".mp3"))
            tmp.write_bytes(audio)
            return FileResponse(path=tmp, media_type=media_type, filename=f"tts_test.{'wav' if 'wav' in media_type else 'mp3'}")
        except LocalTTSError as e:
            raise HTTPException(status_code=503, detail=f"Local TTS unavailable: {e}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"TTS test failed: {e}")

    tts = EdgeTTSProvider(voice=voice, rate=rate)
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            output_path = Path(tmp.name)
        await tts.synthesize(test_text, output_path)
        return FileResponse(path=output_path, media_type="audio/mpeg", filename="tts_test.mp3")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS test failed: {str(e)}")


@router.get("/voices", response_model=ApiResponse[dict[str, str] | dict])
async def list_tts_voices():
    """List voices — if local TTS configured, return upstream list; else edge list."""
    client = _local_client()
    if client is not None:
        result = await client.list_voices()
        # Normalize to richer response when local is active
        return ApiResponse(success=True, data=result)  # type: ignore[arg-type]
    voices = EdgeTTSProvider.list_voices()
    return ApiResponse(success=True, data=voices)  # type: ignore[arg-type]


# ---- New routes ported from Fae-v2 ----


@router.get("/status")
async def tts_status():
    client = _local_client()
    if client is None:
        return {
            "backend": "edge-tts",
            "configured": False,
            "embedded": False,
            "natural_speech": False,
            "model": "edge-tts",
            "voice": settings.tts_voice,
            "language": settings.tts_language,
            "speed": settings.tts_speed,
            "url": None,
            "hq_configured": False,
            "hint": "Edge-TTS mode. Set VLLM_TTS_URL or VLLM_TTS_HQ_URL for local TTS.",
        }
    reachable = await client.health()
    upstream = await client.upstream_status() if reachable else None
    up_backend = (upstream or {}).get("backend") or {}
    up_device = (upstream or {}).get("device") or {}
    upstream_engine = str(up_backend.get("name") or "") or None
    upstream_model = str(up_backend.get("model_id") or "") or None
    return {
        "backend": "local",
        "configured": reachable,
        "embedded": False,
        "natural_speech": reachable,
        "model": client.model,
        "voice": client.voice,
        "language": client.language,
        "speed": client.speed,
        "sample_rate": client.sample_rate,
        "url": client.base_url,
        "hq_url": settings.vllm_tts_hq_url or None,
        "hq_configured": bool((settings.vllm_tts_hq_url or "").strip()),
        "speech_url": client.speech_url,
        "upstream_engine": upstream_engine,
        "upstream_model": upstream_model,
        "upstream_device": up_device.get("type") or up_device.get("gpu_name"),
        "hint": (
            f"Local TTS ready at {client.speech_url}" + (f" · {upstream_engine} · {upstream_model}" if upstream_model else "")
            if reachable
            else (
                f"No TTS server at {client.speech_url}. "
                "Start a local TTS server and set VLLM_TTS_URL/HQ_URL."
            )
        ),
    }


async def _spark_voices(client: LocalTTSClient) -> list[dict[str, str]]:
    try:
        result = await client.list_voices()
    except Exception:
        return list(_SPARK_VOICES_FALLBACK)
    voices = result.get("voices") or []
    if not voices:
        return list(_SPARK_VOICES_FALLBACK)
    return [
        {"id": str(v["id"]), "name": f"Spark · {v['name']}", "language": "Chinese"}
        for v in voices
        if isinstance(v, dict) and v.get("id")
    ]


@router.post("/voices/register")
async def register_voice(
    voice_id: str = Form(...),
    transcript: str = Form(...),
    file: UploadFile = File(...),
):
    vid = (voice_id or "").strip().lower()
    if not _VOICE_ID_RE.match(vid):
        raise HTTPException(status_code=422, detail={"message": "voice_id 只能是小写字母开头、含小写字母/数字/_/-"})
    text = (transcript or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail={"message": "转写文本不能为空"})
    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail={"message": "音频文件为空"})
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=422, detail={"message": "音频文件不能超过 20MB"})

    _VOICE_DIR.mkdir(parents=True, exist_ok=True)
    ref_dst = _VOICE_DIR / f"{vid}.wav"

    if shutil.which("ffmpeg"):
        tmp = _VOICE_DIR / f".{vid}.tmp.wav"
        tmp.write_bytes(content)
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-i", str(tmp), "-ar", "16000", "-ac", "1", str(ref_dst)],
                check=True,
                timeout=60,
            )
        except Exception:
            ref_dst.write_bytes(content)
        finally:
            tmp.unlink(missing_ok=True)
    else:
        ref_dst.write_bytes(content)

    try:
        data = json.loads(_VOICES_FILE.read_text()) if _VOICES_FILE.exists() else {}
    except Exception:
        data = {}
    data[vid] = {"ref": f"{vid}.wav", "text": text, "speed": 1.0, "description": f"Cloned voice '{vid}'"}
    _VOICES_FILE.parent.mkdir(parents=True, exist_ok=True)
    _VOICES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    logger.info("registered voice '%s' (ref=%s)", vid, ref_dst)
    return {"id": f"spark:{vid}", "registered": True, "ref": str(ref_dst)}


@router.post("/speak-stream")
async def speak_stream(body: SpeakRequest):
    plain = to_speakable_text(body.text)
    if not plain:
        raise HTTPException(status_code=400, detail={"code": "empty_text", "message": "Nothing left to speak"})
    chunks = chunk_for_tts(plain)
    if not chunks:
        raise HTTPException(status_code=400, detail={"code": "empty_text", "message": "Nothing left to speak"})

    voice = (body.voice or settings.tts_voice or "spark:female").strip()
    language = (body.language or settings.tts_language or "Chinese").strip()
    speed = float(body.speed) if body.speed is not None else float(settings.tts_speed)
    client = _local_client()
    if client is None:
        raise HTTPException(status_code=503, detail={"code": "local_tts_unavailable", "message": "Local TTS not configured. Set VLLM_TTS_URL."})
    hq_voice = voice.startswith(_HQ_VOICE_PREFIX) or bool((settings.vllm_tts_hq_url or "").strip())
    if hq_voice:
        speed = 1.0

    async def _gen():
        n = len(chunks)
        sem = asyncio.Semaphore(2)
        results: dict[int, bytes] = {}
        failures: set[int] = set()

        async def _synth_one(i: int, chunk: str) -> None:
            async with sem:
                try:
                    wav, _ = await client.synthesize(chunk, voice=voice, speed=speed, language=language)
                except LocalTTSError as exc:
                    logger.warning("speak-stream chunk %d failed: %s", i, exc)
                    failures.add(i)
                    return
            results[i] = wav

        window: list[tuple[int, asyncio.Task]] = []
        next_i = 0
        while next_i < n or window:
            while len(window) < 2 and next_i < n:
                i = next_i
                next_i += 1
                window.append((i, asyncio.create_task(_synth_one(i, chunks[i]))))
            i, task = window.pop(0)
            await task
            wav = results.pop(i, None)
            if wav is not None:
                is_last = i == n - 1 and not failures
                block = wav if is_last else pad_silence(wav)
                yield struct.pack(">I", len(block)) + block
        yield struct.pack(">I", 0)

    return StreamingResponse(
        _gen(),
        media_type="application/octet-stream",
        headers={
            "X-TTS-Backend": "local",
            "X-TTS-Upstream": client.speech_url,
            "X-TTS-Engine": "spark-hq" if hq_voice else "default",
            "Cache-Control": "no-store",
        },
    )


@router.post("/speak")
async def speak(body: SpeakRequest):
    plain = to_speakable_text(body.text)
    if not plain:
        raise HTTPException(status_code=400, detail={"code": "empty_text", "message": "Nothing left to speak"})
    if len(plain) > 1800:
        raise HTTPException(
            status_code=413,
            detail={"code": "text_too_long", "message": "文本过长，请使用 /api/tts-settings/speak-stream"},
        )
    voice = (body.voice or settings.tts_voice or "spark:female").strip()
    language = (body.language or settings.tts_language or "Chinese").strip()
    speed = float(body.speed) if body.speed is not None else float(settings.tts_speed)
    client = _local_client()
    if client is None:
        raise HTTPException(status_code=503, detail={"code": "local_tts_unavailable", "message": "Local TTS not configured"})
    hq_voice = voice.startswith(_HQ_VOICE_PREFIX) or bool((settings.vllm_tts_hq_url or "").strip())
    if hq_voice:
        speed = 1.0
    started = time.perf_counter()
    try:
        audio, media_type = await client.synthesize(plain, voice=voice, speed=speed, language=language)
    except LocalTTSError as e:
        logger.warning("Local TTS failed (%s): %s", client.speech_url, e)
        raise HTTPException(status_code=503, detail={"code": "local_tts_unavailable", "message": str(e), "upstream": client.speech_url}) from e
    except Exception as e:
        logger.exception("Local TTS failed")
        raise HTTPException(status_code=502, detail={"code": "tts_failed", "message": str(e), "upstream": client.speech_url}) from e

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info("tts.speak ms=%s chars=%s voice=%s upstream=%s", elapsed_ms, len(plain), voice, client.speech_url)

    return Response(
        content=audio,
        media_type=media_type or "audio/wav",
        headers={
            "X-TTS-Backend": "local",
            "X-TTS-Upstream": client.speech_url,
            "X-TTS-Voice": voice,
            "X-TTS-Speed": f"{speed:.2f}",
            "X-TTS-Ms": str(elapsed_ms),
            "X-TTS-Engine": "spark-hq" if hq_voice else "default",
            "Cache-Control": "no-store",
        },
    )
