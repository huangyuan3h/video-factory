"""Video generation routes — single minimal API.

POST /api/videos/generate  title + content required, rest optional.
Default: landscape 1920x1080 (desktop).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import AliasChoices, BaseModel, Field, model_validator

from ..config import settings
from ..queue import enqueue, queue_depth
from ..services.video_service import run_video_generation, video_tasks

logger = logging.getLogger(__name__)

router = APIRouter()


# Presets: keep lookup lowercase
PRESETS: dict[str, tuple[int, int]] = {
    "landscape": (1920, 1080),
    "portrait": (1080, 1920),
    "square": (1080, 1080),
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "4:3": (1440, 1080),
    "21:9": (1920, 822),
}


def resolve_resolution(
    resolution: str | None,
    orientation: str | None,
    aspect_ratio: str | None,
    w: int | None,
    h: int | None,
) -> tuple[int, int]:
    """Resolve final (width, height). Priority: explicit w/h > preset > orientation/aspect > default landscape."""
    if w is not None and h is not None:
        return (int(w), int(h))
    if w is not None or h is not None:
        # If only one side given, infer from default aspect
        if w is not None:
            return (int(w), int(w * 1080 / 1920))
        return (int(h * 1920 / 1080), int(h))
    # single string preset (resolution field)
    if resolution:
        key = resolution.strip().lower()
        if key in PRESETS:
            return PRESETS[key]
        # allow "1920x1080" freeform
        if "x" in key:
            try:
                a, b = key.split("x", 1)
                return (int(a), int(b))
            except Exception:
                pass
    if aspect_ratio and aspect_ratio.strip().lower() in PRESETS:
        return PRESETS[aspect_ratio.strip().lower()]
    if orientation:
        o = orientation.strip().lower()
        if o in PRESETS:
            return PRESETS[o]
        if o == "horizontal":
            return PRESETS["landscape"]
        if o == "vertical":
            return PRESETS["portrait"]
    # default: landscape for desktop as requested
    return PRESETS["landscape"]


class VideoGenerateRequest(BaseModel):
    """Single video generation request — only title & content required."""

    model_config = {"populate_by_name": True, "extra": "ignore"}

    # Required
    title: str = Field(..., min_length=1, max_length=200, description="Video title")
    # content accepts multiple aliases: content / text_content / textContent / text
    content: str = Field(
        ...,
        min_length=1,
        max_length=20000,
        validation_alias=AliasChoices("content", "text_content", "textContent", "text"),
        description="Main text content to generate video from",
    )

    # Optional — diverse knobs
    system_prompt: str | None = Field(default="", validation_alias=AliasChoices("system_prompt", "systemPrompt"))
    # LLM rewrite
    rewrite_content: bool = Field(default=False, validation_alias=AliasChoices("rewrite_content", "rewriteContent", "optimize", "optimize_content", "optimizeContent", "llm_optimize"))
    rewrite_prompt: str | None = Field(default=None, validation_alias=AliasChoices("rewrite_prompt", "rewritePrompt", "optimize_prompt"))
    voice: str = Field(default="zh-CN-XiaoxiaoNeural")
    voice_rate: str = Field(default="+0%", validation_alias=AliasChoices("voice_rate", "voiceRate"))
    background_source: str = Field(default="both", validation_alias=AliasChoices("background_source", "backgroundSource"))
    background_music: str | None = Field(default=None, validation_alias=AliasChoices("background_music", "backgroundMusic"))
    generate_subtitle: bool = Field(default=True, validation_alias=AliasChoices("generate_subtitle", "generateSubtitle"))
    subtitle_color: str = Field(default="&H00FFFFFF", validation_alias=AliasChoices("subtitle_color", "subtitleColor"))
    subtitle_font: str = Field(default="Microsoft YaHei", validation_alias=AliasChoices("subtitle_font", "subtitleFont"))
    subtitle_style: dict | None = None
    # Resolution control — flexible
    resolution: str | None = Field(default=None, description="Preset: landscape/portrait/square/16:9/9:16/1:1 or '1920x1080'")
    orientation: Literal["landscape", "portrait", "square"] | str | None = None
    aspect_ratio: str | None = Field(default=None, validation_alias=AliasChoices("aspect_ratio", "aspectRatio"))
    resolution_width: int | None = Field(default=None, validation_alias=AliasChoices("resolution_width", "resolutionWidth", "width"))
    resolution_height: int | None = Field(default=None, validation_alias=AliasChoices("resolution_height", "resolutionHeight", "height"))
    fps: int = Field(default=30, ge=15, le=60)
    generate_cover: bool = Field(default=True, validation_alias=AliasChoices("generate_cover", "generateCover"))
    # Auto-publish — extensible
    publish_to: list[str] | None = Field(default=None, validation_alias=AliasChoices("publish_to", "publishTo", "platforms"), description="Auto-publish platforms: youtube,douyin,xiaohongshu")
    folder_id: str | None = Field(default=None, validation_alias=AliasChoices("folder_id", "folderId", "playlist_id", "playlistId"))
    folder_name: str | None = Field(default=None, validation_alias=AliasChoices("folder_name", "folderName"))
    publish_privacy: str | None = Field(default=None, validation_alias=AliasChoices("publish_privacy", "privacy"))

    @model_validator(mode="after")
    def _check_content(self):
        # Already required via Field(...), but keep friendly error when empty string
        if not (self.content or "").strip():
            raise ValueError("content / text_content is required and cannot be empty")
        return self

    @property
    def text_content(self) -> str:
        return self.content

    def resolved_resolution(self) -> tuple[int, int]:
        return resolve_resolution(
            self.resolution, self.orientation, self.aspect_ratio, self.resolution_width, self.resolution_height
        )


def _task_response(task_id: str, task_uuid: str, task_dir: Path, rw: int, rh: int) -> dict:
    return {
        "id": task_id,
        "task_uuid": task_uuid,
        "task_dir": str(task_dir),
        "status": "pending",
        "message": "视频生成任务已启动",
        "resolution": {"width": rw, "height": rh},
        "orientation": "landscape" if rw > rh else "portrait" if rh > rw else "square",
    }


@router.post("/generate")
async def generate_video(
    request: VideoGenerateRequest,
    background_tasks: BackgroundTasks,
):
    """Start video generation — minimal required: title + content."""
    rw, rh = request.resolved_resolution()
    task_uuid = uuid.uuid4().hex
    task_id = f"video-{task_uuid[:8]}"
    task_dir = settings.output_dir / task_uuid

    # Store canonical resolved resolution back onto request for worker
    request.resolution_width = rw
    request.resolution_height = rh

    video_tasks[task_id] = {
        "id": task_id,
        "task_uuid": task_uuid,
        "task_dir": str(task_dir),
        "status": "pending",
        "progress": 0.0,
        "current_step": 0,
        "message": "任务已创建，等待开始...",
        "created_at": datetime.now().isoformat(),
        "resolution": {"width": rw, "height": rh},
        "orientation": "landscape" if rw > rh else "portrait" if rh > rw else "square",
        "request": {
            "title": request.title,
            "has_background_music": bool(request.background_music),
            "voice": request.voice,
            "resolution": f"{rw}x{rh}",
        },
    }

    # Try queue first (worker independent), fallback to BackgroundTasks for dev without Redis
    job = {
        "task_id": task_id,
        "task_uuid": task_uuid,
        "task_dir": str(task_dir),
        "request": request.model_dump(),
        "created_at": video_tasks[task_id]["created_at"],
    }
    queued = enqueue(job)
    if queued:
        video_tasks[task_id]["queued"] = True
        video_tasks[task_id]["queue_depth"] = queue_depth()
        logger.info(f"Enqueued {task_id} depth={queue_depth()}")
    else:
        background_tasks.add_task(run_video_generation, task_id, request, task_dir)

    return {
        "success": True,
        "data": {**_task_response(task_id, task_uuid, task_dir, rw, rh), "queued": queued, "queue_depth": queue_depth()},
    }


# Alias: POST /api/videos  (without /generate) for even simpler agent UX
@router.post("")
async def generate_video_alias(request: VideoGenerateRequest, background_tasks: BackgroundTasks):
    return await generate_video(request, background_tasks)


def _enrich_task(task: dict) -> dict:
    """Inject files derived from task_dir/status.json if present."""
    task_dir = Path(task.get("task_dir", ""))
    status_file = task_dir / "status.json"
    if status_file.exists():
        try:
            with open(status_file, "r", encoding="utf-8") as f:
                file_status = json.load(f)
            task["current_step"] = file_status.get("current_step", task.get("current_step", 0))
            task["step_name"] = file_status.get("step_name", task.get("step_name", ""))
            task["files"] = file_status.get("files", {})
            files = task["files"] or {}
            task["video_path"] = files.get("video") or task.get("video_path")
            task["subtitle_path"] = files.get("subtitles")
            task["cover_path"] = files.get("cover")
            task["script_path"] = files.get("script")
            # Build download URLs for agent convenience
            tid = task.get("id")
            if tid:
                task["download_urls"] = {
                    "video": f"/api/videos/tasks/{tid}/download?kind=video",
                    "cover": f"/api/videos/tasks/{tid}/download?kind=cover",
                    "subtitle": f"/api/videos/tasks/{tid}/download?kind=subtitle",
                    "script": f"/api/videos/tasks/{tid}/download?kind=script",
                }
        except Exception:
            pass
    if "resolution" not in task and task.get("request", {}).get("resolution"):
        try:
            w, h = task["request"]["resolution"].split("x")
            task["resolution"] = {"width": int(w), "height": int(h)}
        except Exception:
            pass
    # Ensure files dict always present for frontend
    task.setdefault("files", {})
    task.setdefault("download_urls", {})
    return task


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    if task_id not in video_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    task = _enrich_task(dict(video_tasks[task_id]))
    return {"success": True, "data": task}


@router.get("/tasks/{task_id}/log")
async def get_task_log(task_id: str):
    if task_id not in video_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    task = video_tasks[task_id]
    log_file = Path(task.get("task_dir", "")) / "task.log"
    if not log_file.exists():
        return {"success": True, "data": {"log": ""}}
    with open(log_file, "r", encoding="utf-8") as f:
        log_content = f.read()
    return {"success": True, "data": {"log": log_content}}


@router.get("/tasks")
async def list_tasks():
    return {"success": True, "data": [_enrich_task(dict(v)) for v in video_tasks.values()]}


@router.get("/tasks/{task_id}/download")
async def download_task_file(task_id: str, kind: str = Query(default="video", description="video|cover|subtitle|script")):
    """Download generated file for a task — used for acceptance and agent retrieval."""
    if task_id not in video_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    task = _enrich_task(dict(video_tasks[task_id]))
    files: dict = task.get("files", {}) or {}
    # Map kind to file key
    key_map = {"video": "video", "cover": "cover", "subtitle": "subtitles", "subtitles": "subtitles", "script": "script"}
    file_key = key_map.get(kind.lower(), kind)
    path_str = files.get(file_key)
    # Fallback: direct video_path fields
    if not path_str:
        path_str = task.get("video_path") if kind == "video" else task.get(f"{kind}_path") or task.get(f"{file_key}_path")
    if not path_str:
        raise HTTPException(status_code=404, detail=f"File not found for kind={kind}. Task may still be processing.")
    p = Path(path_str)
    if not p.exists():
        # Try alternative locations within task_dir
        task_dir = Path(task.get("task_dir", ""))
        alt = task_dir / p.name
        if alt.exists():
            p = alt
        else:
            raise HTTPException(status_code=404, detail=f"File missing on disk: {p.name}")
    media = "video/mp4" if p.suffix == ".mp4" else "image/png" if p.suffix == ".png" else "text/plain" if p.suffix in (".ass", ".srt") else "application/json" if p.suffix == ".json" else "application/octet-stream"
    return FileResponse(path=p, media_type=media, filename=p.name)


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    if task_id not in video_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    del video_tasks[task_id]
    return {"success": True, "message": "Task deleted"}
