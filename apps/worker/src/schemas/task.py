"""Task schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


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