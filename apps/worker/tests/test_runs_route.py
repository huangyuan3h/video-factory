"""Tests for runs route."""

import pytest


def test_runs_router():
    """Test runs router exists."""
    from src.routes.runs import router
    
    assert router is not None


def test_runs_imports():
    """Test runs imports."""
    from src.routes import runs
    
    assert runs is not None