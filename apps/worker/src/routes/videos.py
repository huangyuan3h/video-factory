"""Video generation routes."""

import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from ..config import settings
from ..core.video_generator import VideoGenerator, VideoOptions

logger = logging.getLogger(__name__)

router = APIRouter()

video_tasks: dict[str, dict] = {}


class VideoGenerateRequest(BaseModel):
    """Request model for video generation."""

    title: str
    system_prompt: str = ""
    text_content: str
    background_music: str | None = None
    generate_subtitle: bool = True
    subtitle_color: str = "&H00FFFFFF"
    subtitle_font: str = "Microsoft YaHei"
    voice: str = "zh-CN-XiaoxiaoNeural"
    voice_rate: str = "+0%"
    background_source: str = "both"
    resolution_width: int = 1080
    resolution_height: int = 1920


def run_video_generation(
    task_id: str,
    request: VideoGenerateRequest,
):
    """Run video generation in background."""

    async def _generate():
        try:
            video_tasks[task_id]["status"] = "processing"
            video_tasks[task_id]["progress"] = 0.0
            video_tasks[task_id]["message"] = "Starting video generation..."

            video_generator = VideoGenerator()

            bg_music_path = None
            if request.background_music:
                music_path = Path(request.background_music)
                if music_path.exists():
                    bg_music_path = music_path
                elif (settings.assets_dir / "music" / request.background_music).exists():
                    bg_music_path = settings.assets_dir / "music" / request.background_music

            options = VideoOptions(
                voice=request.voice,
                voice_rate=request.voice_rate,
                resolution=(request.resolution_width, request.resolution_height),
                material_source=request.background_source,
                subtitle_style={
                    "font_name": request.subtitle_font,
                    "font_size": 48,
                    "color": request.subtitle_color,
                    "outline_color": "&H00000000",
                },
            )

            async def progress_callback(step: str, progress: float):
                video_tasks[task_id]["progress"] = progress
                video_tasks[task_id]["message"] = step

            video_path = await video_generator.generate(
                content=request.text_content,
                title=request.title,
                system_prompt=request.system_prompt or "",
                background_music_path=bg_music_path,
                options=options,
                progress_callback=progress_callback,
            )

            video_tasks[task_id]["status"] = "completed"
            video_tasks[task_id]["progress"] = 1.0
            video_tasks[task_id]["message"] = "Video generation completed"
            video_tasks[task_id]["video_path"] = str(video_path)
            video_tasks[task_id]["completed_at"] = datetime.now().isoformat()

        except Exception as e:
            logger.error(f"Video generation failed for task {task_id}: {e}")
            video_tasks[task_id]["status"] = "failed"
            video_tasks[task_id]["message"] = str(e)
            video_tasks[task_id]["error"] = str(e)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_generate())
    finally:
        loop.close()


@router.post("/generate")
async def generate_video(
    request: VideoGenerateRequest,
    background_tasks: BackgroundTasks,
):
    """Start video generation task."""
    task_id = f"video-{uuid.uuid4().hex[:8]}"

    video_tasks[task_id] = {
        "id": task_id,
        "status": "pending",
        "progress": 0.0,
        "message": "Task created, waiting to start...",
        "created_at": datetime.now().isoformat(),
        "request": {
            "title": request.title,
            "has_background_music": bool(request.background_music),
            "voice": request.voice,
        },
    }

    background_tasks.add_task(
        run_video_generation,
        task_id,
        request,
    )

    return {
        "success": True,
        "data": {
            "id": task_id,
            "status": "pending",
            "message": "Video generation task started",
        },
    }


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """Get video generation task status."""
    if task_id not in video_tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = video_tasks[task_id]
    return {
        "success": True,
        "data": task,
    }


@router.get("/tasks")
async def list_tasks():
    """List all video generation tasks."""
    return {
        "success": True,
        "data": list(video_tasks.values()),
    }


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    """Delete a video generation task."""
    if task_id not in video_tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    del video_tasks[task_id]
    return {
        "success": True,
        "message": "Task deleted",
    }
