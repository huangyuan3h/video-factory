"""Per-content-type narration/visual presets.

A single place for the defaults that used to be scattered as ``book_*`` settings
and ad-hoc ``_uses_gentle_pacing`` checks. ``get_type_preset`` merges a type's
overrides over the ``general`` preset so unknown/missing fields degrade to the
neutral defaults (``indicator`` is already a known type, ready for G2).

:func:`resolve_presenter` is the single source of truth for whether the channel
presenter (pen name) is active for a request: it must be enabled globally, for
the content type, and by the request, and the narration must be Chinese.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from .config import DEFAULT_TYPE_PRESETS, settings
from .core.tts.voices import normalize_language

GENERAL_TYPE = "general"

KNOWN_TYPES = tuple(DEFAULT_TYPE_PRESETS)


@dataclass(frozen=True)
class TypePreset:
    """Resolved narration/visual defaults for one content type."""

    voice: str = "zh-CN-YunjianNeural"
    tts_rate: str = "+0%"
    sentence_pause_seconds: float = 0.0
    sentence_gap_seconds: float = 0.0
    segment_pause_seconds: float = 0.0
    image_hold_seconds: float = 4.0
    orientation: str = "landscape"
    footage: str = "video_first"
    proofread: bool = False
    presenter_intro: bool = False


_PRESET_FIELDS = {field.name for field in fields(TypePreset)}

#: Sentinel so a request object that does not model ``presenter_name`` at all
#: (lightweight stand-ins) is treated as "no explicit choice".
_UNSET = object()


def normalize_type(content_type: str | None) -> str:
    return (content_type or "").strip().lower() or GENERAL_TYPE


def get_type_preset(content_type: str | None = None, settings_obj=None) -> TypePreset:
    """Resolve the preset for ``content_type`` (general defaults + overrides)."""
    source = settings_obj if settings_obj is not None else settings
    raw = getattr(source, "type_presets", None)
    presets = raw if isinstance(raw, dict) and raw else DEFAULT_TYPE_PRESETS

    general = {**DEFAULT_TYPE_PRESETS[GENERAL_TYPE]}
    general.update(
        {k: v for k, v in (presets.get(GENERAL_TYPE) or {}).items() if k in _PRESET_FIELDS}
    )

    key = normalize_type(content_type)
    specific = presets.get(key)
    if specific is None and key != GENERAL_TYPE:
        specific = DEFAULT_TYPE_PRESETS.get(key)
    merged = {**general, **{k: v for k, v in (specific or {}).items() if k in _PRESET_FIELDS}}
    return TypePreset(**{k: merged[k] for k in _PRESET_FIELDS if k in merged})


def resolve_presenter(request, settings_obj=None) -> str | None:
    """Resolve the active presenter name for ``request`` (``None`` = off).

    Off when the feature is disabled globally, disabled for the content type,
    explicitly switched off per request (empty string), or the narration
    language is not Chinese. An explicit non-empty ``presenter_name`` overrides
    the configured name; an absent/``None`` value falls back to settings.
    """
    source = settings_obj if settings_obj is not None else settings
    if not getattr(source, "presenter_enabled", True):
        return None
    if normalize_language(getattr(request, "language", None)) != "zh":
        return None

    preset = get_type_preset(getattr(request, "content_type", None), settings_obj)
    if not preset.presenter_intro:
        return None

    raw = getattr(request, "presenter_name", _UNSET)
    if raw is not _UNSET and raw is not None:
        name = str(raw).strip()
        if not name:
            return None
        return name

    name = str(getattr(source, "presenter_name", "") or "").strip()
    return name or None
