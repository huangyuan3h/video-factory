"""Tests for main module."""

import pytest


def test_main_module_import():
    """Test main module can be imported."""
    from src import main
    
    assert main is not None


def test_app_creation():
    """Test FastAPI app can be created."""
    from src.main import app
    
    assert app is not None


def test_app_routes():
    """Test app has routes."""
    from src.main import app
    
    assert app.routes is not None
    assert len(app.routes) > 0