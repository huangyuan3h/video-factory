"""Tests for scheduler module."""

import pytest


def test_scheduler_module_import():
    """Test scheduler module can be imported."""
    from src import scheduler
    
    assert scheduler is not None