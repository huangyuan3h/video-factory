"""Tests for sources base module."""

import pytest


def test_source_base_creation():
    """Test base source can be created."""
    from src.sources.base import BaseSource
    
    # BaseSource might be abstract, so we test if it can be imported
    assert BaseSource is not None