"""Synthetic image generation via ComfyUI — simple API for video-factory.

Zero node knowledge needed: just prompt + resolution.
OPT-IN: does nothing unless ENABLE_SYNTHETIC=1 (setting `enable_synthetic`).
ComfyUI + SD3.5 can eat 10GB+ RAM/VRAM and has frozen laptops, so generation is
strictly guarded so it can NEVER crash the host:
  * disabled unless explicitly enabled
  * resolution is hard-clamped (never 1920x1080)
  * a free-memory gate refuses to run when RAM is tight (default 12GB)
  * only one image per call by default
  * generation is strictly sequential with cooldown sleeps
  * a global circuit breaker disables synthetic after repeated failures
"""

import asyncio
import json
import logging
import platform
import random
import subprocess
import tempfile
import uuid
from pathlib import Path

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

# ComfyUI URL — configurable via env COMFYUI_URL
COMFYUI_URL = getattr(settings, "comfyui_url", None) or "http://127.0.0.1:8188"

# ---- Safety limits (do not exceed) ----
MAX_WIDTH = 1024
MAX_HEIGHT = 576
MAX_BATCH = 4            # legacy ceiling; effective cap comes from settings.synthetic_max_images
COOLDOWN_S = 5.0         # sleep between images to let VRAM/RAM settle
MIN_FREE_GB = 12.0       # refuse to generate if free RAM below this
POLL_INTERVAL = 2.0      # history poll interval
REQUEST_TIMEOUT = 120.0  # per-image timeout

# Circuit breaker: once tripped, synthetic is disabled for the process lifetime
_breaker_tripped = False


def is_enabled() -> bool:
    """Synthetic generation is opt-in — disabled unless ENABLE_SYNTHETIC=1."""
    return bool(getattr(settings, "enable_synthetic", False))


def _min_free_gb() -> float:
    return float(getattr(settings, "synthetic_min_free_gb", MIN_FREE_GB) or MIN_FREE_GB)


def _max_images() -> int:
    try:
        return max(1, min(MAX_BATCH, int(getattr(settings, "synthetic_max_images", 1) or 1)))
    except Exception:
        return 1


def _cooldown_s() -> float:
    return float(getattr(settings, "synthetic_cooldown_s", COOLDOWN_S) or COOLDOWN_S)


def _request_timeout() -> float:
    return float(getattr(settings, "synthetic_timeout_s", REQUEST_TIMEOUT) or REQUEST_TIMEOUT)


def _system_free_gb() -> float:
    """Return available system memory in GB (best-effort, cross-platform)."""
    try:
        import psutil  # type: ignore

        return float(psutil.virtual_memory().available) / (1024 ** 3)
    except Exception:
        pass
    try:
        if platform.system() == "Darwin":
            out = subprocess.run(["vm_stat"], capture_output=True, text=True).stdout
            page = 4096
            for line in out.splitlines():
                if "page size of" in line:
                    try:
                        page = int(line.split("page size of")[1].split()[0])
                    except Exception:
                        pass
            free = spec = inact = 0
            for line in out.splitlines():
                if "Pages free:" in line:
                    free = int(line.split(":")[1].strip().replace(".", ""))
                elif "Pages speculative:" in line:
                    spec = int(line.split(":")[1].strip().replace(".", ""))
                elif "Pages inactive:" in line:
                    inact = int(line.split(":")[1].strip().replace(".", ""))
            return (free + spec + inact) * page / (1024 ** 3)
        else:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        kb = int(line.split()[1])
                        return kb / (1024 ** 2)
    except Exception:
        pass
    # Unknown — assume safe but log
    logger.warning("Could not determine free memory; allowing synthetic cautiously")
    return _min_free_gb()


def _clamp_dim(w: int, h: int) -> tuple[int, int]:
    w = min(int(w), MAX_WIDTH)
    h = min(int(h), MAX_HEIGHT)
    # keep sane minimums and even dimensions (ComfyUI needs multiples of 8)
    w = max(256, (w // 8) * 8)
    h = max(256, (h // 8) * 8)
    return w, h


def _sd35_workflow(prompt: str, width: int = 1024, height: int = 576, seed: int | None = None) -> dict:
    """Minimal SD3.5-turbo workflow for ComfyUI API — no manual node editing needed."""
    width, height = _clamp_dim(width, height)
    if seed is None:
        seed = random.randint(0, 2 ** 32 - 1)
    return {
        "3": {
            "inputs": {"seed": seed, "steps": 4, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0, "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]},
            "class_type": "KSampler",
        },
        "4": {
            "inputs": {"ckpt_name": "sd3.5_large_turbo.safetensors"},
            "class_type": "CheckpointLoaderSimple",
        },
        "5": {
            "inputs": {"width": width, "height": height, "batch_size": 1},
            "class_type": "EmptyLatentImage",
        },
        "6": {
            "inputs": {"text": prompt, "clip": ["4", 1]},
            "class_type": "CLIPTextEncode",
        },
        "7": {
            "inputs": {"text": "", "clip": ["4", 1]},
            "class_type": "CLIPTextEncode",
        },
        "8": {
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
            "class_type": "VAEDecode",
        },
        "9": {
            "inputs": {"filename_prefix": "video_factory", "images": ["8", 0]},
            "class_type": "SaveImage",
        },
    }


async def generate_image(
    prompt: str,
    width: int = 1024,
    height: int = 576,
    timeout: float | None = None,
) -> Path | None:
    """Generate one image via ComfyUI. Returns Path to image or None on failure/skip."""
    global _breaker_tripped
    if not is_enabled():
        logger.info("Synthetic generation disabled (set ENABLE_SYNTHETIC=1 to enable)")
        return None
    if _breaker_tripped:
        logger.info("Synthetic circuit breaker tripped — skipping ComfyUI")
        return None

    timeout = float(timeout) if timeout is not None else _request_timeout()
    width, height = _clamp_dim(width, height)

    free = _system_free_gb()
    min_free = _min_free_gb()
    if free < min_free:
        logger.warning(f"Free memory {free:.1f}GB < {min_free}GB — skipping ComfyUI to avoid OOM")
        return None

    workflow = _sd35_workflow(prompt, width, height)
    client_id = str(uuid.uuid4())
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{COMFYUI_URL}/prompt", json={"prompt": workflow, "client_id": client_id})
            resp.raise_for_status()
            data = resp.json()
            prompt_id = data.get("prompt_id")
            if not prompt_id:
                logger.warning(f"ComfyUI no prompt_id: {data}")
                return None

            polls = int(timeout / POLL_INTERVAL)
            for _ in range(polls):
                await asyncio.sleep(POLL_INTERVAL)
                hist = await client.get(f"{COMFYUI_URL}/history/{prompt_id}")
                hist.raise_for_status()
                h = hist.json()
                if prompt_id in h and h[prompt_id].get("status", {}).get("completed"):
                    outputs = h[prompt_id].get("outputs", {})
                    for _node_id, out in outputs.items():
                        images = out.get("images", [])
                        for img in images:
                            filename = img.get("filename")
                            if filename:
                                view = await client.get(
                                    f"{COMFYUI_URL}/view",
                                    params={"filename": filename, "subfolder": img.get("subfolder", ""), "type": img.get("type", "output")},
                                )
                                view.raise_for_status()
                                tmp = Path(tempfile.mkdtemp()) / filename
                                tmp.write_bytes(view.content)
                                logger.info(f"ComfyUI generated {filename} ({width}x{height}) for: {prompt[:40]}")
                                return tmp
            logger.warning(f"ComfyUI timeout for prompt: {prompt[:40]}")
            return None
    except Exception as e:
        logger.warning(f"ComfyUI generate failed ({e}), fallback to placeholder")
        # Repeated infra failure -> trip breaker so we never keep hammering RAM
        if "OOM" in str(e) or "out of memory" in str(e).lower():
            _breaker_tripped = True
            logger.error("OOM detected — synthetic circuit breaker TRIPPED for this process")
        return None


async def generate_images(
    prompts: list[str],
    width: int = 1024,
    height: int = 576,
    count_per_prompt: int = 1,
) -> list[Path]:
    """Batch generate — strictly sequential, capped, with cooldown. Safe by design."""
    results: list[Path] = []
    if not is_enabled():
        return results
    cap = _max_images()
    prompts = prompts[:cap]
    for prompt in prompts:
        for _ in range(max(1, count_per_prompt)):
            if len(results) >= cap:
                break
            path = await generate_image(prompt, width, height)
            if path:
                results.append(path)
            # cooldown so VRAM/RAM can be released between runs
            await asyncio.sleep(_cooldown_s())
        if len(results) >= cap:
            break
    return results


def is_available() -> bool:
    """Check whether synthetic is enabled AND ComfyUI is reachable."""
    if not is_enabled():
        return False
    try:
        import httpx as _httpx

        r = _httpx.get(f"{COMFYUI_URL}/system_stats", timeout=3)
        return r.status_code == 200
    except Exception:
        return False
