"""TTS Setting schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


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