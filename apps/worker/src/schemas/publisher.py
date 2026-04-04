"""Publisher Account schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


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