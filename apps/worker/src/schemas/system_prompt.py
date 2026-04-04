"""System Prompt schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


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