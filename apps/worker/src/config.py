"""Configuration management for Video Factory Worker."""

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/video-factory.db"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # Paths
    data_dir: Path = Path("./data")
    output_dir: Path = Path("./data/output")
    assets_dir: Path = Path("./data/assets")

    # AI Settings (can be overridden via database)
    openai_base_url: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o"

    # TTS Settings
    tts_voice: str = "zh-CN-XiaoxiaoNeural"
    tts_rate: str = "+0%"

    # Video Settings
    video_resolution: str = "1080p"
    video_fps: int = 30

    # Material Source
    pexels_api_key: Optional[str] = None
    pixabay_api_key: Optional[str] = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Ensure directories exist
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()