"""Tests for sources route."""

import pytest


def test_sources_router():
    """Test sources router exists."""
    from src.routes.sources import router
    
    assert router is not None


def test_sources_imports():
    """Test sources imports."""
    from src.routes import sources
    
    assert sources is not None