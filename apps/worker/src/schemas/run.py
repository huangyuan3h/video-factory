"""Run schemas."""

import json
from datetime import datetime

from pydantic import BaseModel, field_validator


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

    @field_validator("published_to", mode="before")
    @classmethod
    def _parse_published_to(cls, value):
        """DB stores published_to as a JSON string; expose a list."""
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except Exception:
                parsed = [value]
            return parsed if isinstance(parsed, list) else [str(parsed)]
        return value

    class Config:
        from_attributes = True
