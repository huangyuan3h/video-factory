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

    # Series grouping
    # True: videos live under data/output/<series_slug>/<task_uuid>/
    # False: keep a flat data/output/<task_uuid>/ layout (series only in DB)
    series_output_folders: bool = True

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

    # Scheduler
    enable_scheduler: bool = True  # start APScheduler with the API process
    scheduler_auto_publish: bool = False  # scheduled runs publish to all enabled accounts

    # Material Source
    pexels_api_key: str | None = None
    pixabay_api_key: str | None = None
    redis_url: str = ""  # e.g. redis://localhost:6379/0 for worker queue
    queue_backend: str = "auto"  # auto | db | redis (see src/queue.py)

    # Synthetic images via ComfyUI — OFF by default. ComfyUI + SD3.5 can consume
    # 10GB+ RAM/VRAM and has frozen laptops before, so it must be explicitly opted in.
    comfyui_url: str = "http://127.0.0.1:8188"
    enable_synthetic: bool = False
    synthetic_min_free_gb: float = 12.0  # refuse to generate below this much free RAM
    synthetic_max_images: int = 1  # hard cap per call regardless of requested batch
    synthetic_timeout_s: float = 120.0  # per-image generation timeout
    synthetic_cooldown_s: float = 5.0  # sleep between images

    # Synthetic video / animation via ComfyUI (LTX-Video etc.) — OFF by default.
    # Even heavier than images (multi-GB video models); intended for capable hosts.
    enable_synthetic_video: bool = False
    synthetic_video_workflow: str = ""  # path to an exported ComfyUI workflow-API JSON
    synthetic_video_min_free_gb: float = 16.0
    synthetic_video_max_clips: int = 2  # hard cap per call
    synthetic_video_timeout_s: float = 900.0  # per-clip generation timeout
    synthetic_video_cooldown_s: float = 10.0
    synthetic_video_width: int = 768
    synthetic_video_height: int = 512
    synthetic_video_frames: int = 97  # ~4s at 25fps for LTX
    synthetic_video_fps: float = 25.0

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
