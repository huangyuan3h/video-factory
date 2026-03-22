"""Task management routes."""


from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models import Task
from ..scheduler import scheduler
from ..schemas import ApiResponse, TaskCreate, TaskResponse, TaskUpdate

router = APIRouter()


def generate_id() -> str:
    """Generate a unique ID."""
    import hashlib
    import time
    return hashlib.md5(f"{time.time()}".encode()).hexdigest()[:16]


@router.get("", response_model=ApiResponse[list[TaskResponse]])
async def list_tasks(
    enabled: bool | None = None,
    session: AsyncSession = Depends(get_session),
):
    """List all tasks."""
    query = select(Task)
    if enabled is not None:
        query = query.where(Task.enabled == enabled)
    result = await session.execute(query)
    tasks = result.scalars().all()
    return ApiResponse(
        success=True,
        data=[TaskResponse.model_validate(t) for t in tasks],
    )


@router.get("/{task_id}", response_model=ApiResponse[TaskResponse])
async def get_task(
    task_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get a task by ID."""
    result = await session.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return ApiResponse(success=True, data=TaskResponse.model_validate(task))


@router.post("", response_model=ApiResponse[TaskResponse])
async def create_task(
    data: TaskCreate,
    session: AsyncSession = Depends(get_session),
):
    """Create a new task."""
    task = Task(
        id=generate_id(),
        name=data.name,
        source_id=data.source_id,
        schedule=data.schedule,
        enabled=data.enabled,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)

    # Schedule the task
    await scheduler.add_task(task)

    return ApiResponse(success=True, data=TaskResponse.model_validate(task))


@router.put("/{task_id}", response_model=ApiResponse[TaskResponse])
async def update_task(
    task_id: str,
    data: TaskUpdate,
    session: AsyncSession = Depends(get_session),
):
    """Update a task."""
    result = await session.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(task, key, value)
    await session.commit()
    await session.refresh(task)

    # Re-schedule the task
    await scheduler.update_task(task)

    return ApiResponse(success=True, data=TaskResponse.model_validate(task))


@router.delete("/{task_id}", response_model=ApiResponse[None])
async def delete_task(
    task_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Delete a task."""
    result = await session.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    await scheduler.remove_task(task_id)
    await session.delete(task)
    await session.commit()

    return ApiResponse(success=True)


@router.post("/{task_id}/run", response_model=ApiResponse[dict])
async def run_task_now(
    task_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Trigger a task to run immediately."""
    result = await session.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    run_id = await scheduler.trigger_task(task)
    return ApiResponse(success=True, data={"run_id": run_id})
