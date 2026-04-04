"""Tests for AI settings route."""

import pytest


def test_ai_settings_router():
    """Test AI settings router exists."""
    from src.routes.ai_settings import router
    
    assert router is not None


def test_ai_settings_imports():
    """Test AI settings imports."""
    from src.routes import ai_settings
    
    assert ai_settings is not None