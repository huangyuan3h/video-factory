"""SQLAlchemy models for Video Factory."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Source(Base):
    """Content source model."""

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False)  # rss, news_api, hot_topics
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(512))
    api_key: Mapped[Optional[str]] = mapped_column(String(255))
    keywords: Mapped[Optional[str]] = mapped_column(Text)  # JSON array as string
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    tasks: Mapped[list["Task"]] = relationship("Task", back_populates="source")


class Task(Base):
    """Scheduled task model."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_id: Mapped[str] = mapped_column(String(32), ForeignKey("sources.id"), nullable=False)
    schedule: Mapped[str] = mapped_column(String(64), nullable=False)  # cron expression
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    source: Mapped["Source"] = relationship("Source", back_populates="tasks")
    runs: Mapped[list["Run"]] = relationship("Run", back_populates="task")


class Run(Base):
    """Task execution record."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(32), ForeignKey("tasks.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending, processing, completed, failed
    input_content: Mapped[Optional[str]] = mapped_column(Text)
    script: Mapped[Optional[str]] = mapped_column(Text)
    video_path: Mapped[Optional[str]] = mapped_column(String(512))
    published_to: Mapped[Optional[str]] = mapped_column(Text)  # JSON array as string
    error: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    task: Mapped["Task"] = relationship("Task", back_populates="runs")


class AISetting(Base):
    """AI provider configuration."""

    __tablename__ = "ai_settings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    api_key: Mapped[str] = mapped_column(String(255), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


class PublisherAccount(Base):
    """Publishing platform account."""

    __tablename__ = "publisher_accounts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)  # douyin, xiaohongshu, etc.
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    cookies: Mapped[Optional[str]] = mapped_column(Text)  # JSON cookies
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class TTSSetting(Base):
    """TTS voice configuration."""

    __tablename__ = "tts_settings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    voice: Mapped[str] = mapped_column(String(64), nullable=False, default="zh-CN-XiaoxiaoNeural")
    rate: Mapped[str] = mapped_column(String(16), nullable=False, default="+0%")
    is_default: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())