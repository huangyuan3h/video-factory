"""Configuration management for Video Factory Worker."""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/video-factory.db"

    def model_post_init(self, __context) -> None:
        # An empty DATABASE_URL env (common in dev shells) must not clobber the default.
        if not self.database_url or not str(self.database_url).strip():
            self.database_url = "sqlite+aiosqlite:///./data/video-factory.db"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # Paths
    data_dir: Path = Path("./data")
    output_dir: Path = Path("./data/output")
    assets_dir: Path = Path("./data/assets")

    # AI Settings (can be overridden via database)
    openai_base_url: str | None = None
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o"
    # Fallback providers for LLM rewrite when no system_prompt provided
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    vercel_gateway_api_key: str | None = None
    vercel_api_key: str | None = None  # alias for VERCEL_API_KEY env
    vercel_gateway_url: str = "https://ai-gateway.vercel.sh/v1"

    # TTS Settings — edge-tts defaults
    tts_voice: str = "zh-CN-XiaoxiaoNeural"
    tts_rate: str = "+0%"

    # Local TTS (OpenAI-compatible, e.g. Qwen3-TTS / Spark-TTS)
    # When set, local TTS takes precedence over edge-tts
    vllm_tts_url: str = ""
    vllm_tts_hq_url: str = ""
    tts_model: str = "tts-1"
    tts_language: str = "Chinese"
    tts_speed: float = 1.0
    tts_sample_rate: int = 16000
    tts_response_format: str = "wav"
    tts_timeout_s: float = 300.0
    # Spark voice library (mirrors Fae-v2)
    spark_voice_dir: str = ".data/connectors/voice"
    spark_voices_file: str = "scripts/tts/spark-voices.json"

    # Video Settings
    video_resolution: str = "1080p"
    video_fps: int = 30

    # Agent / security
    api_token: str | None = None  # when set, require Bearer on mutating routes
    cors_origins: str = "*"

    # Material Source
    pexels_api_key: str | None = None
    pixabay_api_key: str | None = None
    comfyui_url: str = "http://127.0.0.1:8188"
    redis_url: str = ""  # e.g. redis://localhost:6379/0 for worker queue

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Ensure directories exist
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
