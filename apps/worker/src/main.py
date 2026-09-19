"""FastAPI main application for Video Factory Worker."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fastapi import Request
from fastapi.responses import JSONResponse

from .config import settings
from .database import init_db
from .routes import ai_settings, general_settings, publishers, publishing, runs, series, sources, synthetic, system_prompts, tasks, tts_settings, videos

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Starting Video Factory Worker...")
    await init_db()
    logger.info("Database initialized")
    if settings.enable_scheduler:
        try:
            from .scheduler import init_scheduler

            await init_scheduler()
        except Exception as e:
            logger.error(f"Scheduler failed to start: {e}")
    yield
    logger.info("Shutting down Video Factory Worker...")
    if settings.enable_scheduler:
        try:
            from .scheduler import shutdown_scheduler

            await shutdown_scheduler()
        except Exception:
            pass


app = FastAPI(
    title="Video Factory Worker",
    description="Video generation and publishing service",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware — supports wildcard or comma-separated list via settings
_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()] if settings.cors_origins != "*" else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def api_token_guard(request: Request, call_next):
    # Enforce Bearer token on mutating API routes when configured
    if settings.api_token and request.url.path.startswith("/api/"):
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            auth = request.headers.get("authorization", "")
            if auth != f"Bearer {settings.api_token}":
                return JSONResponse(status_code=401, content={"success": False, "error": "Unauthorized: invalid API token"})
    return await call_next(request)

# Include routers
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(sources.router, prefix="/api/sources", tags=["sources"])
app.include_router(runs.router, prefix="/api/runs", tags=["runs"])
app.include_router(ai_settings.router, prefix="/api/ai-settings", tags=["ai-settings"])
app.include_router(tts_settings.router, prefix="/api/tts-settings", tags=["tts-settings"])
app.include_router(videos.router, prefix="/api/videos", tags=["videos"])
app.include_router(series.router, prefix="/api/series", tags=["series"])
app.include_router(publishing.router, prefix="/api/publish", tags=["publishing"])
app.include_router(publishers.router, prefix="/api/publishers", tags=["publishers"])
# Alias for agent convenience: also expose videos publish
app.include_router(publishers.router, prefix="/api/videos/publishers", tags=["publishers"])
app.include_router(synthetic.router, prefix="/api/synthetic", tags=["synthetic"])
app.include_router(general_settings.router, prefix="/api/settings", tags=["settings"])
app.include_router(system_prompts.router, prefix="/api/system-prompts", tags=["system-prompts"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "Video Factory Worker API", "version": "0.1.0"}


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/ready")
async def readiness_check():
    """Readiness endpoint for orchestrators / agents."""
    # Minimal liveness: DB file reachable and TTS config readable
    return {
        "status": "ready",
        "version": "0.1.0",
        "tts": {
            "local_configured": bool((settings.vllm_tts_url or settings.vllm_tts_hq_url or "").strip()),
            "voice": settings.tts_voice,
        },
    }


@app.get("/api/capabilities")
async def capabilities():
    """Machine-readable capabilities for AI agents."""
    return {
        "name": "video-factory",
        "version": "0.1.0",
        "description": "Automated video generation and publishing factory",
        "endpoints": {
            "generate_video": {
                "path": "/api/videos/generate",
                "alias": "/api/videos",
                "method": "POST",
                "required": ["title", "content"],
                "optional": [
                    "type/content_type (general|news|book)",
                    "systemPrompt",
                    "rewrite_content/rewritePrompt (bool+prompt)",
                    "voice",
                    "voiceRate",
                    "backgroundSource",
                    "backgroundMusic",
                    "resolution (landscape|portrait|square|1920x1080|16:9...)",
                    "orientation",
                    "aspectRatio",
                    "resolutionWidth/resolutionHeight",
                    "fps",
                    "generateSubtitle",
                    "subtitleColor/subtitleFont",
                    "generateCover",
                    "publish_to (youtube,douyin,xiaohongshu)",
                    "folder_id/playlist_id/publish_privacy",
                ],
                "example": {"title": "今日AI头条", "content": "今天发生了...", "rewrite_content": True, "publish_to": ["youtube"]},
                "defaults": {"type": "general", "resolution": "1920x1080 landscape", "voice": "zh-CN-XiaoxiaoNeural", "backgroundSource": "both (book: online)", "timeline": "per-segment 10s/theme"},
            },
            "task_status": "/api/videos/tasks/{task_id}",
            "task_download": "/api/videos/tasks/{task_id}/download?kind=video|cover|subtitle|script",
            "publish": "/api/publishers/{id}/publish + /api/videos/tasks/{id}/publish (auto via publish_to)",
            "publish_folders": "/api/publishers/{id}/folders (list/create)",
            "series_from_book": {
                "path": "/api/series/from-book",
                "method": "POST",
                "content_type": "multipart/form-data (file=.txt/.md/.markdown/.pdf, title) or application/json ({title,text})",
                "notes": "Creates a series and splits the book into episodes.",
            },
            "series_import_book": "/api/series/{series_id}/import-book (POST)",
            "series_episodes": "/api/series/{series_id}/episodes (GET)",
            "series_generate_episodes": {
                "path": "/api/series/{series_id}/generate-episodes",
                "method": "POST",
                "query": {"limit": 3, "start": 1, "background_source": "online", "resolution": "portrait", "content_type": "book"},
            },
            "tasks": "/api/tasks",
            "sources": "/api/sources",
            "runs": "/api/runs",
            "tts_speak": "/api/tts-settings/speak",
            "tts_speak_stream": "/api/tts-settings/speak-stream",
            "synthetic_status": "/api/synthetic/status",
            "synthetic_video_status": "/api/synthetic/video/status",
        },
        "features": {
            "tts_providers": ["edge-tts", "local-openai-compatible"],
            "tts_streaming": True,
            "voice_cloning": bool((settings.vllm_tts_hq_url or "").strip()),
            "material_sources": ["pexels", "pixabay", "local_assets"]
            + (["synthetic(comfyui)"] if getattr(settings, "enable_synthetic", False) else [])
            + (["synthetic_video(comfyui)"] if getattr(settings, "enable_synthetic_video", False) else []),
            "synthetic_enabled": bool(getattr(settings, "enable_synthetic", False)),
            "synthetic_video_enabled": bool(getattr(settings, "enable_synthetic_video", False)),
            "default_resolution": "1920x1080 landscape",
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
