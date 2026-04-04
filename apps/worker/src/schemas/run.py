"""Run schemas."""

from datetime import datetime

from pydantic import BaseModel


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