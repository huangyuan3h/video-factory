"""Task queue abstraction — Redis if available, else in-memory + DB poll.

API keeps POST /api/videos/generate fast (enqueue <50ms).
Worker is a separate process: `uv run python -m src.worker` or `celery`-like loop.
For lambda-absent GPU tasks, always prefer dedicated worker.
"""

import json
import logging
import os
from typing import Callable

logger = logging.getLogger(__name__)

_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    url = os.getenv("REDIS_URL") or os.getenv("REDIS_TLS_URL") or ""
    if not url:
        # Try Settings
        try:
            from .config import settings
            url = getattr(settings, "redis_url", "") or ""
        except Exception:
            url = ""
    if not url:
        return None
    try:
        import redis  # type: ignore

        _redis_client = redis.from_url(url, decode_responses=True)
        _redis_client.ping()
        logger.info(f"Queue: Redis at {url.split('@')[-1]}")
        return _redis_client
    except Exception as e:
        logger.warning(f"Redis unavailable ({e}), fallback to memory/DB")
        return None


QUEUE_KEY = "video_factory:jobs"


def enqueue(job: dict) -> bool:
    """Try Redis LPUSH, else DB poll fallback returns False."""
    r = _get_redis()
    if r:
        try:
            r.lpush(QUEUE_KEY, json.dumps(job, ensure_ascii=False))
            return True
        except Exception as e:
            logger.warning(f"Redis enqueue failed: {e}")
    return False


def dequeue(block: bool = True, timeout: int = 5) -> dict | None:
    r = _get_redis()
    if not r:
        return None
    try:
        if block:
            res = r.brpop(QUEUE_KEY, timeout=timeout)
            if res:
                _, data = res
                return json.loads(data)
        else:
            data = r.rpop(QUEUE_KEY)
            if data:
                return json.loads(data)
    except Exception as e:
        logger.warning(f"Redis dequeue failed: {e}")
    return None


def queue_depth() -> int:
    r = _get_redis()
    if r:
        try:
            return int(r.llen(QUEUE_KEY))
        except Exception:
            pass
    # Fallback: count pending in DB/video_tasks
    try:
        from .services.video_service import video_tasks

        return sum(1 for v in video_tasks.values() if v.get("status") == "pending")
    except Exception:
        return 0
