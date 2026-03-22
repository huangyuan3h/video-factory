"""Run management routes."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from ..database import get_session
from ..models import Run
from ..schemas import ApiResponse, PaginatedResponse, RunResponse

router = APIRouter()


@router.get("", response_model=ApiResponse[PaginatedResponse[RunResponse]])
async def list_runs(
    task_id: str | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    """List runs with pagination."""
    query = select(Run).options(joinedload(Run.task))

    if task_id:
        query = query.where(Run.task_id == task_id)
    if status:
        query = query.where(Run.status == status)

    # Count total
    count_query = select(Run)
    if task_id:
        count_query = count_query.where(Run.task_id == task_id)
    if status:
        count_query = count_query.where(Run.status == status)

    total_result = await session.execute(count_query)
    total = len(total_result.scalars().all())

    # Paginate
    query = query.order_by(Run.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await session.execute(query)
    runs = result.scalars().unique().all()

    return ApiResponse(
        success=True,
        data=PaginatedResponse(
            items=[RunResponse.model_validate(r) for r in runs],
            total=total,
            page=page,
            page_size=page_size,
        ),
    )


@router.get("/{run_id}", response_model=ApiResponse[RunResponse])
async def get_run(
    run_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get a run by ID."""
    result = await session.execute(
        select(Run).options(joinedload(Run.task)).where(Run.id == run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    response = RunResponse.model_validate(run)
    if run.published_to:
        response.published_to = json.loads(run.published_to)

    return ApiResponse(success=True, data=response)
