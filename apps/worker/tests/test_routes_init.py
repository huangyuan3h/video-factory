"""Tests for routes init."""

import pytest


def test_routes_import():
    """Test routes module import."""
    from src import routes
    
    assert routes is not None


def test_routes_videos():
    """Test videos route."""
    from src.routes.videos import router
    
    assert router is not None


def test_routes_ai_settings():
    """Test ai_settings route."""
    from src.routes.ai_settings import router
    
    assert router is not None


def test_routes_sources():
    """Test sources route."""
    from src.routes.sources import router
    
    assert router is not None


def test_routes_tasks():
    """Test tasks route."""
    from src.routes.tasks import router
    
    assert router is not None