"""Plugin-style registry for series / content types (Phase 4).

Adding a new series (e.g. a book, news, or future novel series) must NOT require
touching core code. Instead:

1. Describe it with a :class:`SeriesSpec` (or a JSON file under ``config/series.d/``,
   see :func:`load_series_configs` and ``config/series.d/README.md``).
2. Register it via :func:`register_series` (or the :func:`series` decorator).
3. Optionally attach a ``builder`` — a callable ``(args) -> (request, name)`` that
   builds a pipeline request, like ``build_indicator_request`` /
   ``build_generic_request`` in ``cli_runner.py``. When a builder is registered,
   ``vf new-ep --type <name>`` discovers it with zero core changes.
4. Add a QA gate script (see ``scripts/indicator_qa.py``) and wire ``vf qa``.

Named pipeline steps (every series moves through the same named steps; runners
may execute a subset by name, e.g. script-only stops after ``review``):

    research -> script -> review -> tts -> materials -> render -> qa -> publish
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Canonical named pipeline steps. Subsets are valid (e.g. script-only runs
# research/script/review and stops; publish-only runs qa/publish).
PIPELINE_STEPS: tuple[str, ...] = (
    "research",
    "script",
    "review",
    "tts",
    "materials",
    "render",
    "qa",
    "publish",
)

# Where declarative series configs live (JSON files, optional).
# __file__ = <root>/apps/worker/src/services/series_registry.py -> parents[4] is <root>.
SERIES_CONFIG_DIR = Path(__file__).resolve().parents[4] / "config" / "series.d"

BuilderFn = Callable[[object], tuple[object, str]]


@dataclass(frozen=True)
class SeriesSpec:
    """One registered series / content type."""

    name: str
    content_type: str
    description: str = ""
    steps: tuple[str, ...] = PIPELINE_STEPS
    script_only_supported: bool = True
    # Optional request builder (args -> (request, name)). Pure w.r.t. network:
    # must only BUILD the request, never run TTS/render/upload.
    builder: BuilderFn | None = field(default=None, compare=False)


_SERIES_REGISTRY: dict[str, SeriesSpec] = {}


def register_series(spec: SeriesSpec) -> SeriesSpec:
    """Register (or replace) a series spec. Returns the spec.

    Raises ValueError on unknown step names so typos fail fast.
    """
    key = spec.name.strip().lower()
    if not key:
        raise ValueError("series name must not be empty")
    unknown = [s for s in spec.steps if s not in PIPELINE_STEPS]
    if unknown:
        raise ValueError(f"series {key!r} has unknown steps {unknown} (want subset of {list(PIPELINE_STEPS)})")
    norm = SeriesSpec(
        name=key,
        content_type=spec.content_type.strip().lower() or key,
        description=spec.description,
        steps=tuple(spec.steps),
        script_only_supported=bool(spec.script_only_supported),
        builder=spec.builder,
    )
    _SERIES_REGISTRY[key] = norm
    return norm


def series(name: str, **kwargs: Any) -> Callable[[BuilderFn], BuilderFn]:
    """Decorator registering a builder under a series name.

    Example::

        @series("novel", content_type="novel", description="Future novel series")
        def build_novel_request(args):
            ...
            return request, name
    """

    def deco(fn: BuilderFn) -> BuilderFn:
        register_series(SeriesSpec(name=name, content_type=kwargs.get("content_type", name), description=kwargs.get("description", ""), steps=kwargs.get("steps", PIPELINE_STEPS), builder=fn))
        return fn

    return deco


def get_series(name: str | None) -> SeriesSpec:
    """Fetch a spec by name (case-insensitive). Raises KeyError with a hint."""
    key = (name or "").strip().lower()
    try:
        return _SERIES_REGISTRY[key]
    except KeyError:
        raise KeyError(f"unknown series/type {name!r}. Available: {list_series()} (see `vf new-ep --list-types`)") from None


def list_series() -> list[str]:
    """Sorted registered series names."""
    return sorted(_SERIES_REGISTRY.keys())


def steps_for(name: str | None) -> list[str]:
    """Named pipeline steps for a series (defaults to the full pipeline)."""
    if not name:
        return list(PIPELINE_STEPS)
    return list(get_series(name).steps)


def load_series_configs(config_dir: str | Path | None = None) -> int:
    """Load ``*.json`` series declarations from a directory. Returns count loaded.

    File format::

        {"name": "novel", "content_type": "novel",
         "description": "Future novel series", "steps": ["research", "script", "review"]}

    Invalid files raise ValueError naming the file (fail fast, never half-load).
    Missing directory loads zero (no error — configs are optional).
    """
    directory = Path(config_dir) if config_dir else SERIES_CONFIG_DIR
    if not directory.is_dir():
        return 0
    loaded = 0
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"invalid series config {path}: {exc}") from exc
        if not isinstance(data, dict) or not data.get("name"):
            raise ValueError(f"invalid series config {path}: need object with 'name'")
        steps = data.get("steps", list(PIPELINE_STEPS))
        register_series(
            SeriesSpec(
                name=str(data["name"]),
                content_type=str(data.get("content_type", data["name"])),
                description=str(data.get("description", "")),
                steps=tuple(steps),
            )
        )
        loaded += 1
    return loaded


def _register_builtins() -> None:
    for name, content_type, description in (
        ("indicator", "indicator", "什么指标不赚钱 chart-episode series (default)"),
        ("general", "general", "Generic narration episode"),
        ("book", "book", "Book-reading episode"),
        ("news", "news", "News episode (news_service pipeline)"),
        ("daily_news", "daily_news", "Daily-news MVP (S0-S8, type=daily_news)"),
    ):
        if name not in _SERIES_REGISTRY:
            register_series(SeriesSpec(name=name, content_type=content_type, description=description))


_register_builtins()
