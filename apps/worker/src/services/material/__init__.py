"""Material fetching services."""

from .local_assets_service import LocalAssetsService
from .material_fetcher import (
    BOOK_FALLBACK_KEYWORDS,
    MaterialFetcher,
    book_fallback_keywords,
    derive_book_search_terms,
    derive_search_terms,
    normalize_sources,
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
    "book_fallback_keywords",
    "BOOK_FALLBACK_KEYWORDS",
    "normalize_sources",
]
