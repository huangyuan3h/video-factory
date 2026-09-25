"""Loader for the research pipeline's chart ``manifest.json``.

The canonical schema is a JSON list::

    [
      {"file": "00_title_card.png", "section": "intro", "title": "...",
       "key_point": "...", "suggested_seconds": 15},
      ...
    ]

The loader is deliberately tolerant: a top-level object with ``charts`` or
``items`` (+ optional ``indicator_id`` / ``title`` / ``indicator_name``) is
accepted, ``file`` aliases (``path`` / ``image``), ``suggested_seconds`` aliases
(``seconds`` / ``duration``) and ``key_point`` aliases (``keypoint`` / ``point``)
all work, and the manifest order is preserved. Unknown sections are kept but
warn. ``file`` is resolved relative to the manifest's directory (absolute paths
are allowed too).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from ..script_review import number_tokens

logger = logging.getLogger(__name__)

#: Canonical section order used by the script prompt / docs.
SECTION_SEQUENCE = (
    "intro",
    "explain",
    "retail_usage",
    "history",
    "why_not",
    "summary",
)
KNOWN_SECTIONS = frozenset(SECTION_SEQUENCE)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

_FILE_KEYS = ("file", "path", "image")
_SECONDS_KEYS = ("suggested_seconds", "seconds", "duration")
_KEY_POINT_KEYS = ("key_point", "keypoint", "point")


@dataclass
class ManifestItem:
    """One chart in the manifest (kept in manifest order)."""

    index: int
    file: Path
    section: str
    title: str
    key_point: str
    suggested_seconds: int | None


@dataclass
class IndicatorManifest:
    """Loaded manifest: charts dir, ordered items, title and indicator id."""

    charts_dir: Path
    items: list[ManifestItem]
    title: str
    indicator_id: str
    manifest_path: Path | None = None

    @property
    def cover(self) -> ManifestItem:
        """Title-card item: first ``intro`` chart whose name contains ``title``.

        Falls back to the first item so a manifest without a title card still
        yields a usable cover.
        """
        for item in self.items:
            if item.section == "intro" and "title" in item.file.name.lower():
                return item
        return self.items[0]


def _pick(raw: dict, keys: tuple[str, ...]):
    for key in keys:
        if key in raw and raw[key] is not None:
            return raw[key]
    return None


def _coerce_seconds(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _normalise_section(value) -> str:
    return str(value or "").strip().lower()


def _resolve_chart_file(charts_dir: Path, raw_file) -> Path:
    candidate = Path(str(raw_file)).expanduser()
    if not candidate.is_absolute():
        candidate = charts_dir / candidate
    candidate = candidate.resolve()
    if candidate.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError(
            f"图表文件扩展名不支持 / unsupported chart extension: {candidate} "
            "(仅支持 .png/.jpg/.jpeg/.webp)"
        )
    if not candidate.is_file():
        raise ValueError(f"图表文件不存在 / chart file not found: {candidate}")
    return candidate


def _iter_raw_items(data) -> tuple[list, dict]:
    if isinstance(data, list):
        return data, {}
    if isinstance(data, dict):
        raw_items = data.get("charts")
        if raw_items is None:
            raw_items = data.get("items")
        if raw_items is None:
            raise ValueError(
                "图表清单缺少 charts/items 列表 / manifest object has no 'charts' or 'items' list"
            )
        if not isinstance(raw_items, list):
            raise ValueError(
                "图表清单 charts/items 必须是列表 / manifest 'charts'/'items' must be a list"
            )
        return raw_items, data
    raise ValueError("图表清单格式不支持 / unsupported manifest format (expected list or object)")


def load_manifest(path: str | Path) -> IndicatorManifest:
    """Load a chart manifest from a ``manifest.json`` file or a charts dir."""
    given = Path(str(path)).expanduser()
    if given.is_dir():
        manifest_path = given / "manifest.json"
        charts_dir = given
    else:
        manifest_path = given
        charts_dir = given.parent
    manifest_path = manifest_path.resolve()
    charts_dir = charts_dir.resolve()

    if not manifest_path.is_file():
        raise ValueError(
            f"图表清单不存在 / manifest not found: {manifest_path}"
        )
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except ValueError as exc:  # includes JSONDecodeError
        raise ValueError(
            f"图表清单不是合法 JSON / invalid manifest JSON: {manifest_path}: {exc}"
        ) from exc

    raw_items, meta = _iter_raw_items(data)
    if not raw_items:
        raise ValueError(f"图表清单为空 / manifest has no charts: {manifest_path}")

    items: list[ManifestItem] = []
    for position, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            raise ValueError(
                f"图表项必须是对象 / manifest item must be an object: {raw!r}"
            )
        raw_file = _pick(raw, _FILE_KEYS)
        if raw_file is None or not str(raw_file).strip():
            raise ValueError(
                f"图表项缺少 file 字段 / manifest item missing 'file': {raw!r}"
            )
        resolved = _resolve_chart_file(charts_dir, raw_file)
        section = _normalise_section(raw.get("section"))
        if section and section not in KNOWN_SECTIONS:
            logger.warning(
                "未知章节 section=%r（保留原值）/ unknown manifest section", section
            )
        items.append(
            ManifestItem(
                index=position,
                file=resolved,
                section=section,
                title=str(raw.get("title") or "").strip(),
                key_point=str(_pick(raw, _KEY_POINT_KEYS) or "").strip(),
                suggested_seconds=_coerce_seconds(_pick(raw, _SECONDS_KEYS)),
            )
        )

    title = str(
        (meta.get("title") if isinstance(meta, dict) else None)
        or (meta.get("indicator_name") if isinstance(meta, dict) else None)
        or ""
    ).strip()
    indicator_id = str(
        (meta.get("indicator_id") if isinstance(meta, dict) else None) or ""
    ).strip()
    if not title:
        title = indicator_id or charts_dir.name
    if not indicator_id:
        indicator_id = title
    return IndicatorManifest(
        charts_dir=charts_dir,
        items=items,
        title=title,
        indicator_id=indicator_id,
        manifest_path=manifest_path,
    )


def required_numbers(text: str) -> list[str]:
    """Number tokens in ``text`` that a segment must reproduce verbatim.

    Reuses :func:`src.services.script_review.number_tokens` so the indicator
    number check and the proofread number guard share one definition. Duplicates
    are collapsed, first-seen order preserved (the extractor returns sorted).
    """
    seen: dict[str, None] = {}
    for token in number_tokens(text):
        seen.setdefault(token, None)
    return list(seen)
