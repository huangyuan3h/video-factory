"""Series schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class SeriesBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    cover_path: str | None = Field(None, max_length=512)
    system_prompt: str | None = None
    default_voice: str | None = Field(None, max_length=64)
    default_voice_rate: str | None = Field(None, max_length=16)
    default_resolution_width: int | None = Field(None, ge=256, le=4096)
    default_resolution_height: int | None = Field(None, ge=256, le=4096)
    default_background_source: str | None = Field(None, max_length=32)
    default_background_music: str | None = Field(None, max_length=255)


class SeriesCreate(SeriesBase):
    slug: str | None = Field(None, max_length=128)


class SeriesUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    slug: str | None = Field(None, max_length=128)
    description: str | None = None
    cover_path: str | None = Field(None, max_length=512)
    system_prompt: str | None = None
    default_voice: str | None = Field(None, max_length=64)
    default_voice_rate: str | None = Field(None, max_length=16)
    default_resolution_width: int | None = Field(None, ge=256, le=4096)
    default_resolution_height: int | None = Field(None, ge=256, le=4096)
    default_background_source: str | None = Field(None, max_length=32)
    default_background_music: str | None = Field(None, max_length=255)


class SeriesResponse(SeriesBase):
    id: str
    slug: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
