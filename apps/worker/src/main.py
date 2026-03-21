"""FastAPI main application for Video Factory Worker."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import init_db
from .routes import ai_settings, runs, sources, tasks, tts_settings

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
    yield
    logger.info("Shutting down Video Factory Worker...")


app = FastAPI(
    title="Video Factory Worker",
    description="Video generation and publishing service",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(sources.router, prefix="/api/sources", tags=["sources"])
app.include_router(runs.router, prefix="/api/runs", tags=["runs"])
app.include_router(ai_settings.router, prefix="/api/ai-settings", tags=["ai-settings"])
app.include_router(tts_settings.router, prefix="/api/tts-settings", tags=["tts-settings"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "Video Factory Worker API", "version": "0.1.0"}


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )