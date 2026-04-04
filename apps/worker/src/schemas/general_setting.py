"""General Setting schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class GeneralSettingBase(BaseModel):
    output_dir: str = Field("./data/output", max_length=512)
    video_resolution_width: int = Field(1080, ge=1)
    video_resolution_height: int = Field(1920, ge=1)
    pexels_api_key: str | None = Field(None, max_length=255)
    pixabay_api_key: str | None = Field(None, max_length=255)
    default_background_music: str | None = Field(None, max_length=255)


class GeneralSettingUpdate(BaseModel):
    output_dir: str | None = Field(None, max_length=512)
    video_resolution_width: int | None = Field(None, ge=1)
    video_resolution_height: int | None = Field(None, ge=1)
    pexels_api_key: str | None = Field(None, max_length=255)
    pixabay_api_key: str | None = Field(None, max_length=255)
    default_background_music: str | None = Field(None, max_length=255)


class GeneralSettingResponse(GeneralSettingBase):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True