"""Tests for scheduler module."""

import pytest


def test_scheduler_module():
    """Test scheduler module."""
    from src import scheduler
    
    assert scheduler is not None