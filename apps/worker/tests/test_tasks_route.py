"""Tests for tasks route."""

import pytest


def test_tasks_router():
    """Test tasks router exists."""
    from src.routes.tasks import router
    
    assert router is not None


def test_tasks_imports():
    """Test tasks imports."""
    from src.routes import tasks
    
    assert tasks is not None