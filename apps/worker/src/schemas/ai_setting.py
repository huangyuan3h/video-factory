"""AI Setting schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class AISettingBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    base_url: str = Field(..., min_length=1, max_length=512)
    api_key: str = Field(..., min_length=1)
    model_id: str = Field(..., min_length=1, max_length=128)
    temperature: float = Field(0.7, ge=0, le=2)
    max_tokens: int = Field(4096, ge=1, le=128000)


class AISettingCreate(AISettingBase):
    pass


class AISettingUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    base_url: str | None = Field(None, min_length=1, max_length=512)
    api_key: str | None = Field(None, min_length=1)
    model_id: str | None = Field(None, min_length=1, max_length=128)
    temperature: float | None = Field(None, ge=0, le=2)
    max_tokens: int | None = Field(None, ge=1, le=128000)
    is_active: bool | None = None


class AISettingResponse(AISettingBase):
    id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True