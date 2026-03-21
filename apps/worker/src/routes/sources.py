"""Source management routes."""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models import Source
from ..schemas import ApiResponse, SourceCreate, SourceResponse, SourceUpdate

router = APIRouter()


def generate_id() -> str:
    """Generate a unique ID."""
    import hashlib
    import time
    return hashlib.md5(f"{time.time()}".encode()).hexdigest()[:16]


@router.get("", response_model=ApiResponse[list[SourceResponse]])
async def list_sources(
    source_type: Optional[str] = None,
    enabled: Optional[bool] = None,
    session: AsyncSession = Depends(get_session),
):
    """List all sources."""
    query = select(Source)
    if source_type:
        query = query.where(Source.type == source_type)
    if enabled is not None:
        query = query.where(Source.enabled == enabled)
    result = await session.execute(query)
    sources = result.scalars().all()
    return ApiResponse(
        success=True,
        data=[SourceResponse.model_validate(s) for s in sources],
    )


@router.get("/{source_id}", response_model=ApiResponse[SourceResponse])
async def get_source(
    source_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get a source by ID."""
    result = await session.execute(select(Source).where(Source.id == source_id))
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return ApiResponse(success=True, data=SourceResponse.model_validate(source))


@router.post("", response_model=ApiResponse[SourceResponse])
async def create_source(
    data: SourceCreate,
    session: AsyncSession = Depends(get_session),
):
    """Create a new source."""
    source = Source(
        id=generate_id(),
        type=data.type,
        name=data.name,
        url=data.url,
        api_key=data.api_key,
        keywords=json.dumps(data.keywords) if data.keywords else None,
        enabled=data.enabled,
    )
    session.add(source)
    await session.commit()
    await session.refresh(source)
    return ApiResponse(success=True, data=SourceResponse.model_validate(source))


@router.put("/{source_id}", response_model=ApiResponse[SourceResponse])
async def update_source(
    source_id: str,
    data: SourceUpdate,
    session: AsyncSession = Depends(get_session),
):
    """Update a source."""
    result = await session.execute(select(Source).where(Source.id == source_id))
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    update_data = data.model_dump(exclude_unset=True)
    if "keywords" in update_data and update_data["keywords"] is not None:
        update_data["keywords"] = json.dumps(update_data["keywords"])

    for key, value in update_data.items():
        setattr(source, key, value)
    await session.commit()
    await session.refresh(source)
    return ApiResponse(success=True, data=SourceResponse.model_validate(source))


@router.delete("/{source_id}", response_model=ApiResponse[None])
async def delete_source(
    source_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Delete a source."""
    result = await session.execute(select(Source).where(Source.id == source_id))
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    await session.delete(source)
    await session.commit()
    return ApiResponse(success=True)