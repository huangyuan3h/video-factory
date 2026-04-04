"""Tests for general settings route."""

import pytest


def test_general_settings_router():
    """Test general settings router exists."""
    from src.routes.general_settings import router
    
    assert router is not None


def test_general_settings_imports():
    """Test general settings imports."""
    from src.routes import general_settings
    
    assert general_settings is not None