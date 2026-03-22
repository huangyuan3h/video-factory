"""TTS settings management routes."""

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.tts_engine import EdgeTTSEngine
from ..database import get_session
from ..models import TTSSetting
from ..schemas import ApiResponse, TTSSettingResponse, TTSSettingTestRequest, TTSSettingUpdate

router = APIRouter()


def generate_id() -> str:
    """Generate a unique ID."""
    import hashlib
    import time
    return hashlib.md5(f"{time.time()}".encode()).hexdigest()[:16]


async def get_or_create_default_tts_setting(session: AsyncSession) -> TTSSetting:
    """Get the default TTS setting or create one if it doesn't exist."""
    result = await session.execute(
        select(TTSSetting).where(TTSSetting.is_default == True)
    )
    setting = result.scalar_one_or_none()

    if not setting:
        # Create default setting
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


@router.get("", response_model=ApiResponse[TTSSettingResponse])
async def get_tts_setting(
    session: AsyncSession = Depends(get_session),
):
    """Get the default TTS setting."""
    setting = await get_or_create_default_tts_setting(session)
    return ApiResponse(success=True, data=TTSSettingResponse.model_validate(setting))


@router.put("", response_model=ApiResponse[TTSSettingResponse])
async def update_tts_setting(
    data: TTSSettingUpdate,
    session: AsyncSession = Depends(get_session),
):
    """Update the default TTS setting."""
    setting = await get_or_create_default_tts_setting(session)

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(setting, key, value)

    await session.commit()
    await session.refresh(setting)
    return ApiResponse(success=True, data=TTSSettingResponse.model_validate(setting))


@router.post("/test")
async def test_tts_voice(
    data: TTSSettingTestRequest,
    session: AsyncSession = Depends(get_session),
):
    """Test TTS voice by generating a sample audio."""
    # Get current setting or use defaults
    setting = await get_or_create_default_tts_setting(session)

    # Use provided values or fall back to saved settings
    voice = data.voice or setting.voice
    rate = data.rate or setting.rate
    test_text = data.test_text or setting.test_text or "你好，这是一个语音测试。"

    # Create TTS engine with the specified settings
    tts = EdgeTTSEngine(voice=voice, rate=rate)

    try:
        # Generate audio to temp file
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            output_path = Path(tmp.name)

        # Run async TTS
        await tts.synthesize(test_text, output_path)

        # Return the audio file
        return FileResponse(
            path=output_path,
            media_type="audio/mpeg",
            filename="tts_test.mp3",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS test failed: {str(e)}")


@router.get("/voices", response_model=ApiResponse[dict[str, str]])
async def list_tts_voices():
    """List all available TTS voices."""
    voices = EdgeTTSEngine.list_voices()
    return ApiResponse(success=True, data=voices)
