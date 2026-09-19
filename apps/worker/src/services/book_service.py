"""Book -> series splitter.

Splits plain text / markdown / PDF books into per-chapter episodes suitable for
short-form video generation.

v1 keeps the DB schema untouched: episodes are persisted as a JSON sidecar at
``data/series/<slug>/episodes.json`` so no migration is needed. Each episode is
``{"index", "title", "content", "char_count"}``.
"""

from __future__ import annotations

import io
import json
import logging
import re
from pathlib import Path

from ..config import settings

logger = logging.getLogger(__name__)


# Chapter-heading patterns are tried in order; matches are de-duplicated by the
# line they start on (a markdown "## 第一章" matches two patterns).
#
# The `第N章` pattern requires a separator (space/full-width space/colon...) or
# end-of-line after the marker. This rejects in-prose sentences such as
# "第一章是……" that extracted PDF/OCR text frequently produces.
_HEADING_PATTERNS = [
    re.compile(r"^\s*#{1,6}\s+(?P<title>[^\n#][^\n]*?)\s*#*\s*$", re.MULTILINE),
    re.compile(
        r"^\s*(?P<title>第[零一二三四五六七八九十百千万两0-9]+[章节回卷部篇集]"
        r"(?:[\s\u3000:：、.·・\-—]+[^\n]{0,40})?)\s*$",
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

# A section body shorter than this is treated as outline-like (a TOC entry or a
# stray heading) and merged forward instead of becoming a standalone episode.
_MIN_OUTLINE_BODY = 160

_PDF_MAGIC = b"%PDF"

ALLOWED_BOOK_EXTENSIONS = (".txt", ".md", ".markdown", ".pdf")


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


def _heading_body_lengths(text: str, headings: list[tuple[int, int, str]]) -> list[int]:
    """Characters of body between each heading and the next one."""
    lengths: list[int] = []
    for i, (_pos, end, _title) in enumerate(headings):
        next_pos = headings[i + 1][0] if i + 1 < len(headings) else len(text)
        lengths.append(max(0, next_pos - end))
    return lengths


def _title_key(title: str) -> str:
    """Normalized title used to spot a chapter title repeated in a TOC.

    Strips whitespace and TOC dot-leaders/page numbers, e.g.
    ``第一章 央行的困境 .... 12`` and ``第一章　央行的困境`` compare equal.
    """
    key = re.sub(r"[\s\u3000]+", "", title or "")
    key = re.sub(r"[.·・•‧…]{2,}\d*$", "", key)
    return key.lower()


def _select_real_headings(
    text: str, headings: list[tuple[int, int, str]]
) -> list[tuple[int, int, str]]:
    """Drop TOC copies of a chapter in favour of the real body occurrence.

    Both a front *and* a back TOC can repeat the same chapter title. For any
    duplicated title we keep the occurrence with the longest following body
    (the real chapter), so neither TOC wins just by being last.
    """
    if not headings:
        return []
    bodies = _heading_body_lengths(text, headings)
    groups: dict[str, list[int]] = {}
    for i, (_pos, _end, title) in enumerate(headings):
        groups.setdefault(_title_key(title), []).append(i)

    keep: set[int] = set()
    for idxs in groups.values():
        if len(idxs) == 1:
            keep.add(idxs[0])
        else:
            keep.add(max(idxs, key=lambda i: (bodies[i], i)))
    return [h for i, h in enumerate(headings) if i in keep]


def _is_outline_like(content: str) -> bool:
    """True for TOC/heading noise: very short or a wall of short lines."""
    content = (content or "").strip()
    if not content:
        return True
    if len(content) < _MIN_OUTLINE_BODY:
        return True
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    if len(lines) >= 4:
        short = sum(1 for ln in lines if len(ln) <= 14)
        if short / len(lines) >= 0.8:
            return True
    return False


def _filter_to_real_chapters(
    text: str, headings: list[tuple[int, int, str]]
) -> list[tuple[int, int, str]]:
    """Keep only headings with a substantial following body.

    A TOC lists chapters as bare titles, so those headings have tiny bodies.
    Real chapter headings are followed by a much larger body. We only apply the
    filter when at least two headings qualify, otherwise every heading is kept
    (a genuine single-chapter book must not be dropped).
    """
    if len(headings) < 2:
        return headings
    bodies = _heading_body_lengths(text, headings)
    max_body = max(bodies) if bodies else 0
    threshold = max(_MIN_OUTLINE_BODY, int(max_body * 0.2))
    real_idx = {i for i, body in enumerate(bodies) if body >= threshold}
    if len(real_idx) < 2:
        return headings
    return [h for i, h in enumerate(headings) if i in real_idx]


def _merge_outline_sections(
    sections: list[tuple[str, str]], max_chars: int
) -> list[tuple[str, str]]:
    """Merge outline-like sections forward so TOC noise never becomes an episode.

    An empty/heading-only section absorbs the next section (even a real one);
    a short-but-non-empty section only merges with other outline-like sections
    so a genuine chapter body is never swallowed.
    """
    merged: list[tuple[str, str]] = []
    i = 0
    total = len(sections)
    while i < total:
        title, content = sections[i]
        j = i
        while _is_outline_like(content) and j + 1 < total:
            nxt_title, nxt_content = sections[j + 1]
            if content.strip() and not _is_outline_like(nxt_content):
                break
            j += 1
            content = (content + "\n\n" + nxt_title + "\n" + nxt_content).strip()
            if max_chars and len(content) >= max_chars:
                break
        merged.append((title, content))
        i = j + 1
    return merged


def _split_by_headings(text: str, max_chars: int) -> list[tuple[str, str]]:
    headings = _collect_headings(text)
    if not headings:
        return []
    selected = _select_real_headings(text, headings)
    selected = _filter_to_real_chapters(text, selected)
    if not selected:
        return []
    sections: list[tuple[str, str]] = []
    for i, (_pos, heading_end, title) in enumerate(selected):
        next_pos = selected[i + 1][0] if i + 1 < len(selected) else len(text)
        sections.append((title, text[heading_end:next_pos].strip()))
    return _merge_outline_sections(sections, max_chars)


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

    sections = _split_by_headings(normalized, max_chars)
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


def looks_like_pdf(raw: bytes | None) -> bool:
    """True when the bytes start with the PDF magic header."""
    if not raw:
        return False
    return bytes(raw[:1024]).lstrip().startswith(_PDF_MAGIC)


def extract_pdf_text(raw: bytes) -> str:
    """Extract text from PDF bytes with pypdf.

    Raises ``ValueError`` for unreadable/encrypted/image-only PDFs so the route
    can answer with HTTP 400 instead of a 500.
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise ValueError("PDF 导入需要安装 pypdf（请运行 uv sync）") from exc

    try:
        reader = PdfReader(io.BytesIO(raw))
        pages: list[str] = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception as e:  # noqa: BLE001 - one bad page shouldn't kill import
                logger.warning(f"PDF page text extraction failed: {e}")
        text = "\n\n".join(p for p in pages if p).strip()
    except Exception as exc:  # noqa: BLE001
        raise ValueError("无法解析 PDF 文件，请确认文件未加密或损坏") from exc

    if not text:
        raise ValueError("PDF 中未提取到文本（可能是扫描版图片）")
    return text


def decode_text(raw: bytes | None, filename: str | None = None) -> str:
    """Decode uploaded book bytes to text.

    PDFs are detected by file name (``.pdf``) or the ``%PDF`` magic header and
    extracted with pypdf. Everything else is decoded as text, tolerating BOMs
    and common CJK encodings.
    """
    if not raw:
        return ""
    if (filename or "").strip().lower().endswith(".pdf") or looks_like_pdf(raw):
        return extract_pdf_text(raw)
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
