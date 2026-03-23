"""System prompts management routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models import SystemPrompt
from ..schemas import (
    ApiResponse,
    SystemPromptCreate,
    SystemPromptResponse,
    SystemPromptUpdate,
)

router = APIRouter()


def generate_id() -> str:
    """Generate a unique ID."""
    import hashlib
    import time

    return hashlib.md5(f"{time.time()}".encode()).hexdigest()[:16]


@router.get("", response_model=ApiResponse[list[SystemPromptResponse]])
async def list_system_prompts(
    session: AsyncSession = Depends(get_session),
):
    """List all system prompts."""
    result = await session.execute(select(SystemPrompt))
    prompts = result.scalars().all()
    return ApiResponse(
        success=True,
        data=[SystemPromptResponse.model_validate(p) for p in prompts],
    )


@router.post("", response_model=ApiResponse[SystemPromptResponse])
async def create_system_prompt(
    data: SystemPromptCreate,
    session: AsyncSession = Depends(get_session),
):
    """Create a new system prompt."""
    if data.is_default:
        result = await session.execute(select(SystemPrompt).where(SystemPrompt.is_default == True))
        default_prompts = result.scalars().all()
        for p in default_prompts:
            p.is_default = False

    prompt = SystemPrompt(
        id=generate_id(),
        name=data.name,
        content=data.content,
        is_default=data.is_default,
    )
    session.add(prompt)
    await session.commit()
    await session.refresh(prompt)
    return ApiResponse(success=True, data=SystemPromptResponse.model_validate(prompt))


@router.put("/{prompt_id}", response_model=ApiResponse[SystemPromptResponse])
async def update_system_prompt(
    prompt_id: str,
    data: SystemPromptUpdate,
    session: AsyncSession = Depends(get_session),
):
    """Update a system prompt."""
    result = await session.execute(
        select(SystemPrompt).where(SystemPrompt.id == prompt_id)
    )
    prompt = result.scalar_one_or_none()
    if not prompt:
        raise HTTPException(status_code=404, detail="System prompt not found")

    update_data = data.model_dump(exclude_unset=True)

    if update_data.get("is_default"):
        result = await session.execute(select(SystemPrompt).where(SystemPrompt.is_default == True))
        default_prompts = result.scalars().all()
        for p in default_prompts:
            p.is_default = False

    for key, value in update_data.items():
        setattr(prompt, key, value)
    await session.commit()
    await session.refresh(prompt)
    return ApiResponse(success=True, data=SystemPromptResponse.model_validate(prompt))


@router.post("/{prompt_id}/default", response_model=ApiResponse[SystemPromptResponse])
async def set_default_system_prompt(
    prompt_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Set a system prompt as default."""
    result = await session.execute(
        select(SystemPrompt).where(SystemPrompt.id == prompt_id)
    )
    prompt = result.scalar_one_or_none()
    if not prompt:
        raise HTTPException(status_code=404, detail="System prompt not found")

    result = await session.execute(select(SystemPrompt))
    prompts = result.scalars().all()
    for p in prompts:
        p.is_default = p.id == prompt_id

    await session.commit()
    await session.refresh(prompt)
    return ApiResponse(success=True, data=SystemPromptResponse.model_validate(prompt))


@router.delete("/{prompt_id}", response_model=ApiResponse[None])
async def delete_system_prompt(
    prompt_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Delete a system prompt."""
    result = await session.execute(
        select(SystemPrompt).where(SystemPrompt.id == prompt_id)
    )
    prompt = result.scalar_one_or_none()
    if not prompt:
        raise HTTPException(status_code=404, detail="System prompt not found")

    await session.delete(prompt)
    await session.commit()
    return ApiResponse(success=True)