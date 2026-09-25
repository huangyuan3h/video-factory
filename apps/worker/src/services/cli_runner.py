"""Shared in-process CLI runner for indicator / book / general / news episodes.

The scripts under ``apps/worker/scripts`` are thin wrappers around this module so
the argument parsing, request building and status reporting can be unit tested
without spawning a process or hitting the network. ``run_pipeline`` calls
:func:`src.services.video_service.run_video_generation` in-process, which is the
same code path the API/queue uses.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

from ..config import settings
from .video_service import run_video_generation, video_tasks

logger = logging.getLogger(__name__)

_SUPPORTED_TYPES = ("general", "book", "news")

# File keys surfaced by ``status.json`` -> human label in the CLI output.
_RESULT_FILES = (
    ("script", "script.json"),
    ("script_md", "script.md"),
    ("script_review", "script_review.md"),
    ("video", "final video"),
)


def slugify(text: str | None) -> str:
    """URL/fs-safe slug that keeps CJK characters (``isalnum`` accepts them)."""
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", str(text or "")).strip("-")
    return (slug[:40] or "episode").lower()


def default_out_dir(content_type: str, name: str | None = None) -> Path:
    """``output_dir/<type>/<slug>/<timestamp-uuid>`` default task dir."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    unique = uuid.uuid4().hex[:6]
    return Path(settings.output_dir) / content_type / slugify(name) / f"{stamp}-{unique}"


def read_status(task_dir: Path) -> dict:
    status_file = Path(task_dir) / "status.json"
    if not status_file.exists():
        return {}
    try:
        return json.loads(status_file.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - best effort reporting only
        return {}


def run_pipeline(request, task_dir: Path) -> dict:
    """Run the full in-process pipeline and return ``{task_id, task_dir, status}``."""
    task_dir = Path(task_dir)
    task_dir.mkdir(parents=True, exist_ok=True)
    task_id = f"video-{uuid.uuid4().hex[:8]}"
    video_tasks.setdefault(
        task_id,
        {
            "id": task_id,
            "task_uuid": uuid.uuid4().hex,
            "task_dir": str(task_dir),
            "status": "pending",
            "progress": 0.0,
            "current_step": 0,
            "message": "任务已创建，等待开始...",
            "created_at": datetime.now().isoformat(),
            "content_type": getattr(request, "content_type", "general"),
            "type": getattr(request, "content_type", "general"),
            "payload": request.model_dump() if hasattr(request, "model_dump") else {},
        },
    )
    run_video_generation(task_id, request, task_dir)
    return {"task_id": task_id, "task_dir": str(task_dir), "status": read_status(task_dir)}


def result_exit_code(result: dict) -> int:
    status = (result.get("status") or {}).get("status")
    return 0 if status in ("completed", "script_ready") else 1


def format_result(result: dict) -> str:
    status = result.get("status") or {}
    files = status.get("files") or {}
    lines = [
        f"TASK_DIR: {result.get('task_dir')}",
        f"status: {status.get('status', 'unknown')}",
    ]
    if result.get("task_id"):
        lines.append(f"task_id: {result['task_id']}")
    for key, label in _RESULT_FILES:
        if files.get(key):
            lines.append(f"{label}: {files[key]}")
    if status.get("error"):
        lines.append(f"error: {status['error']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Argument parsers
# --------------------------------------------------------------------------- #


def build_indicator_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="indicator_episode.py",
        description=(
            "Generate a manifest-driven type=indicator chart episode. One narration "
            "segment is produced per manifest chart, the title card becomes the cover, "
            "and script-only stops after writing script.json/script.md for review."
        ),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Path to manifest.json or to the charts dir containing it",
    )
    parser.add_argument(
        "--approved-script",
        type=Path,
        help="Render this script.json (from an earlier --script-only run) verbatim",
    )
    parser.add_argument("--title", help="Optional title (defaults to the manifest title)")
    parser.add_argument(
        "--context",
        type=Path,
        help="Optional extra context file (e.g. summary_zh.md); facts only",
    )
    parser.add_argument("--voice", help="Optional edge-tts voice override")
    parser.add_argument("--out-dir", type=Path, help="Explicit task/output directory")
    parser.add_argument(
        "--script-only",
        action="store_true",
        help="Generate + review the script and stop (no TTS/materials/render)",
    )
    return parser


def build_generic_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generate_episode.py",
        description="Generate a book/general/news episode in-process (script + render or script-only).",
    )
    parser.add_argument(
        "--type",
        required=True,
        choices=_SUPPORTED_TYPES,
        help="Pipeline type",
    )
    parser.add_argument("--title", help="Episode title")
    parser.add_argument(
        "--content-file",
        type=Path,
        help="UTF-8 file with the narration source text (book/general)",
    )
    parser.add_argument(
        "--series-episodes",
        type=Path,
        help="Optional episodes.json; combined with --episode-index to pick one",
    )
    parser.add_argument(
        "--episode-index",
        type=int,
        default=0,
        help="0-based index into --series-episodes (default 0)",
    )
    parser.add_argument("--voice", help="Optional edge-tts voice override")
    parser.add_argument("--out-dir", type=Path, help="Explicit task/output directory")
    parser.add_argument(
        "--script-only",
        action="store_true",
        help="Generate + review the script and stop (no TTS/materials/render)",
    )
    parser.add_argument(
        "--approved-script",
        type=Path,
        help="Render this script.json instead of generating one",
    )
    return parser


# --------------------------------------------------------------------------- #
# Request builders
# --------------------------------------------------------------------------- #


def build_indicator_request(args) -> tuple[object, str]:
    """Build a ``VideoGenerateRequest`` for an indicator episode + a name."""
    from ..routes.videos import VideoGenerateRequest

    if not args.manifest and not args.approved_script:
        raise ValueError("--manifest is required unless --approved-script is given")

    kwargs: dict = {"type": "indicator"}
    manifest = getattr(args, "manifest", None)
    approved = getattr(args, "approved_script", None)
    title = getattr(args, "title", None)
    if title:
        kwargs["title"] = title
    if getattr(args, "voice", None):
        kwargs["voice"] = args.voice
    if manifest:
        kwargs["custom_visuals_manifest"] = str(manifest)
    if approved:
        kwargs["approved_script"] = str(approved)
    if getattr(args, "script_only", False):
        kwargs["script_only"] = True

    context = getattr(args, "context", None)
    if context:
        kwargs["content"] = Path(context).read_text(encoding="utf-8")

    name = title or ""
    if not name and manifest:
        manifest_path = Path(manifest)
        name = manifest_path.name if manifest_path.is_dir() else manifest_path.parent.name
    if not name and approved:
        name = Path(approved).parent.name
    return VideoGenerateRequest(**kwargs), name or "indicator"


def build_generic_request(args) -> tuple[object, str]:
    """Build a ``VideoGenerateRequest`` for book/general/news + a name."""
    from ..routes.videos import VideoGenerateRequest

    kwargs: dict = {"type": args.type}
    title = getattr(args, "title", None)
    content = None

    series_episodes = getattr(args, "series_episodes", None)
    if series_episodes:
        data = json.loads(Path(series_episodes).read_text(encoding="utf-8"))
        episodes = data if isinstance(data, list) else (data.get("episodes") or [])
        index = getattr(args, "episode_index", 0) or 0
        if not episodes or index < 0 or index >= len(episodes):
            raise ValueError(
                f"episode index {index} out of range for {series_episodes} "
                f"({len(episodes)} episodes)"
            )
        episode = episodes[index]
        title = title or episode.get("title")
        content = episode.get("content") or episode.get("text")
        if not kwargs.get("series_id") and episode.get("series_id"):
            kwargs["series_id"] = episode["series_id"]

    content_file = getattr(args, "content_file", None)
    if content_file:
        content = content or Path(content_file).read_text(encoding="utf-8")

    if title:
        kwargs["title"] = title
    if content is not None:
        kwargs["content"] = content
    if getattr(args, "voice", None):
        kwargs["voice"] = args.voice
    if getattr(args, "script_only", False):
        kwargs["script_only"] = True
    if getattr(args, "approved_script", None):
        kwargs["approved_script"] = str(args.approved_script)

    return VideoGenerateRequest(**kwargs), (title or args.type)


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #


def _run_cli(request, out_dir, name: str, content_type: str) -> int:
    task_dir = Path(out_dir) if out_dir else default_out_dir(content_type, name)
    try:
        result = run_pipeline(request, task_dir)
    except Exception as exc:  # noqa: BLE001 - CLI must report, not traceback
        logger.error("Episode generation failed: %s", exc, exc_info=True)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(format_result(result))
    return result_exit_code(result)


def indicator_main(argv=None) -> int:
    parser = build_indicator_parser()
    args = parser.parse_args(argv)
    if not args.manifest and not args.approved_script:
        parser.error("--manifest is required unless --approved-script is given")
    try:
        request, name = build_indicator_request(args)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return _run_cli(request, args.out_dir, name, "indicator")


def generic_main(argv=None) -> int:
    parser = build_generic_parser()
    args = parser.parse_args(argv)
    try:
        request, name = build_generic_request(args)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return _run_cli(request, args.out_dir, name, args.type)
