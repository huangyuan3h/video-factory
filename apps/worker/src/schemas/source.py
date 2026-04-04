"""Source schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


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