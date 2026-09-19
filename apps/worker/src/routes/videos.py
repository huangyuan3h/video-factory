"""Video generation routes — single minimal API.

POST /api/videos/generate  title + content required, rest optional.
Default: landscape 1920x1080 (desktop).
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import AliasChoices, BaseModel, Field, model_validator
from sqlalchemy import select

from ..config import settings
from ..queue import enqueue, enqueue_publish_jobs, queue_depth, request_cancel as queue_request_cancel
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
    """Single video generation request.

    General pipeline: title + content required.
    News pipeline (`type=news`): title/content optional; articles are fetched
    from GNews using `news_query` (or title/content as a search seed).
    """

    model_config = {"populate_by_name": True, "extra": "ignore"}

    # Pipeline selector — "general" (default) or "news"
    content_type: str = Field(
        default="general",
        validation_alias=AliasChoices("type", "content_type", "contentType", "content-type"),
        description="Pipeline selector: 'general' (default) or 'news'",
    )

    # Required for general; optional for news (fetched from GNews)
    title: str | None = Field(default=None, max_length=200, description="Video title")
    # content accepts multiple aliases: content / text_content / textContent / text
    content: str | None = Field(
        default=None,
        max_length=20000,
        validation_alias=AliasChoices("content", "text_content", "textContent", "text"),
        description="Main text content to generate video from",
    )

    # News pipeline options (GNews free tier)
    news_query: str | None = Field(
        default=None, validation_alias=AliasChoices("news_query", "newsQuery", "q")
    )
    news_provider: str = Field(
        default="gnews", validation_alias=AliasChoices("news_provider", "newsProvider")
    )
    news_lang: str | None = Field(
        default=None, validation_alias=AliasChoices("news_lang", "newsLang", "lang")
    )
    news_country: str | None = Field(
        default=None, validation_alias=AliasChoices("news_country", "newsCountry")
    )
    news_max_articles: int = Field(
        default=5,
        ge=1,
        le=10,
        validation_alias=AliasChoices("news_max_articles", "newsMaxArticles", "news_max", "newsMax"),
    )

    # Optional — series grouping
    series_id: str | None = Field(default=None, validation_alias=AliasChoices("series_id", "seriesId"))

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
        if self.is_news():
            # News pipeline can source everything from GNews; require a hint.
            if not any([
                (self.news_query or "").strip(),
                (self.title or "").strip(),
                (self.content or "").strip(),
            ]):
                raise ValueError("news request requires one of: news_query, title, content")
            return self
        if not (self.title or "").strip():
            raise ValueError("title is required and cannot be empty")
        if not (self.content or "").strip():
            raise ValueError("content / text_content is required and cannot be empty")
        return self

    def is_news(self) -> bool:
        """True when the news pipeline should be used."""
        return str(self.content_type or "").strip().lower() == "news"

    @property
    def text_content(self) -> str:
        return self.content or ""

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


async def _get_series(series_id: str):
    """Look up a Series row (returns None when missing)."""
    from ..database import async_session_maker
    from ..models import Series

    async with async_session_maker() as session:
        return await session.get(Series, series_id)


@router.post("/generate")
async def generate_video(
    request: VideoGenerateRequest,
    background_tasks: BackgroundTasks,
):
    """Start video generation — minimal required: title + content."""
    rw, rh = request.resolved_resolution()
    task_uuid = uuid.uuid4().hex
    task_id = f"video-{task_uuid[:8]}"

    # Resolve optional series -> output folder (series slug, or _unsorted)
    series = None
    if request.series_id:
        series = await _get_series(request.series_id)
        if not series:
            raise HTTPException(status_code=404, detail="Series not found")
    if series and getattr(settings, "series_output_folders", True):
        task_dir = settings.output_dir / series.slug / task_uuid
    else:
        task_dir = settings.output_dir / "_unsorted" / task_uuid

    # Store canonical resolved resolution back onto request for worker
    request.resolution_width = rw
    request.resolution_height = rh

    video_tasks[task_id] = {
        "id": task_id,
        "task_uuid": task_uuid,
        "series_id": series.id if series else None,
        "series_name": series.name if series else None,
        "series_slug": series.slug if series else None,
        "task_dir": str(task_dir),
        "status": "pending",
        "progress": 0.0,
        "current_step": 0,
        "message": "任务已创建，等待开始...",
        "created_at": datetime.now().isoformat(),
        "resolution": {"width": rw, "height": rh},
        "orientation": "landscape" if rw > rh else "portrait" if rh > rw else "square",
        "content_type": request.content_type,
        "source_name": None,
        "source_url": None,
        "request": {
            "title": request.title,
            "content_type": request.content_type,
            "has_background_music": bool(request.background_music),
            "voice": request.voice,
            "resolution": f"{rw}x{rh}",
        },
        "payload": request.model_dump(),
    }

    # Try queue first (worker independent), fallback to BackgroundTasks for dev without Redis
    job = {
        "task_id": task_id,
        "task_uuid": task_uuid,
        "series_id": series.id if series else None,
        "task_dir": str(task_dir),
        "request": request.model_dump(),
        "created_at": video_tasks[task_id]["created_at"],
    }
    queued = await enqueue(job)
    if queued:
        depth = await queue_depth()
        video_tasks[task_id]["queued"] = True
        video_tasks[task_id]["queue_backend"] = queued
        video_tasks[task_id]["queue_depth"] = depth
        logger.info(f"Enqueued {task_id} via {queued} depth={depth}")
    else:
        background_tasks.add_task(run_video_generation, task_id, request, task_dir)

    depth = await queue_depth() if queued else 0
    return {
        "success": True,
        "data": {**_task_response(task_id, task_uuid, task_dir, rw, rh), "content_type": request.content_type, "queued": bool(queued), "queue_backend": queued, "queue_depth": depth},
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
            # Disk status is the source of truth (worker may run in another process)
            for key in ("status", "progress", "message", "error", "completed_at", "series_id", "review_status", "review_note", "content_type", "source_name", "source_url", "news_articles"):
                if file_status.get(key) is not None:
                    task[key] = file_status[key]
            task.setdefault("review_status", "draft")
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
async def list_tasks(series_id: str | None = None):
    """List generation tasks, optionally filtered by series."""
    tasks = list(video_tasks.values())
    if series_id:
        tasks = [v for v in tasks if v.get("series_id") == series_id]
    return {"success": True, "data": [_enrich_task(dict(v)) for v in tasks]}


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    """Request cancellation — drops a flag file and marks the DB job."""
    if task_id not in video_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    task = video_tasks[task_id]
    task_dir = Path(task.get("task_dir", ""))
    try:
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "cancel.flag").write_text("cancelled", encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to write cancel flag for {task_id}: {e}")
    try:
        await queue_request_cancel(task_id)
    except Exception:
        pass
    if task.get("status") in ("pending",):
        task["status"] = "cancelled"
        task["message"] = "任务已取消"
    else:
        task["message"] = "正在取消..."
    return {"success": True, "data": {"id": task_id, "status": task.get("status")}}


@router.post("/tasks/{task_id}/retry")
async def retry_task(task_id: str, background_tasks: BackgroundTasks):
    """Re-run a task using its stored payload (creates a new task)."""
    if task_id not in video_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    payload = video_tasks[task_id].get("payload")
    if not payload:
        raise HTTPException(status_code=400, detail="任务缺少原始请求，无法重试")
    try:
        request = VideoGenerateRequest.model_validate(payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"原始请求无效: {e}")
    return await generate_video(request, background_tasks)


class ReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = None


class PublishTaskRequest(BaseModel):
    account_id: str | None = None
    account_ids: list[str] | None = None
    platforms: list[str] | None = None
    folder_id: str | None = None
    title: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    privacy: str | None = None


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def _update_status_file(task_dir: Path, updates: dict):
    status_file = task_dir / "status.json"
    try:
        data = json.loads(status_file.read_text(encoding="utf-8")) if status_file.exists() else {}
        data.update(updates)
        status_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to update status.json in {task_dir}: {e}")


async def _resolve_targets(session, task: dict, data: "PublishTaskRequest") -> list[dict]:
    """Resolve which accounts/platforms to publish to (explicit > series targets)."""
    from ..models import PublisherAccount, SeriesPublishTarget

    targets: list[dict] = []
    account_ids = list(data.account_ids or [])
    if data.account_id:
        account_ids.append(data.account_id)

    if account_ids:
        for aid in account_ids:
            acc = await session.get(PublisherAccount, aid)
            if acc and acc.enabled:
                targets.append({"account_id": acc.id, "platform": acc.platform, "folder_id": data.folder_id or acc.folder_id})
    elif data.platforms:
        for platform in data.platforms:
            key = (platform or "").lower().strip()
            res = await session.execute(
                select(PublisherAccount)
                .where(PublisherAccount.platform == key, PublisherAccount.enabled == True)
                .limit(1)
            )
            acc = res.scalars().first()
            if acc:
                targets.append({"account_id": acc.id, "platform": acc.platform, "folder_id": data.folder_id or acc.folder_id})
    elif task.get("series_id"):
        res = await session.execute(
            select(SeriesPublishTarget).where(
                SeriesPublishTarget.series_id == task["series_id"],
                SeriesPublishTarget.enabled == True,
            )
        )
        for t in res.scalars().all():
            if t.account_id:
                targets.append({"account_id": t.account_id, "platform": t.platform, "folder_id": data.folder_id or t.folder_id})
    return targets


@router.post("/tasks/{task_id}/review")
async def review_task(task_id: str, data: ReviewRequest):
    """Approve or reject a generated video before publishing."""
    if task_id not in video_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    task = video_tasks[task_id]
    enriched = _enrich_task(dict(task))
    if enriched.get("status") != "completed":
        raise HTTPException(status_code=400, detail="只有已完成的视频可以审核")
    reviewed = "approved" if data.decision == "approve" else "rejected"
    task["review_status"] = reviewed
    _update_status_file(Path(task.get("task_dir", "")), {"review_status": reviewed, "review_note": data.note})
    return {"success": True, "data": {"id": task_id, "review_status": reviewed}}


@router.post("/tasks/{task_id}/publish")
async def publish_task(task_id: str, data: PublishTaskRequest):
    """Queue publishing of a completed (and ideally approved) video."""
    if task_id not in video_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    task = video_tasks[task_id]
    enriched = _enrich_task(dict(task))
    if enriched.get("status") != "completed":
        raise HTTPException(status_code=400, detail="视频尚未生成完成")
    if getattr(settings, "publish_require_review", True) and enriched.get("review_status") != "approved":
        raise HTTPException(status_code=400, detail="视频尚未审核通过，请先审核")

    from ..database import async_session_maker

    async with async_session_maker() as session:
        targets = await _resolve_targets(session, task, data)
    if not targets:
        raise HTTPException(status_code=400, detail="没有可用的发布目标（账号或系列发布目标）")

    title = data.title or enriched.get("request", {}).get("title") or "Video"
    jobs = [
        {
            "id": _new_id(),
            "task_id": task_id,
            "series_id": task.get("series_id"),
            "video_path": enriched.get("video_path"),
            "task_dir": task.get("task_dir"),
            "account_id": t["account_id"],
            "platform": t["platform"],
            "title": title,
            "description": data.description,
            "tags_json": json.dumps(data.tags, ensure_ascii=False) if data.tags else None,
            "folder_id": t.get("folder_id"),
            "privacy": data.privacy,
        }
        for t in targets
    ]
    created = await enqueue_publish_jobs(jobs)
    return {"success": True, "data": {"queued": created, "jobs": [j["id"] for j in jobs]}}


@router.get("/tasks/{task_id}/publish")
async def list_task_publish_jobs(task_id: str):
    """List publish jobs for a task."""
    from ..database import async_session_maker
    from ..models import PublishJob

    async with async_session_maker() as session:
        result = await session.execute(
            select(PublishJob).where(PublishJob.task_id == task_id).order_by(PublishJob.created_at)
        )
        jobs = [
            {
                "id": j.id,
                "platform": j.platform,
                "account_id": j.account_id,
                "status": j.status,
                "post_url": j.post_url,
                "post_id": j.post_id,
                "error": j.error,
                "attempts": j.attempts,
                "created_at": j.created_at.isoformat() if j.created_at else None,
            }
            for j in result.scalars().all()
        ]
    return {"success": True, "data": jobs}


@router.get("/events")
async def task_events(request: Request):
    """Server-Sent Events stream of all generation tasks (for live UI updates)."""

    async def event_generator():
        last_payload: str | None = None
        while True:
            if await request.is_disconnected():
                break
            data = [_enrich_task(dict(v)) for v in video_tasks.values()]
            payload = json.dumps({"success": True, "data": data}, ensure_ascii=False, default=str)
            if payload != last_payload:
                last_payload = payload
                yield f"data: {payload}\n\n"
            else:
                yield ": keep-alive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


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
