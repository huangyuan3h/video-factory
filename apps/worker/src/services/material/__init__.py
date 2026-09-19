"""Material fetching services."""

from .local_assets_service import LocalAssetsService
from .material_fetcher import (
    BOOK_AVOID_ALT_TERMS,
    BOOK_FALLBACK_KEYWORDS,
    BOOK_VISUAL_REPLACEMENTS,
    MaterialFetcher,
    book_fallback_keywords,
    build_book_segment_query,
    chapter_anchor_terms,
    derive_book_search_terms,
    derive_search_terms,
    normalize_sources,
    to_visual_search_terms,
)
from .pexels_service import PexelsService
from .pixabay_service import PixabayService

__all__ = [
    "PexelsService",
    "PixabayService",
    "LocalAssetsService",
    "MaterialFetcher",
    "derive_search_terms",
    "derive_book_search_terms",
    "build_book_segment_query",
    "chapter_anchor_terms",
    "book_fallback_keywords",
    "to_visual_search_terms",
    "BOOK_FALLBACK_KEYWORDS",
    "BOOK_VISUAL_REPLACEMENTS",
    "BOOK_AVOID_ALT_TERMS",
    "normalize_sources",
]
