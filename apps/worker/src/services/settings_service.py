"""Settings service for retrieving configuration from database."""

from sqlalchemy import select

from ..core.ai_client import AIClient
from ..database import async_session_maker
from ..models import AISetting, GeneralSetting


async def get_active_ai_client() -> AIClient | None:
    """Get AI client from active database settings."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(AISetting).where(AISetting.is_active == True)
        )
        ai_setting = result.scalar_one_or_none()
        
        if ai_setting:
            return AIClient(
                base_url=ai_setting.base_url,
                api_key=ai_setting.api_key,
                model=ai_setting.model_id,
            )
        return None


async def get_general_settings() -> dict:
    """Get general settings from database."""
    async with async_session_maker() as session:
        result = await session.execute(select(GeneralSetting))
        setting = result.scalar_one_or_none()
        if setting:
            return {
                "pexels_api_key": setting.pexels_api_key,
                "pixabay_api_key": setting.pixabay_api_key,
            }
        return {}