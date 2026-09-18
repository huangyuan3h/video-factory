"""Series management routes."""

import hashlib
import re
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models import Series, SeriesPublishTarget
from ..schemas import ApiResponse, SeriesCreate, SeriesResponse, SeriesUpdate

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
    from ..config import settings
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
        jobs = [
            {
                "id": uuid.uuid4().hex[:16],
                "task_id": task["id"],
                "series_id": series_id,
                "video_path": enriched.get("video_path"),
                "task_dir": task.get("task_dir"),
                "account_id": t.account_id,
                "platform": t.platform,
                "title": title,
                "description": None,
                "tags_json": None,
                "folder_id": t.folder_id,
                "privacy": None,
            }
            for t in targets
        ]
        queued += await enqueue_publish_jobs(jobs)

    return {"success": True, "data": {"videos": tasks_seen, "queued": queued}}

