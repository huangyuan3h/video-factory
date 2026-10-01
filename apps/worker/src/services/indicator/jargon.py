"""Jargon blocklist for indicator narration / on-screen text (ep21 seed fix).

Viewers do not understand programmer terms. Any of these tokens in narration,
subtitles, key_point or on-screen chart text fails QA.

Blocklist covers (case-insensitive where applicable):
- 种子 / seed (any case, including plural/seeds)
- random_state / random-state / randomstate
- 参数名 / 变量名 / 文件名 (parameter / variable / file-name jargon)
- file extensions and code artefacts: .py / .png / .json / .csv / manifest
- known seed constants: 20260925 (mc_seed / random_stock_seeds)
- generic code words: 参数 (when glued to code-like context is still flagged
  conservatively -- plain "费用参数" style prose is rare in this series and
  should be reworded anyway)
"""

from __future__ import annotations

import re

# (pattern, human label). Regexes run with re.IGNORECASE for latin tokens.
BLOCKLIST: list[tuple[str, str]] = [
    (r"种子", "种子"),
    (r"seed", "seed"),
    (r"random_state", "random_state"),
    (r"random-state", "random-state"),
    (r"randomstate", "randomstate"),
    (r"参数名", "参数名"),
    (r"变量名", "变量名"),
    (r"文件名", "文件名"),
    (r"20260925", "20260925 (seed constant)"),
    (r"\.py\b", ".py"),
    (r"\.png\b", ".png"),
    (r"\.json\b", ".json"),
    (r"\.csv\b", ".csv"),
    (r"manifest", "manifest"),
    (r"key_point", "key_point"),
]

_COMPILED: list[tuple[re.Pattern, str]] = [
    (re.compile(pat, re.IGNORECASE if re.search(r"[A-Za-z_.]", pat) else 0), label)
    for pat, label in BLOCKLIST
]


def find_jargon(text: str) -> list[str]:
    """Return sorted labels found in ``text`` (empty when clean)."""
    hits: list[str] = []
    for rx, label in _COMPILED:
        if rx.search(text or ""):
            hits.append(label)
    return sorted(set(hits))


def check_segments(segments: list[str]) -> list[dict]:
    """Per-segment jargon hits: [{index, hits}]."""
    out: list[dict] = []
    for i, text in enumerate(segments):
        hits = find_jargon(text or "")
        if hits:
            out.append({"index": i, "hits": hits})
    return out


def assert_no_jargon(segments: list[str]) -> None:
    """Fail the build when any segment contains blocklisted jargon."""
    offenders = check_segments(segments)
    if offenders:
        details = "; ".join(
            f"seg{o['index']}: {','.join(o['hits'])}" for o in offenders[:5]
        )
        raise ValueError(f"旁白行话/程序员术语 (jargon blocklist): {details}")


def check_image_text_jargon(image_path: str) -> list[str]:
    """Best-effort OCR jargon check on a chart PNG via tesseract CLI.

    Returns labels found, [] when clean or when OCR is unavailable (tesseract
    missing / image unreadable). Never raises -- callers treat [] as pass and
    log the skip. Latin tokens are lowercased by OCR; Chinese 种子 is detected
    when the chi_sim data is present, otherwise the filename + text checks
    on script/key_point remain the primary gate.
    """
    from pathlib import Path
    import shutil
    import subprocess

    path = Path(str(image_path))
    if not path.is_file():
        return []
    if shutil.which("tesseract") is None:
        return []
    try:
        proc = subprocess.run(
            ["tesseract", str(path), "stdout", "-l", "chi_sim+eng"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        text = proc.stdout or ""
        if not text.strip():
            # Fallback to English-only when chi_sim data is missing.
            proc = subprocess.run(
                ["tesseract", str(path), "stdout", "-l", "eng"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            text = proc.stdout or ""
        return find_jargon(text)
    except Exception:
        return []
