"""Synthetic video / animation via ComfyUI (LTX-Video, Wan, HunyuanVideo...).

Zero node knowledge needed in the common case, but heavy: video models are
multi-GB and generation can take minutes. Therefore this is OPT-IN
(ENABLE_SYNTHETIC_VIDEO=1) and reuses the same safety posture as images:

  * disabled unless explicitly enabled
  * free-memory gate (default 16GB)
  * dimensions clamped to multiples of 32 and a sane range
  * one/few clips per call, strictly sequential with cooldown
  * circuit breaker on repeated failure

Workflow source, in order of preference:
  1. `SYNTHETIC_VIDEO_WORKFLOW` — path to a ComfyUI "workflow (API format)"
     JSON you exported. Use placeholders so we can inject values:
       {{prompt}} {{negative}} {{width}} {{height}} {{length}} {{fps}} {{seed}} {{image}}
  2. Built-in LTX-Video text-to-video workflow (best-effort default).
"""

import asyncio
import json
import logging
import tempfile
import uuid
from pathlib import Path

import httpx

from ..config import settings
from .synthetic_service import _system_free_gb

logger = logging.getLogger(__name__)

COMFYUI_URL = getattr(settings, "comfyui_url", None) or "http://127.0.0.1:8188"

MAX_WIDTH = 1280
MAX_HEIGHT = 1280
MAX_BATCH = 4
POLL_INTERVAL = 3.0
MIN_FREE_GB = 16.0
REQUEST_TIMEOUT = 900.0

_breaker_tripped = False


def is_enabled() -> bool:
    return bool(getattr(settings, "enable_synthetic_video", False))


def _min_free_gb() -> float:
    return float(getattr(settings, "synthetic_video_min_free_gb", MIN_FREE_GB) or MIN_FREE_GB)


def _max_clips() -> int:
    try:
        return max(1, min(MAX_BATCH, int(getattr(settings, "synthetic_video_max_clips", 1) or 1)))
    except Exception:
        return 1


def _cooldown_s() -> float:
    return float(getattr(settings, "synthetic_video_cooldown_s", 10.0) or 10.0)


def _request_timeout() -> float:
    return float(getattr(settings, "synthetic_video_timeout_s", REQUEST_TIMEOUT) or REQUEST_TIMEOUT)


def _clamp_dim(w: int, h: int) -> tuple[int, int]:
    """LTX and most video VAEs need dimensions divisible by 32."""
    w = max(256, min(int(w), MAX_WIDTH))
    h = max(256, min(int(h), MAX_HEIGHT))
    return (w // 32) * 32, (h // 32) * 32


def _default_ltx_t2v(prompt: str, negative: str, width: int, height: int, length: int, seed: int, fps: float) -> dict:
    return {
        "3": {
            "inputs": {
                "seed": seed,
                "steps": 25,
                "cfg": 3.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["8", 0],
                "negative": ["8", 1],
                "latent_image": ["5", 0],
            },
            "class_type": "KSampler",
        },
        "4": {
            "inputs": {"ckpt_name": "ltx-video-2b-v0.9.5.safetensors"},
            "class_type": "CheckpointLoaderSimple",
        },
        "5": {
            "inputs": {"width": width, "height": height, "length": length, "batch_size": 1},
            "class_type": "EmptyLTXVLatentVideo",
        },
        "6": {"inputs": {"text": prompt, "clip": ["4", 1]}, "class_type": "CLIPTextEncode"},
        "7": {"inputs": {"text": negative, "clip": ["4", 1]}, "class_type": "CLIPTextEncode"},
        "8": {
            "inputs": {"positive": ["6", 0], "negative": ["7", 0], "frame_rate": fps},
            "class_type": "LTXVConditioning",
        },
        "9": {"inputs": {"samples": ["3", 0], "vae": ["4", 2]}, "class_type": "VAEDecode"},
        "10": {
            "inputs": {"images": ["9", 0], "filename_prefix": "video_factory", "codec": "vp9", "fps": fps, "crf": 32},
            "class_type": "SaveWEBM",
        },
    }


def _substitute(value, mapping: dict[str, object]):
    """Replace {{placeholders}}; exact scalar placeholders keep their type."""
    if isinstance(value, dict):
        return {k: _substitute(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, mapping) for v in value]
    if isinstance(value, str):
        if value in mapping and not isinstance(mapping[value], str):
            return mapping[value]
        out = value
        for key, replacement in mapping.items():
            out = out.replace(key, str(replacement))
        return out
    return value


def load_workflow(prompt: str, negative: str, width: int, height: int, length: int, seed: int, fps: float, image_name: str | None) -> dict:
    """Build the ComfyUI workflow, from a configured template or the built-in one."""
    mapping: dict[str, object] = {
        "{{prompt}}": prompt,
        "{{negative}}": negative,
        "{{width}}": width,
        "{{height}}": height,
        "{{length}}": length,
        "{{fps}}": fps,
        "{{seed}}": seed,
        "{{image}}": image_name or "",
    }
    template_path = getattr(settings, "synthetic_video_workflow", "") or ""
    if template_path:
        try:
            raw = json.loads(Path(template_path).read_text(encoding="utf-8"))
            logger.info(f"Synthetic video: using workflow template {template_path}")
            return _substitute(raw, mapping)
        except Exception as e:
            logger.warning(f"Failed to load workflow template {template_path}: {e}; using built-in")
    return _default_ltx_t2v(prompt, negative, width, height, length, seed, fps)


async def _upload_image(client: httpx.AsyncClient, image_path: Path) -> str | None:
    """Upload an image for image-to-video workflows; returns the stored name."""
    try:
        with open(image_path, "rb") as f:
            files = {"image": (image_path.name, f, "image/png")}
            resp = await client.post(f"{COMFYUI_URL}/upload/image", files=files)
        resp.raise_for_status()
        data = resp.json()
        name = data.get("name")
        subfolder = data.get("subfolder") or ""
        return f"{subfolder}/{name}" if subfolder else name
    except Exception as e:
        logger.warning(f"ComfyUI image upload failed: {e}")
        return None


def _extract_output(history: dict, prompt_id: str) -> dict | None:
    """Pick the first video/animation output entry from history."""
    entry = history.get(prompt_id, {})
    outputs = entry.get("outputs", {})
    for _node_id, out in outputs.items():
        for key in ("gifs", "videos", "images"):
            for item in out.get(key, []) or []:
                if item.get("filename"):
                    return item
    return None


async def generate_video_clip(
    prompt: str,
    negative: str = "",
    width: int | None = None,
    height: int | None = None,
    image: Path | None = None,
    timeout: float | None = None,
) -> Path | None:
    """Generate one clip via ComfyUI. Returns a Path or None on failure/skip."""
    global _breaker_tripped
    if not is_enabled():
        logger.info("Synthetic video disabled (set ENABLE_SYNTHETIC_VIDEO=1 to enable)")
        return None
    if _breaker_tripped:
        logger.info("Synthetic video circuit breaker tripped — skipping")
        return None

    timeout = float(timeout) if timeout is not None else _request_timeout()
    width = width or getattr(settings, "synthetic_video_width", 768)
    height = height or getattr(settings, "synthetic_video_height", 512)
    width, height = _clamp_dim(width, height)
    length = int(getattr(settings, "synthetic_video_frames", 97) or 97)
    fps = float(getattr(settings, "synthetic_video_fps", 25.0) or 25.0)

    free = _system_free_gb()
    if free < _min_free_gb():
        logger.warning(f"Free memory {free:.1f}GB < {_min_free_gb()}GB — skipping synthetic video")
        return None

    client_id = str(uuid.uuid4())
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            image_name = None
            if image is not None:
                image_name = await _upload_image(client, image)
                if not image_name:
                    return None

            workflow = load_workflow(prompt, negative, width, height, length, seed=_random_seed(), fps=fps, image_name=image_name)
            resp = await client.post(f"{COMFYUI_URL}/prompt", json={"prompt": workflow, "client_id": client_id})
            resp.raise_for_status()
            prompt_id = resp.json().get("prompt_id")
            if not prompt_id:
                logger.warning("ComfyUI video: no prompt_id returned")
                return None

            polls = int(timeout / POLL_INTERVAL)
            for _ in range(polls):
                await asyncio.sleep(POLL_INTERVAL)
                hist = await client.get(f"{COMFYUI_URL}/history/{prompt_id}")
                hist.raise_for_status()
                history = hist.json()
                if prompt_id in history and history[prompt_id].get("status", {}).get("completed"):
                    item = _extract_output(history, prompt_id)
                    if not item:
                        logger.warning("ComfyUI video: completed but no output")
                        return None
                    view = await client.get(
                        f"{COMFYUI_URL}/view",
                        params={
                            "filename": item["filename"],
                            "subfolder": item.get("subfolder", ""),
                            "type": item.get("type", "output"),
                        },
                    )
                    view.raise_for_status()
                    tmp = Path(tempfile.mkdtemp()) / item["filename"]
                    tmp.write_bytes(view.content)
                    logger.info(f"ComfyUI generated clip {tmp.name} ({width}x{height}, {length}f) for: {prompt[:40]}")
                    return tmp
            logger.warning(f"ComfyUI video timeout for prompt: {prompt[:40]}")
            return None
    except Exception as e:
        logger.warning(f"ComfyUI video generate failed ({e})")
        if "out of memory" in str(e).lower() or "OOM" in str(e):
            _breaker_tripped = True
            logger.error("OOM detected — synthetic video circuit breaker TRIPPED")
        return None


def _random_seed() -> int:
    import random

    return random.randint(0, 2 ** 32 - 1)


async def generate_video_clips(
    prompts: list[str],
    width: int | None = None,
    height: int | None = None,
    image: Path | None = None,
) -> list[Path]:
    """Batch generate — sequential, capped, with cooldown."""
    results: list[Path] = []
    if not is_enabled():
        return results
    cap = _max_clips()
    for prompt in prompts[:cap]:
        path = await generate_video_clip(prompt, width=width, height=height, image=image)
        if path:
            results.append(path)
        await asyncio.sleep(_cooldown_s())
        if len(results) >= cap:
            break
    return results


def is_available() -> bool:
    """Enabled AND ComfyUI reachable."""
    if not is_enabled():
        return False
    try:
        r = httpx.get(f"{COMFYUI_URL}/system_stats", timeout=3)
        return r.status_code == 200
    except Exception:
        return False
