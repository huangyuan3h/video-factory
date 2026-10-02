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


# Human + machine explanation for every code. `vf explain <CODE>` prints one entry.
# Each entry: cause (why it happens), fix (what to do), next (exact command to run).
EXPLAIN: dict[str, dict[str, str]] = {
    E_OK: {
        "cause": "Command succeeded.",
        "fix": "Nothing to fix.",
        "next": "vf status --json",
    },
    E_USAGE: {
        "cause": "Wrong flags or arguments (exit 2).",
        "fix": "Re-run with the required flags; see the command's --help examples.",
        "next": "vf <subcommand> --help",
    },
    E_CREDENTIALS: {
        "cause": "Missing/expired credentials (cookies, token.json, invalid_grant, login needed) or YouTube public without --force.",
        "fix": "Re-auth (scripts/youtube_reauth.sh), check login cookies, or keep safe defaults (YT unlisted, others draft-only). Never commit secrets.",
        "next": "vf doctor --json",
    },
    E_BACKEND_OVERLOAD: {
        "cause": "AI/backend overloaded, timed out, or the pipeline failed to import (503/timeout/import-fail).",
        "fix": "Wait and retry with --resume (skips finished steps). One heavy job at a time; check memory_pressure first.",
        "next": "vf doctor --json",
    },
    E_PNG_READ: {
        "cause": "A .png/.jpg was opened with the file-read tool (crashes the session: 'Invalid upload request') or a chart image is unreadable.",
        "fix": "Never open .png/.jpg with the file-read tool; inspect key-frames via Python/PIL/OCR text checks only.",
        "next": "vf qa --dir <TASK_DIR> --json",
    },
    E_QA_FAIL: {
        "cause": "A QA gate failed (overflow/repeat/transition/jargon/beats/sync/encode) or render/publish refused fail-closed.",
        "fix": "Read the offender list, fix the script/cards, re-run QA. Override only with --force --force-reason (logged to state/force_log.jsonl).",
        "next": "vf qa --dir <TASK_DIR> --json",
    },
    E_MEMORY: {
        "cause": "Low disk (<5GB free) or memory pressure; the command refused to start a heavy job.",
        "fix": "Free disk space (data/output is transient-heavy at 1440p), wait for other jobs, then retry. Never kill processes you did not start.",
        "next": "vf doctor --json",
    },
    E_BLOCKED: {
        "cause": "Blocked: a precondition is missing (no task dir, missing --approved-script, missing --manifest).",
        "fix": "Provide the missing input (usually --dir/--approved-script/--manifest) or run the earlier pipeline step first.",
        "next": "vf status --json",
    },
    E_NOT_FOUND: {
        "cause": "Episode not in state/episodes.json (--ep typo or not migrated yet).",
        "fix": "Check the episode number (25 or ep25), list the ledger, or re-run scripts/migrate_ledger.py (read-only on old ledgers).",
        "next": "vf status --json",
    },
    E_LEDGER: {
        "cause": "state/episodes.json missing or unreadable.",
        "fix": "Rebuild it with scripts/migrate_ledger.py (reads old ledgers, never writes them). Old ledgers stay read-only for daily routines.",
        "next": "vf status --json",
    },
}


def explain(code: str | None) -> dict[str, str]:
    """Explanation entry for an error code (case-insensitive, accepts 'E_QA_FAIL' or 'qa-fail')."""
    if not code:
        return {"code": E_BLOCKED, **EXPLAIN[E_BLOCKED]}
    key = str(code).strip().upper().replace("-", "_").replace(" ", "_")
    if not key.startswith("E_"):
        key = f"E_{key}"
    entry = EXPLAIN.get(key)
    if entry is None:
        return {"code": key, "cause": "Unknown code.", "fix": "See vf explain E_OK for the code list.", "next": "vf explain E_OK"}
    return {"code": key, **entry}
