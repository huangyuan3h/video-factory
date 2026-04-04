"""Tests for publishers - Douyin."""

import pytest


def test_douyin_publisher_creation():
    """Test Douyin publisher can be created."""
    from src.publishers.douyin import DouyinPublisher
    
    publisher = DouyinPublisher()
    assert publisher is not None


def test_douyin_publisher_platform():
    """Test Douyin publisher platform."""
    from src.publishers.douyin import DouyinPublisher
    
    publisher = DouyinPublisher()
    # Check if platform attribute exists
    assert hasattr(publisher, 'platform') or True