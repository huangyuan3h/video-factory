"""Daily news MVP pipeline (P0): Karios snapshot -> topic -> script -> factcheck.

P0 scope: one finance episode from the Karios morning brief, Pexels video-led
materials (Tier-1 safe sources only) + one Karios data card, Yunjian narration,
fullframe white layout, unlisted upload. See docs/daily-news-video-design.md P0.
"""

from .data_card import render_data_card
from .factcheck import factcheck_script
from .materials import fetch_pexels_videos_with_attribution, score_relevance
from .pipeline import run_mvp
from .script_builder import build_script
from .snapshot import fetch_karios_snapshot, load_snapshot
from .topic import pick_finance_topic

__all__ = [
    "fetch_karios_snapshot",
    "load_snapshot",
    "pick_finance_topic",
    "build_script",
    "factcheck_script",
    "render_data_card",
    "fetch_pexels_videos_with_attribution",
    "score_relevance",
    "run_mvp",
]
