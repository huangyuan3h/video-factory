"""Configuration management for Video Factory Worker."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings

# Per-content-type narration/visual defaults. ``src.presets.get_type_preset``
# merges a type's overrides over the "general" preset; the book entry is kept in
# sync with the legacy ``book_*`` settings unless ``TYPE_PRESETS`` overrides it.
DEFAULT_TYPE_PRESETS: dict[str, dict] = {
    "general": {
        "voice": "zh-CN-YunjianNeural",
        "tts_rate": "+0%",
        "sentence_pause_seconds": 0.0,
        "sentence_gap_seconds": 0.0,
        "segment_pause_seconds": 0.0,
        "image_hold_seconds": 4.0,
        "orientation": "landscape",
        "footage": "video_first",
        "proofread": False,
        "presenter_intro": False,
        "chart_layout": "letterbox",
    },
    "news": {
        "voice": "zh-CN-YunjianNeural",
        "tts_rate": "+0%",
        "sentence_pause_seconds": 0.0,
        "sentence_gap_seconds": 0.0,
        "segment_pause_seconds": 0.0,
        "image_hold_seconds": 4.0,
        "orientation": "landscape",
        "footage": "images_first",
        "proofread": False,
        "presenter_intro": True,
    },
    "book": {
        "voice": "zh-CN-YunjianNeural",
        "tts_rate": "-8%",
        "sentence_pause_seconds": 0.38,
        "sentence_gap_seconds": 0.0,
        "segment_pause_seconds": 0.5,
        "image_hold_seconds": 5.0,
        "orientation": "landscape",
        "footage": "video_first",
        "proofread": True,
        "presenter_intro": True,
        "chart_layout": "letterbox",
    },
    "indicator": {
        "voice": "zh-CN-YunjianNeural",
        "tts_rate": "+2%",
        "sentence_pause_seconds": 0.0,
        "sentence_gap_seconds": 0.75,
        "segment_pause_seconds": 0.5,
        "image_hold_seconds": 5.0,
        "orientation": "landscape",
        "footage": "video_first",
        "proofread": True,
        "presenter_intro": True,
        "chart_layout": "fullframe",
    },
}


class Settings(BaseSettings):
    """Application settings."""

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/video-factory.db"

    # Per-content-type narration/visual defaults, overridable via the
    # ``TYPE_PRESETS`` env JSON (e.g. TYPE_PRESETS='{"indicator":{"voice":"..."}}').
    type_presets: dict[str, dict] = Field(default_factory=dict)

    def model_post_init(self, __context) -> None:
        # An empty DATABASE_URL env (common in dev shells) must not clobber the default.
        if not self.database_url or not str(self.database_url).strip():
            self.database_url = "sqlite+aiosqlite:///./data/video-factory.db"
        self.type_presets = self._build_type_presets()

    def _build_type_presets(self) -> dict[str, dict]:
        """Merge env/default overrides into a complete per-type preset map.

        The book entry's pacing fields mirror the legacy ``book_*`` settings so
        overriding ``BOOK_TTS_RATE`` etc. still works, unless ``TYPE_PRESETS``
        explicitly set the same book field.
        """
        raw = self.type_presets if isinstance(self.type_presets, dict) else {}

        def _explicit(name: str) -> dict:
            value = raw.get(name)
            return value if isinstance(value, dict) else {}

        presets: dict[str, dict] = {}
        for name, defaults in DEFAULT_TYPE_PRESETS.items():
            presets[name] = {**defaults, **_explicit(name)}

        # Preserve env-defined content types not built in yet; they inherit the
        # general defaults so a future type works before a code default exists.
        for name, value in raw.items():
            if name not in presets and isinstance(value, dict):
                presets[name] = {**DEFAULT_TYPE_PRESETS["general"], **value}

        book_explicit = _explicit("book")
        presets["book"]["tts_rate"] = book_explicit.get("tts_rate", self.book_tts_rate)
        presets["book"]["segment_pause_seconds"] = book_explicit.get(
            "segment_pause_seconds", self.book_segment_pause_seconds
        )
        presets["book"]["image_hold_seconds"] = book_explicit.get(
            "image_hold_seconds", self.book_image_hold_seconds
        )
        return presets

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
    tts_voice: str = "zh-CN-YunjianNeural"
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

    # Presenter / pen name shown on covers and spoken as the opening greeting.
    # The channel presenter is the pen name 「躺平的老黄」 (never a real name).
    # ``PRESENTER_ENABLED=0`` switches the whole feature off; an individual
    # request can switch it off by sending an empty ``presenter_name``.
    presenter_name: str = "躺平的老黄"
    presenter_enabled: bool = True

    # Video Settings
    video_resolution: str = "1080p"
    video_fps: int = 30

    # Subtitle line width by orientation. Landscape frames are physically wider
    # so they hold more characters than portrait/square ones at the same font size.
    subtitle_max_chars_landscape: int = 26
    subtitle_max_chars_portrait: int = 20

    # Custom per-segment images/charts (``segment_images`` / ``cover_image``):
    # neutral background behind "contain" images (dark charcoal, hex parsed).
    chart_background_color: str = "#16181c"
    # Full-frame ("fullframe") chart layout: the frame fallback colour used when
    # the chart's own border is dark/unreadable (hex parsed), white by default.
    chart_canvas_color: str = "#ffffff"
    # Full-frame subtitle band height at 1080p, scaled by H/1080 (so 130 px at
    # 1080p leaves a 1920x950 chart box).
    chart_fullframe_band_px: int = 130
    # Full-frame subtitle text colour (dark, drawn without a stroke).
    chart_subtitle_dark_color: str = "#1f2329"
    # Bottom band reserved for subtitles on chart segments, as a fraction of the
    # frame height (~130 px at 1080p); the image is contained above it.
    chart_subtitle_band_ratio: float = 0.12
    # Subtitle font size inside the chart band, as a fraction of the frame height.
    chart_subtitle_font_ratio: float = 0.036

    # Agent / security
    api_token: str | None = None  # when set, require Bearer on mutating routes
    cors_origins: str = "*"

    # Scheduler
    enable_scheduler: bool = True  # start APScheduler with the API process
    scheduler_auto_publish: bool = False  # scheduled runs publish to all enabled accounts

    # Publishing
    publish_require_review: bool = True  # only approved videos may be queued for publishing
    # YouTube default privacy when the caller does not specify one. `unlisted` is
    # smoke-test friendly (visible via link, not in public search) while `public`
    # is the growth default once packaging is trusted. Env: YOUTUBE_DEFAULT_PRIVACY.
    youtube_default_privacy: str = "unlisted"
    # Default spoken language for new tasks (zh master; en for YouTube growth).
    default_video_language: str = "zh"
    # External API timeout for blocking operations (Google APIs, etc.)
    external_api_timeout_s: float = 30.0  # fail fast instead of hanging indefinitely

    # Material Source
    pexels_api_key: str | None = None
    pixabay_api_key: str | None = None
    redis_url: str = ""  # e.g. redis://localhost:6379/0 for worker queue
    queue_backend: str = "auto"  # auto | db | redis (see src/queue.py)

    # News pipeline (GNews primary). Free tier is small (~100 req/day, max 10
    # articles) so defaults stay conservative and responses are cached briefly.
    gnews_api_key: str | None = None
    news_api_key: str | None = None  # optional NewsAPI.org key (gnews is primary)
    news_provider: str = "gnews"
    news_lang: str = "zh"
    news_country: str = "cn"
    news_max_articles: int = 5
    news_cache_ttl_s: int = 900  # 15 min in-process cache to save quota

    # Book -> series pipeline (v1: .txt/.md, episodes stored as JSON sidecar)
    book_max_episodes: int = 20  # hard cap when splitting a book
    # Each chapter is trimmed to this many characters before the friendly rewrite.
    # Book episodes target a spoken length of 180-240s (~800-1000 汉字 at the
    # calm default rate), so this must comfortably exceed the script target;
    # 3200 chars is ~4x the old 800.
    book_max_chars: int = 3200
    book_default_episodes_per_call: int = 3  # smoke-friendly batch cap
    # Target spoken length of a book episode in seconds. The prompt char range is
    # derived from this as roughly target +/- 30s (default 180-240s).
    book_target_seconds: int = 210
    # Effective narration rate (汉字/second) of the *final* audio. Already
    # includes the slower book TTS rate and the pauses between segments, so the
    # char range for a default 210s episode is 180*4.0..240*4.0 = 720..960,
    # rounded up to a clean ~800-1000 字 by book_script.book_char_range.
    book_chars_per_second: float = 4.0
    # Calmer narration speed for book episodes (edge-tts rate). Only applied when
    # the request does not explicitly override voice_rate.
    book_tts_rate: str = "-8%"
    # Silence inserted after each book segment (not after the last one) to give
    # the narration room to breathe.
    book_segment_pause_seconds: float = 0.5
    # Stills change about this often; 5.0s keeps a calm, book-like pace instead
    # of the rushed ~4s cadence.
    book_image_hold_seconds: float = 5.0
    book_cover_hold_seconds: float = 3.0
    book_slide_transition_seconds: float = 0.5

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
