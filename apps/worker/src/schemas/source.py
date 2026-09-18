"""Source schemas."""

import json
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


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

    @field_validator("keywords", mode="before")
    @classmethod
    def _parse_keywords(cls, value):
        """DB stores keywords as a JSON string; expose a list."""
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except Exception:
                parsed = [k.strip() for k in value.split(",") if k.strip()]
            if isinstance(parsed, list):
                return parsed
            return [str(parsed)]
        return value

    class Config:
        from_attributes = True