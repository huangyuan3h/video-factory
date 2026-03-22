"""AI settings management routes."""


from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models import AISetting
from ..schemas import AISettingCreate, AISettingResponse, AISettingUpdate, ApiResponse

router = APIRouter()


def generate_id() -> str:
    """Generate a unique ID."""
    import hashlib
    import time
    return hashlib.md5(f"{time.time()}".encode()).hexdigest()[:16]


@router.get("", response_model=ApiResponse[list[AISettingResponse]])
async def list_ai_settings(
    session: AsyncSession = Depends(get_session),
):
    """List all AI settings."""
    result = await session.execute(select(AISetting))
    settings = result.scalars().all()
    return ApiResponse(
        success=True,
        data=[AISettingResponse.model_validate(s) for s in settings],
    )


@router.get("/active", response_model=ApiResponse[AISettingResponse])
async def get_active_ai_setting(
    session: AsyncSession = Depends(get_session),
):
    """Get the active AI setting."""
    result = await session.execute(
        select(AISetting).where(AISetting.is_active == True)
    )
    setting = result.scalar_one_or_none()
    if not setting:
        return ApiResponse(success=False, error="No active AI setting found")
    return ApiResponse(success=True, data=AISettingResponse.model_validate(setting))


@router.post("", response_model=ApiResponse[AISettingResponse])
async def create_ai_setting(
    data: AISettingCreate,
    session: AsyncSession = Depends(get_session),
):
    """Create a new AI setting."""
    # If this is set as active, deactivate others
    setting = AISetting(
        id=generate_id(),
        name=data.name,
        base_url=data.base_url,
        api_key=data.api_key,
        model_id=data.model_id,
        temperature=data.temperature,
        max_tokens=data.max_tokens,
        is_active=True,
    )
    session.add(setting)
    await session.commit()
    await session.refresh(setting)
    return ApiResponse(success=True, data=AISettingResponse.model_validate(setting))


@router.put("/{setting_id}", response_model=ApiResponse[AISettingResponse])
async def update_ai_setting(
    setting_id: str,
    data: AISettingUpdate,
    session: AsyncSession = Depends(get_session),
):
    """Update an AI setting."""
    result = await session.execute(
        select(AISetting).where(AISetting.id == setting_id)
    )
    setting = result.scalar_one_or_none()
    if not setting:
        raise HTTPException(status_code=404, detail="AI setting not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(setting, key, value)
    await session.commit()
    await session.refresh(setting)
    return ApiResponse(success=True, data=AISettingResponse.model_validate(setting))


@router.post("/{setting_id}/activate", response_model=ApiResponse[AISettingResponse])
async def activate_ai_setting(
    setting_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Activate an AI setting (deactivates others)."""
    result = await session.execute(select(AISetting))
    settings = result.scalars().all()

    found = False
    for s in settings:
        if s.id == setting_id:
            s.is_active = True
            found = True
        else:
            s.is_active = False

    if not found:
        raise HTTPException(status_code=404, detail="AI setting not found")

    await session.commit()

    result = await session.execute(
        select(AISetting).where(AISetting.id == setting_id)
    )
    setting = result.scalar_one()
    return ApiResponse(success=True, data=AISettingResponse.model_validate(setting))


@router.delete("/{setting_id}", response_model=ApiResponse[None])
async def delete_ai_setting(
    setting_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Delete an AI setting."""
    result = await session.execute(
        select(AISetting).where(AISetting.id == setting_id)
    )
    setting = result.scalar_one_or_none()
    if not setting:
        raise HTTPException(status_code=404, detail="AI setting not found")

    await session.delete(setting)
    await session.commit()
    return ApiResponse(success=True)


@router.post("/{setting_id}/test", response_model=ApiResponse[dict])
async def test_ai_setting(
    setting_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Test AI provider connection."""
    import time

    from openai import AsyncOpenAI

    result = await session.execute(
        select(AISetting).where(AISetting.id == setting_id)
    )
    setting = result.scalar_one_or_none()
    if not setting:
        raise HTTPException(status_code=404, detail="AI setting not found")

    try:
        client = AsyncOpenAI(
            base_url=setting.base_url,
            api_key=setting.api_key,
        )

        start_time = time.time()
        response = await client.chat.completions.create(
            model=setting.model_id,
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=10,
        )
        latency_ms = int((time.time() - start_time) * 1000)

        return ApiResponse(
            success=True,
            data={
                "success": True,
                "latency_ms": latency_ms,
                "model": response.model,
            },
        )
    except Exception as e:
        return ApiResponse(
            success=True,
            data={
                "success": False,
                "error": str(e),
            },
        )
