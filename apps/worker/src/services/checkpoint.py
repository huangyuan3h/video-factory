"""Uniform --resume / checkpoint helper (Phase 3).

Every vf command is idempotent: re-run skips finished steps by checking
`status.json` + output hashes. Publishers use draft-dedupe (see publishers
helpers `is_already_published`/`should_refuse_publish`); this module covers
the local pipeline side.

Checkpoint file: <task_dir>/status.json (written by cli_runner) plus
<task_dir>/.vf_checkpoint.json (step -> {inputs_hash, updated_at}).
`should_skip(task_dir, step, inputs_hash)` returns True when the step is
already done with identical inputs.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


def hash_inputs(*parts: str) -> str:
    """Stable sha256 hex (12 chars) of the given input strings."""
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p or "").encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:12]


def hash_file(path: str | Path) -> str | None:
    """sha256 (12 chars) of a file, None when missing/unreadable."""
    try:
        p = Path(path)
        if not p.is_file():
            return None
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()[:12]
    except Exception:
        return None


def checkpoint_path(task_dir: str | Path) -> Path:
    return Path(task_dir) / ".vf_checkpoint.json"


def load_checkpoint(task_dir: str | Path) -> dict:
    try:
        p = checkpoint_path(task_dir)
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def save_checkpoint(task_dir: str | Path, step: str, inputs_hash: str, extra: dict | None = None) -> None:
    try:
        td = Path(task_dir)
        td.mkdir(parents=True, exist_ok=True)
        data = load_checkpoint(td)
        data[str(step)] = {
            "inputs_hash": inputs_hash,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            **(extra or {}),
        }
        checkpoint_path(td).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def should_skip(task_dir: str | Path, step: str, inputs_hash: str) -> bool:
    """True when checkpoint for step matches inputs_hash."""
    try:
        data = load_checkpoint(task_dir)
        entry = data.get(str(step))
        if not isinstance(entry, dict):
            return False
        return bool(entry) and entry.get("inputs_hash") == inputs_hash
    except Exception:
        return False


def status_is_done(task_dir: str | Path) -> tuple[bool, dict]:
    """True when status.json says completed/script_ready (plus parsed status)."""
    try:
        sf = Path(task_dir) / "status.json"
        if not sf.is_file():
            return False, {}
        data = json.loads(sf.read_text(encoding="utf-8"))
        st = (data.get("status") if isinstance(data, dict) else None) or ""
        return st in ("completed", "script_ready"), data
    except Exception:
        return False, {}


def check_resume(task_dir: str | Path | None, step: str, inputs_hash: str) -> dict:
    """Uniform resume decision: {skip: bool, reason: str}."""
    if not task_dir:
        return {"skip": False, "reason": "no-task-dir"}
    done, _ = status_is_done(task_dir)
    if done and should_skip(task_dir, step, inputs_hash):
        return {"skip": True, "reason": "checkpoint-hit"}
    if done:
        # status.json done but checkpoint hash differs -> still skip when the
        # caller only cares about final status (conservative idempotency).
        return {"skip": True, "reason": "status-done"}
    if should_skip(task_dir, step, inputs_hash):
        return {"skip": True, "reason": "checkpoint-hit"}
    return {"skip": False, "reason": "not-done"}
