"""Canonical error codes surfaced in vf --json (Phase 3).

E_CREDENTIALS: missing/expired credentials (cookies, token.json, invalid_grant, login needed).
E_BACKEND_OVERLOAD: AI/backend overload, 503, timeout, import-fail of pipeline.
E_PNG_READ: PNG/JPG read via file-read tool or unreadable chart image (Invalid upload request guard).
E_QA_FAIL: QA gate FAIL, render/publish fail-closed refusal.
E_MEMORY: low disk (<5GB), memory pressure, missing task dir space.

Plus E_USAGE (exit 2) and E_BLOCKED/E_NOT_FOUND for completeness; every vf --json
payload carries `error_code` (E_OK when ok).
"""
from __future__ import annotations

E_OK = "E_OK"
E_USAGE = "E_USAGE"
E_CREDENTIALS = "E_CREDENTIALS"
E_BACKEND_OVERLOAD = "E_BACKEND_OVERLOAD"
E_PNG_READ = "E_PNG_READ"
E_QA_FAIL = "E_QA_FAIL"
E_MEMORY = "E_MEMORY"
E_BLOCKED = "E_BLOCKED"
E_NOT_FOUND = "E_NOT_FOUND"
E_LEDGER = "E_LEDGER"

ALL_CODES = frozenset(
    {
        E_OK,
        E_USAGE,
        E_CREDENTIALS,
        E_BACKEND_OVERLOAD,
        E_PNG_READ,
        E_QA_FAIL,
        E_MEMORY,
        E_BLOCKED,
        E_NOT_FOUND,
        E_LEDGER,
    }
)

# Map internal vf error keys -> canonical codes (keys use underscores;
# lookup normalises hyphens/spaces to underscores).
_KEY_MAP = {
    "usage": E_USAGE,
    "blocked": E_BLOCKED,
    "ledger_missing": E_LEDGER,
    "ledger_read_fail": E_LEDGER,
    "not_found": E_NOT_FOUND,
    "missing_approved_script": E_BLOCKED,
    "import_fail": E_BACKEND_OVERLOAD,
    "missing_script_json": E_BLOCKED,
    "missing_script.json": E_BLOCKED,
    "no_task_dir": E_BLOCKED,
    "low_disk": E_MEMORY,
    "low_memory": E_MEMORY,
    "credentials_missing": E_CREDENTIALS,
    "public_needs_force": E_CREDENTIALS,
    "qa_fail": E_QA_FAIL,
    "force_needed": E_QA_FAIL,
    "png_read": E_PNG_READ,
    "backend_overload": E_BACKEND_OVERLOAD,
    "fail": E_QA_FAIL,
}


def code_for(key: str | None) -> str:
    """Canonical code for an internal error key (defaults to E_BLOCKED)."""
    if not key:
        return E_BLOCKED
    k = str(key).strip().lower().replace("-", "_").replace(" ", "_")
    # Direct code passthrough.
    upper = str(key).strip().upper()
    if upper in ALL_CODES:
        return upper
    if k in _KEY_MAP:
        return _KEY_MAP[k]
    # Substring heuristics for backend messages.
    if "invalid_grant" in k or "credential" in k or "login" in k or "unauthorized" in k:
        return E_CREDENTIALS
    if "overload" in k or "503" in k or "timeout" in k or "overloaded" in k:
        return E_BACKEND_OVERLOAD
    if "png" in k or "invalid upload" in k.replace("_", " "):
        return E_PNG_READ
    if "qa" in k or "fail" in k:
        return E_QA_FAIL
    if "memory" in k or "disk" in k or "space" in k:
        return E_MEMORY
    return E_BLOCKED
