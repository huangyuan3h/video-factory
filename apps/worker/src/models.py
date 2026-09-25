"""SQLAlchemy models for Video Factory."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Source(Base):
    """Content source model."""

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False)  # rss, news_api, hot_topics
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str | None] = mapped_column(String(512))
    api_key: Mapped[str | None] = mapped_column(String(255))
    keywords: Mapped[str | None] = mapped_column(Text)  # JSON array as string
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
    series_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending, processing, completed, failed
    input_content: Mapped[str | None] = mapped_column(Text)
    script: Mapped[str | None] = mapped_column(Text)
    video_path: Mapped[str | None] = mapped_column(String(512))
    published_to: Mapped[str | None] = mapped_column(Text)  # JSON array as string
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
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
    """Publishing platform account — extensible for OAuth + folder/playlist."""

    __tablename__ = "publisher_accounts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)  # douyin, xiaohongshu, youtube, bilibili
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    cookies: Mapped[str | None] = mapped_column(Text)  # JSON cookies or OAuth token JSON
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    # Extensible fields for folder/playlist/OAuth
    credentials: Mapped[str | None] = mapped_column(Text, nullable=True)  # OAuth refresh_token JSON for YouTube
    folder_id: Mapped[str | None] = mapped_column(String(128), nullable=True)  # Douyin collection / XHS album / YouTube playlistId
    folder_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extra_config: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON for platform-specific settings


class GenerationJob(Base):
    """Queue-backed video generation job (DB fallback when Redis is unavailable)."""

    __tablename__ = "generation_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # task_id
    task_uuid: Mapped[str | None] = mapped_column(String(32), nullable=True)
    series_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    task_dir: Mapped[str] = mapped_column(String(512), nullable=False)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending, processing, completed, failed, cancelled
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Series(Base):
    """A series groups a family of videos under one folder/theme."""

    __tablename__ = "series"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_voice: Mapped[str | None] = mapped_column(
        String(64), nullable=True, default="zh-CN-YunjianNeural"
    )
    default_voice_rate: Mapped[str | None] = mapped_column(String(16), nullable=True)
    default_resolution_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    default_resolution_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    default_background_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    default_background_music: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


class SeriesPublishTarget(Base):
    """Per-series publishing destination (account + folder per platform)."""

    __tablename__ = "series_publish_targets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    series_id: Mapped[str] = mapped_column(String(32), ForeignKey("series.id"), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    account_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    folder_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    folder_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class PublishJob(Base):
    """Queued publishing job for a generated video."""

    __tablename__ = "publish_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    series_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    video_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    task_dir: Mapped[str | None] = mapped_column(String(512), nullable=True)
    account_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    folder_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    privacy: Mapped[str | None] = mapped_column(String(32), nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    post_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    post_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TTSSetting(Base):
    """TTS voice configuration."""

    __tablename__ = "tts_settings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    voice: Mapped[str] = mapped_column(String(64), nullable=False, default="zh-CN-YunjianNeural")
    rate: Mapped[str] = mapped_column(String(16), nullable=False, default="+0%")
    test_text: Mapped[str | None] = mapped_column(Text, default="你好，这是一个语音测试。")
    is_default: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


class GeneralSetting(Base):
    """General application settings."""

    __tablename__ = "general_settings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    output_dir: Mapped[str] = mapped_column(String(512), nullable=False, default="./data/output")
    video_resolution_width: Mapped[int] = mapped_column(Integer, nullable=False, default=1080)
    video_resolution_height: Mapped[int] = mapped_column(Integer, nullable=False, default=1920)
    pexels_api_key: Mapped[str | None] = mapped_column(String(255))
    pixabay_api_key: Mapped[str | None] = mapped_column(String(255))
    default_background_music: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


class SystemPrompt(Base):
    """System prompts for content generation."""

    __tablename__ = "system_prompts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
