"""Pydantic schemas for API validation."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# Source Schemas
class SourceBase(BaseModel):
    type: str = Field(..., description="Source type: rss, news_api, hot_topics, custom")
    name: str = Field(..., min_length=1, max_length=255)
    url: Optional[str] = Field(None, max_length=512)
    api_key: Optional[str] = Field(None, max_length=255)
    keywords: Optional[list[str]] = Field(default_factory=list)
    enabled: bool = True


class SourceCreate(SourceBase):
    pass


class SourceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    url: Optional[str] = Field(None, max_length=512)
    api_key: Optional[str] = Field(None, max_length=255)
    keywords: Optional[list[str]] = None
    enabled: Optional[bool] = None


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
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    schedule: Optional[str] = None
    enabled: Optional[bool] = None


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
    input_content: Optional[str] = None
    script: Optional[str] = None
    video_path: Optional[str] = None
    published_to: Optional[list[str]] = None
    error: Optional[str] = None


class RunCreate(BaseModel):
    task_id: str


class RunResponse(RunBase):
    id: str
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
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
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    base_url: Optional[str] = Field(None, min_length=1, max_length=512)
    api_key: Optional[str] = Field(None, min_length=1)
    model_id: Optional[str] = Field(None, min_length=1, max_length=128)
    temperature: Optional[float] = Field(None, ge=0, le=2)
    max_tokens: Optional[int] = Field(None, ge=1, le=128000)
    is_active: Optional[bool] = None


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
    cookies: Optional[str] = None


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
    test_text: Optional[str] = Field("你好，这是一个语音测试。", max_length=500)


class TTSSettingUpdate(BaseModel):
    voice: Optional[str] = Field(None, max_length=64)
    rate: Optional[str] = Field(None, max_length=16)
    test_text: Optional[str] = Field(None, max_length=500)


class TTSSettingTestRequest(BaseModel):
    voice: Optional[str] = None
    rate: Optional[str] = None
    test_text: Optional[str] = None


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
    pexels_api_key: Optional[str] = Field(None, max_length=255)
    pixabay_api_key: Optional[str] = Field(None, max_length=255)


class GeneralSettingUpdate(BaseModel):
    output_dir: Optional[str] = Field(None, max_length=512)
    video_resolution_width: Optional[int] = Field(None, ge=1)
    video_resolution_height: Optional[int] = Field(None, ge=1)
    pexels_api_key: Optional[str] = Field(None, max_length=255)
    pixabay_api_key: Optional[str] = Field(None, max_length=255)


class GeneralSettingResponse(GeneralSettingBase):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# API Response Schemas
class ApiResponse[T](BaseModel):
    success: bool
    data: Optional[T] = None
    error: Optional[str] = None


class PaginatedResponse[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int