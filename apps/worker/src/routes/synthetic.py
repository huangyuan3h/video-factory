"""Synthetic image API — ComfyUI wrapper, zero node knowledge."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..config import settings
from ..services.synthetic_service import generate_image, is_available, is_enabled, COMFYUI_URL
from ..services.synthetic_video_service import (
    generate_video_clip,
    is_available as video_is_available,
    is_enabled as video_is_enabled,
)

router = APIRouter()


class SyntheticRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=1000, description="Text prompt for image")
    width: int = Field(default=1920, ge=256, le=2048)
    height: int = Field(default=1080, ge=256, le=2048)
    count: int = Field(default=1, ge=1, le=4)


class BatchSyntheticRequest(BaseModel):
    prompts: list[str] = Field(..., min_length=1, max_length=10)
    width: int = Field(default=1920, ge=256, le=2048)
    height: int = Field(default=1080, ge=256, le=2048)


@router.get("/status")
async def status():
    enabled = is_enabled()
    avail = is_available()
    if not enabled:
        hint = "Synthetic disabled — set ENABLE_SYNTHETIC=1 to opt in (ComfyUI can use 10GB+ RAM)"
    elif avail:
        hint = "ComfyUI reachable"
    else:
        hint = "ComfyUI not reachable — will fallback to placeholder"
    return {
        "enabled": enabled,
        "available": avail,
        "comfyui_url": COMFYUI_URL,
        "model": "sd_xl_turbo_1.0_fp16.safetensors",
        "hint": hint,
    }


@router.post("/generate")
async def generate(req: SyntheticRequest):
    if not is_enabled():
        raise HTTPException(status_code=409, detail="Synthetic disabled. Set ENABLE_SYNTHETIC=1 to opt in.")
    path = await generate_image(req.prompt, req.width, req.height)
    if not path or not path.exists():
        raise HTTPException(status_code=503, detail="ComfyUI generation failed or not available")
    return FileResponse(path, media_type="image/png", filename=path.name)


@router.post("/batch")
async def batch(req: BatchSyntheticRequest):
    if not is_enabled():
        raise HTTPException(status_code=409, detail="Synthetic disabled. Set ENABLE_SYNTHETIC=1 to opt in.")
    from ..services.synthetic_service import generate_images

    paths = await generate_images(req.prompts, req.width, req.height)
    if not paths:
        raise HTTPException(status_code=503, detail="Batch generation failed")
    return {"success": True, "count": len(paths), "files": [str(p) for p in paths]}


class VideoRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=1000)
    negative: str = Field(default="", max_length=1000)
    width: int = Field(default=768, ge=256, le=1280)
    height: int = Field(default=512, ge=256, le=1280)


@router.get("/video/status")
async def video_status():
    enabled = video_is_enabled()
    avail = video_is_available()
    if not enabled:
        hint = "Synthetic video disabled — set ENABLE_SYNTHETIC_VIDEO=1 (video models are heavy)"
    elif avail:
        hint = "ComfyUI reachable"
    else:
        hint = "ComfyUI not reachable"
    return {
        "enabled": enabled,
        "available": avail,
        "comfyui_url": COMFYUI_URL,
        "workflow": "custom template" if (settings.synthetic_video_workflow or "") else "built-in LTX-Video t2v",
        "hint": hint,
    }


@router.post("/video/generate")
async def video_generate(req: VideoRequest):
    if not video_is_enabled():
        raise HTTPException(status_code=409, detail="Synthetic video disabled. Set ENABLE_SYNTHETIC_VIDEO=1 to opt in.")
    path = await generate_video_clip(req.prompt, negative=req.negative, width=req.width, height=req.height)
    if not path or not path.exists():
        raise HTTPException(status_code=503, detail="ComfyUI video generation failed or not available")
    media = "video/webm" if path.suffix == ".webm" else "video/mp4" if path.suffix == ".mp4" else "application/octet-stream"
    return FileResponse(path, media_type=media, filename=path.name)
