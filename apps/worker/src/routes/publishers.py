"""Publisher accounts + publish actions — extensible registry."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models import PublisherAccount
from ..publishers import get_publisher, list_platforms
from ..publishers.base import PublishResult

logger = logging.getLogger(__name__)

router = APIRouter()


def _gen_id() -> str:
    import hashlib, time
    return hashlib.md5(f"{time.time()}".encode()).hexdigest()[:16]


class PublisherCreate(BaseModel):
    platform: str = Field(..., description="douyin|xhs|youtube etc")
    name: str
    cookies: str | None = None
    credentials: str | None = None
    folder_id: str | None = None
    folder_name: str | None = None
    extra_config: str | dict | None = None
    enabled: bool = True


class PublisherUpdate(BaseModel):
    name: str | None = None
    cookies: str | None = None
    credentials: str | None = None
    folder_id: str | None = None
    folder_name: str | None = None
    extra_config: str | dict | None = None
    enabled: bool | None = None


class PublishRequest(BaseModel):
    video_path: str | None = None  # absolute path or task output.mp4
    task_id: str | None = None  # alternative: publish by task_id
    title: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    folder_id: str | None = None
    playlist_id: str | None = None
    privacy: str | None = None  # youtube


def _to_dict(acc: PublisherAccount) -> dict:
    return {
        "id": acc.id,
        "platform": acc.platform,
        "name": acc.name,
        "cookies": acc.cookies,
        "credentials": acc.credentials,
        "folder_id": acc.folder_id,
        "folder_name": acc.folder_name,
        "extra_config": acc.extra_config,
        "enabled": acc.enabled,
        "created_at": acc.created_at.isoformat() if acc.created_at else None,
        "supports_folder": True,
    }


@router.get("")
async def list_publishers(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(PublisherAccount))
    accounts = result.scalars().all()
    return {"success": True, "data": [_to_dict(a) for a in accounts], "platforms": list_platforms()}


@router.post("")
async def create_publisher(data: PublisherCreate, session: AsyncSession = Depends(get_session)):
    platform = data.platform.lower().strip()
    if platform not in [p.lower() for p in list_platforms()]:
        # Allow any but warn
        logger.warning(f"Creating publisher for unknown platform {platform}")
    extra = data.extra_config
    if isinstance(extra, dict):
        extra = json.dumps(extra, ensure_ascii=False)
    acc = PublisherAccount(
        id=_gen_id(),
        platform=platform,
        name=data.name,
        cookies=data.cookies,
        credentials=data.credentials,
        folder_id=data.folder_id,
        folder_name=data.folder_name,
        extra_config=extra,
        enabled=data.enabled,
    )
    session.add(acc)
    await session.commit()
    await session.refresh(acc)
    return {"success": True, "data": _to_dict(acc)}


@router.get("/{publisher_id}")
async def get_publisher_account(publisher_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(PublisherAccount).where(PublisherAccount.id == publisher_id))
    acc = result.scalar_one_or_none()
    if not acc:
        raise HTTPException(status_code=404, detail="Publisher not found")
    return {"success": True, "data": _to_dict(acc)}


@router.put("/{publisher_id}")
async def update_publisher(publisher_id: str, data: PublisherUpdate, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(PublisherAccount).where(PublisherAccount.id == publisher_id))
    acc = result.scalar_one_or_none()
    if not acc:
        raise HTTPException(status_code=404, detail="Publisher not found")
    upd = data.model_dump(exclude_unset=True)
    if "extra_config" in upd and isinstance(upd["extra_config"], dict):
        upd["extra_config"] = json.dumps(upd["extra_config"], ensure_ascii=False)
    for k, v in upd.items():
        setattr(acc, k, v)
    await session.commit()
    await session.refresh(acc)
    return {"success": True, "data": _to_dict(acc)}


@router.delete("/{publisher_id}")
async def delete_publisher(publisher_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(PublisherAccount).where(PublisherAccount.id == publisher_id))
    acc = result.scalar_one_or_none()
    if not acc:
        raise HTTPException(status_code=404, detail="Publisher not found")
    await session.delete(acc)
    await session.commit()
    return {"success": True, "message": "Deleted"}


@router.get("/{publisher_id}/folders")
async def list_folders(publisher_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(PublisherAccount).where(PublisherAccount.id == publisher_id))
    acc = result.scalar_one_or_none()
    if not acc:
        raise HTTPException(status_code=404, detail="Publisher not found")
    try:
        pub = get_publisher(acc.platform, credentials=acc.credentials or acc.cookies, folder_id=acc.folder_id)
        folders = await pub.list_folders()
        return {"success": True, "data": folders}
    except Exception as e:
        logger.error(f"list_folders failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{publisher_id}/publish")
async def publish_video(publisher_id: str, data: PublishRequest, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(PublisherAccount).where(PublisherAccount.id == publisher_id))
    acc = result.scalar_one_or_none()
    if not acc:
        raise HTTPException(status_code=404, detail="Publisher not found")
    # Resolve video path
    video_path = None
    if data.video_path:
        video_path = Path(data.video_path)
    elif data.task_id:
        # Resolve from video_tasks
        from ..services.video_service import video_tasks
        task = video_tasks.get(data.task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        # Enrich
        vp = task.get("video_path") or (task.get("files") or {}).get("video")
        if vp:
            video_path = Path(vp)
    if not video_path or not video_path.exists():
        raise HTTPException(status_code=400, detail="video_path required and must exist")
    title = data.title or f"Video {video_path.stem}"
    try:
        pub = get_publisher(acc.platform, credentials=acc.credentials or acc.cookies, folder_id=acc.folder_id)
        folder = data.folder_id or data.playlist_id or acc.folder_id
        res: PublishResult = await pub.upload(
            video_path=video_path,
            title=title,
            description=data.description,
            tags=data.tags,
            folder_id=folder,
            playlist_id=folder,
            privacy=data.privacy or "private",
        )
        return {"success": res.success, "data": {"platform": res.platform, "post_url": res.post_url, "post_id": res.post_id, "error": res.error}}
    except Exception as e:
        logger.error(f"publish failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/platforms/list")
async def list_supported_platforms():
    return {"success": True, "data": list_platforms()}
