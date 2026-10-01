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
from .card_qa import (
    assert_card_image_fits,
    check_card_image_no_overflow,
    shorten_card_fact,
)
from .script import found_numbers, generate_indicator_script, missing_numbers
from .repeat_guard import (
    assert_no_repeats,
    check_transcript_no_repeats,
    find_adjacent_bridge_repeats,
    find_global_repeats,
    find_repeats,
    strip_bridge_duplicates,
)
from .transition import (
    NEARDUP_JACCARD_THRESHOLD,
    REVIEW_MIN_SCORE,
    STOCK_FILLERS,
    assert_transitions_coherent,
    find_bridge_phrase_reuse,
    find_near_duplicate_boundaries,
    find_stock_filler_reuse,
    jaccard,
    polish_transitions,
    review_boundaries,
    run_transition_pass,
    tail_head_jaccard,
    transition_issues,
)
from .jargon import assert_no_jargon, check_segments as check_jargon_segments, find_jargon
from .visual_beats import (
    MAX_SINGLE_HOLD_SECONDS,
    assert_beat_sync,
    assert_visual_beats,
    beat_markers_in_order,
    check_beat_sync,
    check_visual_beats,
    compute_cue_based_holds,
    compute_holds_from_boundaries,
    count_group_beats,
)

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
    "assert_no_repeats",
    "check_transcript_no_repeats",
    "find_adjacent_bridge_repeats",
    "find_global_repeats",
    "find_repeats",
    "strip_bridge_duplicates",
    "assert_card_image_fits",
    "check_card_image_no_overflow",
    "shorten_card_fact",
    "NEARDUP_JACCARD_THRESHOLD",
    "REVIEW_MIN_SCORE",
    "STOCK_FILLERS",
    "assert_transitions_coherent",
    "find_bridge_phrase_reuse",
    "find_near_duplicate_boundaries",
    "find_stock_filler_reuse",
    "jaccard",
    "polish_transitions",
    "review_boundaries",
    "run_transition_pass",
    "tail_head_jaccard",
    "transition_issues",
    "assert_no_jargon",
    "check_jargon_segments",
    "find_jargon",
    "MAX_SINGLE_HOLD_SECONDS",
    "assert_beat_sync",
    "assert_visual_beats",
    "beat_markers_in_order",
    "check_beat_sync",
    "check_visual_beats",
    "compute_cue_based_holds",
    "compute_holds_from_boundaries",
    "count_group_beats",
]
