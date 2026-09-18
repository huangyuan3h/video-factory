"""Series management routes."""

import hashlib
import re
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models import Series
from ..schemas import ApiResponse, SeriesCreate, SeriesResponse, SeriesUpdate

router = APIRouter()

_SLUG_STRIP = re.compile(r"[^\w-]+", re.UNICODE)


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
