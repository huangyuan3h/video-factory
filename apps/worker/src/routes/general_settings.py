"""General settings management routes."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models import GeneralSetting
from ..schemas import ApiResponse, GeneralSettingResponse, GeneralSettingUpdate

router = APIRouter()


def generate_id() -> str:
    """Generate a unique ID."""
    import hashlib
    import time
    return hashlib.md5(f"{time.time()}".encode()).hexdigest()[:16]


async def get_or_create_default_general_setting(session: AsyncSession) -> GeneralSetting:
    """Get the default general setting or create one if it doesn't exist."""
    result = await session.execute(select(GeneralSetting))
    setting = result.scalar_one_or_none()

    if not setting:
        setting = GeneralSetting(
            id=generate_id(),
            output_dir="./data/output",
            video_resolution_width=1080,
            video_resolution_height=1920,
        )
        session.add(setting)
        await session.commit()
        await session.refresh(setting)

    return setting


@router.get("", response_model=ApiResponse[GeneralSettingResponse])
async def get_general_setting(
    session: AsyncSession = Depends(get_session),
):
    """Get the general settings."""
    setting = await get_or_create_default_general_setting(session)
    return ApiResponse(success=True, data=GeneralSettingResponse.model_validate(setting))


@router.put("", response_model=ApiResponse[GeneralSettingResponse])
async def update_general_setting(
    data: GeneralSettingUpdate,
    session: AsyncSession = Depends(get_session),
):
    """Update the general settings."""
    setting = await get_or_create_default_general_setting(session)

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(setting, key, value)

    await session.commit()
    await session.refresh(setting)
    return ApiResponse(success=True, data=GeneralSettingResponse.model_validate(setting))
