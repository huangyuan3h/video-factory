"""Pydantic schemas for API validation."""

from datetime import datetime
from typing import Generic, TypeVar, Optional

from pydantic import BaseModel, Field

T = TypeVar("T")


# Source Schemas
class SourceBase(BaseModel):
    type: str = Field(..., description="Source type: rss, news_api, hot_topics, custom")
    name: str = Field(..., min_length=1, max_length=255)
    url: str | None = Field(None, max_length=512)
    api_key: str | None = Field(None, max_length=255)
    keywords: list[str] | None = Field(default_factory=list)
    enabled: bool = True


class SourceCreate(SourceBase):
    pass


class SourceUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    url: str | None = Field(None, max_length=512)
    api_key: str | None = Field(None, max_length=255)
    keywords: list[str] | None = None
    enabled: bool | None = None


class SourceResponse(SourceBase):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Task Schemas
class TaskBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    source_id: str
    schedule: str = Field(..., description="Cron expression")
    enabled: bool = True


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    schedule: str | None = None
    enabled: bool | None = None


class TaskResponse(TaskBase):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Run Schemas
class RunBase(BaseModel):
    task_id: str
    status: str = "pending"
    input_content: str | None = None
    script: str | None = None
    video_path: str | None = None
    published_to: list[str] | None = None
    error: str | None = None


class RunCreate(BaseModel):
    task_id: str


class RunResponse(RunBase):
    id: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    created_at: datetime

    class Config:
        from_attributes = True


# AI Settings Schemas
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


# Publisher Account Schemas
class PublisherAccountBase(BaseModel):
    platform: str = Field(..., description="Platform: douyin, xiaohongshu, etc.")
    name: str = Field(..., min_length=1, max_length=255)
    enabled: bool = True


class PublisherAccountCreate(PublisherAccountBase):
    cookies: str | None = None


class PublisherAccountResponse(PublisherAccountBase):
    id: str
    created_at: datetime

    class Config:
        from_attributes = True


# Video Options Schema
class VideoOptions(BaseModel):
    voice: str = "zh-CN-XiaoxiaoNeural"
    resolution: str = "1080p"
    fps: int = 30
    material_source: str = "both"  # online, local, both


# TTS Settings Schemas
class TTSSettingBase(BaseModel):
    voice: str = Field("zh-CN-XiaoxiaoNeural", max_length=64)
    rate: str = Field("+0%", max_length=16)
    test_text: str | None = Field("你好，这是一个语音测试。", max_length=500)


class TTSSettingUpdate(BaseModel):
    voice: str | None = Field(None, max_length=64)
    rate: str | None = Field(None, max_length=16)
    test_text: str | None = Field(None, max_length=500)


class TTSSettingTestRequest(BaseModel):
    voice: str | None = None
    rate: str | None = None
    test_text: str | None = None


class TTSSettingResponse(TTSSettingBase):
    id: str
    is_default: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


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


# System Prompt Schemas
class SystemPromptBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)
    is_default: bool = False


class SystemPromptCreate(SystemPromptBase):
    pass


class SystemPromptUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    content: str | None = Field(None, min_length=1)
    is_default: bool | None = None


class SystemPromptResponse(SystemPromptBase):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# API Response Schemas
class ApiResponse(BaseModel, Generic[T]):
    success: bool
    data: T | None = None
    error: str | None = None


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
