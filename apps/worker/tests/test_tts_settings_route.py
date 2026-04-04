"""Tests for TTS settings route."""

import pytest


def test_tts_settings_router():
    """Test TTS settings router exists."""
    from src.routes.tts_settings import router
    
    assert router is not None


def test_tts_settings_imports():
    """Test TTS settings imports."""
    from src.routes import tts_settings
    
    assert tts_settings is not None