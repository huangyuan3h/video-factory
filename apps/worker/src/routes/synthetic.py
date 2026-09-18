"""Synthetic image API — ComfyUI wrapper, zero node knowledge."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..services.synthetic_service import generate_image, is_available, is_enabled, COMFYUI_URL

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
        "model": "sd3.5_large_turbo.safetensors",
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
