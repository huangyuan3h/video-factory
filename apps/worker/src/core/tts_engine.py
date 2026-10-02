"""Compatibility shim — re-exports EdgeTTSProvider as EdgeTTSEngine.

New code should import from `core.tts` directly.
"""

from .tts.edge_provider import EdgeTTSProvider
from .tts.edge_provider import EdgeTTSProvider as EdgeTTSEngine

__all__ = ["EdgeTTSEngine", "EdgeTTSProvider"]
