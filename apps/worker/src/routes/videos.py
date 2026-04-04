"""Video generation routes."""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from ..config import settings
from ..services.video_service import run_video_generation, video_tasks

logger = logging.getLogger(__name__)

router = APIRouter()


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


@router.post("/generate")
async def generate_video(
    request: VideoGenerateRequest,
    background_tasks: BackgroundTasks,
):
    """Start video generation task."""
    task_uuid = uuid.uuid4().hex
    task_id = f"video-{task_uuid[:8]}"
    
    task_dir = settings.output_dir / task_uuid

    video_tasks[task_id] = {
        "id": task_id,
        "task_uuid": task_uuid,
        "task_dir": str(task_dir),
        "status": "pending",
        "progress": 0.0,
        "current_step": 0,
        "message": "任务已创建，等待开始...",
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
        task_dir,
    )

    return {
        "success": True,
        "data": {
            "id": task_id,
            "task_uuid": task_uuid,
            "task_dir": str(task_dir),
            "status": "pending",
            "message": "视频生成任务已启动",
        },
    }


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """Get video generation task status."""
    if task_id not in video_tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = video_tasks[task_id]
    
    task_dir = Path(task.get("task_dir", ""))
    status_file = task_dir / "status.json"
    
    if status_file.exists():
        with open(status_file, "r", encoding="utf-8") as f:
            file_status = json.load(f)
            task["current_step"] = file_status.get("current_step", 0)
            task["step_name"] = file_status.get("step_name", "")
            task["files"] = file_status.get("files", {})
    
    return {
        "success": True,
        "data": task,
    }


@router.get("/tasks/{task_id}/log")
async def get_task_log(task_id: str):
    """Get task log content."""
    if task_id not in video_tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = video_tasks[task_id]
    log_file = Path(task.get("task_dir", "")) / "task.log"
    
    if not log_file.exists():
        return {"success": True, "data": {"log": ""}}
    
    with open(log_file, "r", encoding="utf-8") as f:
        log_content = f.read()
    
    return {
        "success": True,
        "data": {"log": log_content},
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