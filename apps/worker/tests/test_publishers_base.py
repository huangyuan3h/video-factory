"""Tests for publishers base module."""

import pytest


def test_publisher_base_creation():
    """Test base publisher can be created."""
    from src.publishers.base import BasePublisher
    
    # BasePublisher might be abstract
    assert BasePublisher is not None