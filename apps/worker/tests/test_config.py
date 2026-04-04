"""Tests for config module."""

import pytest


def test_settings_defaults():
    """Test default settings."""
    from src.config import Settings
    
    settings = Settings()
    
    assert settings.host == "0.0.0.0"
    assert settings.port == 8000


def test_settings_from_env():
    """Test settings can be created."""
    from src.config import Settings
    
    settings = Settings()
    assert hasattr(settings, 'host')
    assert hasattr(settings, 'port')


def test_settings_singleton():
    """Test settings singleton."""
    from src.config import settings
    
    assert settings is not None
    assert settings.host
    assert settings.port