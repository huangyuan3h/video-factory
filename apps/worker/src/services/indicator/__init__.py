"""Manifest-driven chart episodes (``type=indicator``).

Two pieces, kept separate so they are easy to test:

* :mod:`src.services.indicator.manifest` — loads/tolerates the research
  pipeline's ``manifest.json`` into an ordered :class:`IndicatorManifest`.
* :mod:`src.services.indicator.script` — turns that manifest into a
  :class:`~src.core.ai_client.GeneratedScript` with one chart-bound segment per
  manifest item.
"""

from .manifest import (
    KNOWN_SECTIONS,
    SECTION_SEQUENCE,
    IndicatorManifest,
    ManifestItem,
    load_manifest,
    required_numbers,
)
from .script import found_numbers, generate_indicator_script, missing_numbers

__all__ = [
    "IndicatorManifest",
    "ManifestItem",
    "load_manifest",
    "required_numbers",
    "generate_indicator_script",
    "found_numbers",
    "missing_numbers",
    "KNOWN_SECTIONS",
    "SECTION_SEQUENCE",
]
