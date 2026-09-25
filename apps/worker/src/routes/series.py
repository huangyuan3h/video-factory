"""Series management routes."""

import hashlib
import json
import re
import time
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_session
from ..models import Series, SeriesPublishTarget
from ..schemas import ApiResponse, SeriesCreate, SeriesResponse, SeriesUpdate
from ..services import book_service

router = APIRouter()

_SLUG_STRIP = re.compile(r"[^\w-]+", re.UNICODE)


class TargetCreate(BaseModel):
    platform: str
    account_id: str | None = None
    folder_id: str | None = None
    folder_name: str | None = None
    enabled: bool = True


def _target_to_dict(t: SeriesPublishTarget) -> dict:
    return {
        "id": t.id,
        "series_id": t.series_id,
        "platform": t.platform,
        "account_id": t.account_id,
        "folder_id": t.folder_id,
        "folder_name": t.folder_name,
        "enabled": t.enabled,
    }


def generate_id() -> str:
    """Generate a unique ID."""
    return hashlib.md5(f"{time.time()}-{id(object())}".encode()).hexdigest()[:16]


def slugify(name: str, fallback: str) -> str:
    """Filesystem-safe slug that keeps CJK characters."""
    slug = _SLUG_STRIP.sub("-", (name or "").strip()).strip("-").lower()
    slug = re.sub(r"-{2,}", "-", slug)
    return (slug or fallback)[:120]


async def _unique_slug(session: AsyncSession, base: str, exclude_id: str | None = None) -> str:
    slug = base
    suffix = 2
    while True:
        query = select(Series).where(Series.slug == slug)
        if exclude_id:
            query = query.where(Series.id != exclude_id)
        existing = (await session.execute(query)).scalar_one_or_none()
        if not existing:
            return slug
        slug = f"{base}-{suffix}"
        suffix += 1


@router.get("", response_model=ApiResponse[list[SeriesResponse]])
async def list_series(session: AsyncSession = Depends(get_session)):
    """List all series."""
    result = await session.execute(select(Series).order_by(Series.created_at.desc()))
    return ApiResponse(success=True, data=[SeriesResponse.model_validate(s) for s in result.scalars().all()])


@router.get("/{series_id}", response_model=ApiResponse[SeriesResponse])
async def get_series(series_id: str, session: AsyncSession = Depends(get_session)):
    """Get a series by ID."""
    series = await session.get(Series, series_id)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")
    return ApiResponse(success=True, data=SeriesResponse.model_validate(series))


@router.post("", response_model=ApiResponse[SeriesResponse])
async def create_series(data: SeriesCreate, session: AsyncSession = Depends(get_session)):
    """Create a series."""
    series_id = generate_id()
    base_slug = slugify(data.slug or data.name, f"series-{series_id}")
    slug = await _unique_slug(session, base_slug)
    payload = data.model_dump(exclude={"slug"})
    series = Series(id=series_id, slug=slug, **payload)
    session.add(series)
    await session.commit()
    await session.refresh(series)
    return ApiResponse(success=True, data=SeriesResponse.model_validate(series))


@router.put("/{series_id}", response_model=ApiResponse[SeriesResponse])
async def update_series(
    series_id: str, data: SeriesUpdate, session: AsyncSession = Depends(get_session)
):
    """Update a series."""
    series = await session.get(Series, series_id)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")
    update_data = data.model_dump(exclude_unset=True)
    if update_data.get("slug"):
        base = slugify(update_data["slug"], series.slug)
        update_data["slug"] = await _unique_slug(session, base, exclude_id=series_id)
    for key, value in update_data.items():
        setattr(series, key, value)
    await session.commit()
    await session.refresh(series)
    return ApiResponse(success=True, data=SeriesResponse.model_validate(series))


@router.delete("/{series_id}", response_model=ApiResponse[None])
async def delete_series(series_id: str, session: AsyncSession = Depends(get_session)):
    """Delete a series (does not delete its generated videos)."""
    series = await session.get(Series, series_id)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")
    await session.delete(series)
    await session.commit()
    return ApiResponse(success=True)


async def _read_book_request(request: Request) -> tuple[str | None, str]:
    """Accept either multipart ``file``/``title`` or a JSON ``{title, text}`` body.

    Multipart files may be ``.txt``/``.md``/``.markdown`` (decoded text) or
    ``.pdf`` (text extracted with pypdf). PDFs are also detected by magic bytes
    when the file name is missing or generic.
    """
    content_type = (request.headers.get("content-type") or "").lower()
    title: str | None = None
    text = ""

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        raw_title = form.get("title")
        if raw_title:
            title = str(raw_title).strip()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(status_code=400, detail="缺少上传文件 file")
        filename = (getattr(upload, "filename", "") or "").strip().lower()
        raw = await upload.read()
        supported = not filename or filename.endswith(book_service.ALLOWED_BOOK_EXTENSIONS)
        if not supported and not book_service.looks_like_pdf(raw):
            raise HTTPException(
                status_code=400, detail="仅支持 .txt / .md / .markdown / .pdf 文件"
            )
        try:
            text = book_service.decode_text(raw, filename=filename)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = None
        if isinstance(body, dict):
            raw_title = body.get("title")
            if raw_title:
                title = str(raw_title).strip()
            text = str(body.get("text") or body.get("content") or "")

    if not text.strip():
        raise HTTPException(status_code=400, detail="书籍内容为空（需要 text 或 file）")
    return title, text


def _series_payload(series: Series, episodes: list[dict]) -> dict:
    payload = SeriesResponse.model_validate(series).model_dump()
    payload.update({"episode_count": len(episodes), "episodes": episodes})
    return payload


@router.post("/from-book")
async def create_series_from_book(
    request: Request, session: AsyncSession = Depends(get_session)
):
    """Create a series from an uploaded book and split it into episodes."""
    title, text = await _read_book_request(request)
    name = (title or "未命名书籍").strip()[:255] or "未命名书籍"

    series_id = generate_id()
    base_slug = slugify(name, f"series-{series_id}")
    slug = await _unique_slug(session, base_slug)
    series = Series(id=series_id, slug=slug, name=name)
    session.add(series)
    await session.commit()
    await session.refresh(series)

    episodes = book_service.split_book(text)
    book_service.save_episodes(series.slug, episodes)
    return {"success": True, "data": _series_payload(series, episodes)}


@router.post("/{series_id}/import-book")
async def import_book(
    series_id: str, request: Request, session: AsyncSession = Depends(get_session)
):
    """Split an uploaded book into episodes and store them for an existing series."""
    series = await session.get(Series, series_id)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")

    title, text = await _read_book_request(request)
    episodes = book_service.split_book(text)
    path = book_service.save_episodes(series.slug, episodes)
    return {
        "success": True,
        "data": {
            "series_id": series.id,
            "slug": series.slug,
            "title": title,
            "episode_count": len(episodes),
            "episodes": episodes,
            "episodes_path": str(path),
        },
    }


@router.get("/{series_id}/episodes")
async def list_episodes(series_id: str, session: AsyncSession = Depends(get_session)):
    """List the imported episodes for a series."""
    series = await session.get(Series, series_id)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")
    episodes = book_service.load_episodes(series.slug)
    return {"success": True, "data": {"episodes": episodes, "episode_count": len(episodes)}}


@router.post("/{series_id}/generate-episodes")
async def generate_episodes(
    series_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    limit: int | None = Query(default=None, ge=1, le=50, description="Max episodes to queue"),
    start: int = Query(default=1, ge=1, description="1-based episode index to start from"),
    background_source: str = Query(default="online"),
    resolution: str = Query(default="landscape"),
    content_type: str = Query(default="book", description="Pipeline type for queued videos"),
    language: str = Query(default="zh", description="Narration language: zh | en (en for YouTube growth)"),
):
    """Queue one book (non-news) video task per imported episode."""
    series = await session.get(Series, series_id)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")

    episodes = book_service.load_episodes(series.slug)
    if not episodes:
        raise HTTPException(status_code=400, detail="该系列尚未导入书籍章节，请先调用 import-book")

    cap = int(limit if limit is not None else settings.book_default_episodes_per_call)
    cap = max(1, min(cap, 50))
    selected = episodes[start - 1 : start - 1 + cap]
    if not selected:
        raise HTTPException(status_code=400, detail="没有可生成的章节（检查 start/limit）")

    from . import videos

    queued: list[dict] = []
    for episode in selected:
        request = videos.VideoGenerateRequest(
            title=episode.get("title") or "未命名章节",
            content=episode.get("content") or "",
            series_id=series_id,
            content_type=content_type,
            background_source=background_source,
            resolution=resolution,
            language=language,
        )
        response = await videos.generate_video(request, background_tasks)
        data = response.get("data", {})
        queued.append(
            {
                "task_id": data.get("id"),
                "task_dir": data.get("task_dir"),
                "index": episode.get("index"),
                "title": request.title,
            }
        )

    return {
        "success": True,
        "data": {"series_id": series_id, "queued": len(queued), "tasks": queued},
    }


@router.get("/{series_id}/targets")
async def list_targets(series_id: str, session: AsyncSession = Depends(get_session)):
    """List publishing targets for a series."""
    series = await session.get(Series, series_id)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")
    result = await session.execute(
        select(SeriesPublishTarget).where(SeriesPublishTarget.series_id == series_id)
    )
    return {"success": True, "data": [_target_to_dict(t) for t in result.scalars().all()]}


@router.post("/{series_id}/targets")
async def create_target(series_id: str, data: TargetCreate, session: AsyncSession = Depends(get_session)):
    """Add a publishing target to a series."""
    series = await session.get(Series, series_id)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")
    target = SeriesPublishTarget(
        id=uuid.uuid4().hex[:16],
        series_id=series_id,
        platform=data.platform.lower().strip(),
        account_id=data.account_id,
        folder_id=data.folder_id,
        folder_name=data.folder_name,
        enabled=data.enabled,
    )
    session.add(target)
    await session.commit()
    await session.refresh(target)
    return {"success": True, "data": _target_to_dict(target)}


@router.delete("/{series_id}/targets/{target_id}")
async def delete_target(series_id: str, target_id: str, session: AsyncSession = Depends(get_session)):
    """Remove a publishing target."""
    target = await session.get(SeriesPublishTarget, target_id)
    if not target or target.series_id != series_id:
        raise HTTPException(status_code=404, detail="Target not found")
    await session.delete(target)
    await session.commit()
    return {"success": True}


@router.post("/{series_id}/publish-approved")
async def publish_approved(series_id: str, session: AsyncSession = Depends(get_session)):
    """Queue publishing for every approved video in the series using its targets."""
    from ..queue import enqueue_publish_jobs
    from ..services.video_service import video_tasks

    series = await session.get(Series, series_id)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")

    targets_res = await session.execute(
        select(SeriesPublishTarget).where(
            SeriesPublishTarget.series_id == series_id,
            SeriesPublishTarget.enabled == True,
            SeriesPublishTarget.account_id.is_not(None),
        )
    )
    targets = list(targets_res.scalars().all())
    if not targets:
        raise HTTPException(status_code=400, detail="该系列没有配置发布目标")

    # Import here to avoid a route-level cycle
    from .videos import _enrich_task

    queued = 0
    tasks_seen = 0
    for task in list(video_tasks.values()):
        if task.get("series_id") != series_id:
            continue
        enriched = _enrich_task(dict(task))
        if enriched.get("status") != "completed":
            continue
        if getattr(settings, "publish_require_review", True) and enriched.get("review_status") != "approved":
            continue
        tasks_seen += 1
        title = enriched.get("request", {}).get("title") or "Video"
        language = enriched.get("language") or enriched.get("request", {}).get("language") or "zh"
        jobs = [
            {
                "id": uuid.uuid4().hex[:16],
                "task_id": task["id"],
                "series_id": series_id,
                "video_path": enriched.get("video_path"),
                "task_dir": task.get("task_dir"),
                "account_id": t.account_id,
                "platform": t.platform,
                "title": (
                    enriched.get("youtube_title") or title
                    if str(t.platform).lower() in ("youtube", "yt") and language != "zh"
                    else title
                ),
                "description": (
                    enriched.get("youtube_description")
                    if str(t.platform).lower() in ("youtube", "yt") and language != "zh"
                    else None
                ),
                "tags_json": (
                    json.dumps(enriched.get("youtube_tags"), ensure_ascii=False)
                    if str(t.platform).lower() in ("youtube", "yt")
                    and language != "zh"
                    and enriched.get("youtube_tags")
                    else None
                ),
                "folder_id": t.folder_id,
                "privacy": (
                    settings.youtube_default_privacy
                    if str(t.platform).lower() in ("youtube", "yt")
                    else None
                ),
                "language": language,
            }
            for t in targets
        ]
        queued += await enqueue_publish_jobs(jobs)

    return {"success": True, "data": {"videos": tasks_seen, "queued": queued}}

