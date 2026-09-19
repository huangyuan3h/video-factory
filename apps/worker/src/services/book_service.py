"""Book -> series splitter.

Splits plain text / markdown books into per-chapter episodes suitable for
short-form video generation.

v1 keeps the DB schema untouched: episodes are persisted as a JSON sidecar at
``data/series/<slug>/episodes.json`` so no migration is needed. Each episode is
``{"index", "title", "content", "char_count"}``.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from ..config import settings

logger = logging.getLogger(__name__)


# Chapter-heading patterns are tried in order; matches are de-duplicated by the
# line they start on (a markdown "## 第一章" matches two patterns).
_HEADING_PATTERNS = [
    re.compile(r"^\s*#{1,6}\s+(?P<title>[^\n#][^\n]*?)\s*#*\s*$", re.MULTILINE),
    re.compile(
        r"^\s*(?P<title>第[零一二三四五六七八九十百千万两0-9]+[章节回卷部篇集][^\n]{0,40})\s*$",
        re.MULTILINE,
    ),
    re.compile(
        r"^\s*(?P<title>Chapter\s+\d+[^\n]{0,60})\s*$", re.MULTILINE | re.IGNORECASE
    ),
    re.compile(
        r"^\s*(?P<title>(?:序章|序言|前言|楔子|引子|尾声|后记|番外|Prologue|Epilogue)[^\n]{0,40})\s*$",
        re.MULTILINE | re.IGNORECASE,
    ),
]

_SENTENCE_END = "。！？!?；;\n"


def _normalize(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _collect_headings(text: str) -> list[tuple[int, int, str]]:
    """Return ``(line_start, heading_end, title)`` deduped by ``line_start``."""
    found: dict[int, tuple[int, str]] = {}
    for pattern in _HEADING_PATTERNS:
        for match in pattern.finditer(text):
            title = (match.group("title") or "").strip()
            if not title:
                continue
            line_start = text.rfind("\n", 0, match.start()) + 1
            if line_start not in found:
                found[line_start] = (match.end(), title)
    return sorted((pos, end, title) for pos, (end, title) in found.items())


def _split_by_headings(text: str) -> list[tuple[str, str]]:
    headings = _collect_headings(text)
    if len(headings) < 2:
        return []
    sections: list[tuple[str, str]] = []
    preface = text[: headings[0][0]].strip()
    if preface:
        sections.append(("前言", preface))
    for i, (pos, heading_end, title) in enumerate(headings):
        next_pos = headings[i + 1][0] if i + 1 < len(headings) else len(text)
        sections.append((title, text[heading_end:next_pos].strip()))
    return sections


def _derive_title(chunk: str) -> str:
    first = next((ln.strip() for ln in chunk.splitlines() if ln.strip()), "")
    first = re.sub(r"^#+\s*", "", first)
    return (first[:40] or "未命名章节").strip()


def _split_by_paragraphs(text: str) -> list[tuple[str, str]]:
    """Last-resort split: one episode per blank-line paragraph."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return [(_derive_title(p), p) for p in paragraphs]


def _trim_content(content: str, max_chars: int) -> str:
    content = content.strip()
    if max_chars <= 0 or len(content) <= max_chars:
        return content
    window = content[:max_chars]
    cut = max(window.rfind(ch) for ch in _SENTENCE_END)
    if cut >= max_chars // 2:
        return content[: cut + 1].strip()
    return window.rstrip()


def split_book(
    text: str,
    *,
    max_episodes: int | None = None,
    max_chars: int | None = None,
) -> list[dict]:
    """Split raw book text into a capped list of episode dicts.

    Prefers explicit chapter headings; falls back to blank-line paragraphs.
    Content is trimmed to ``max_chars`` characters per episode.
    """
    max_episodes = max(
        1, int(max_episodes if max_episodes is not None else settings.book_max_episodes)
    )
    max_chars = max(50, int(max_chars if max_chars is not None else settings.book_max_chars))

    normalized = _normalize(text)
    if not normalized:
        return []

    sections = _split_by_headings(normalized)
    if not sections:
        sections = _split_by_paragraphs(normalized)

    episodes: list[dict] = []
    for title, content in sections:
        body = _trim_content(content, max_chars)
        if not body:
            continue
        episodes.append(
            {
                "index": len(episodes) + 1,
                "title": (title or f"第{len(episodes) + 1}集").strip()[:120],
                "content": body,
                "char_count": len(body),
            }
        )
        if len(episodes) >= max_episodes:
            break
    return episodes


def decode_text(raw: bytes | None) -> str:
    """Decode uploaded book bytes, tolerating BOMs and common CJK encodings."""
    if not raw:
        return ""
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def series_dir(slug: str) -> Path:
    safe = (slug or "series").strip().strip("/") or "series"
    return Path(settings.data_dir) / "series" / safe


def episodes_path(slug: str) -> Path:
    return series_dir(slug) / "episodes.json"


def save_episodes(slug: str, episodes: list[dict]) -> Path:
    path = episodes_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(episodes, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def load_episodes(slug: str) -> list[dict]:
    path = episodes_path(slug)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Failed to read episodes for {slug}: {e}")
        return []
    return data if isinstance(data, list) else []
