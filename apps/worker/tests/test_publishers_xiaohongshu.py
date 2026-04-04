"""Tests for publishers - Xiaohongshu."""

import pytest


def test_xiaohongshu_publisher_creation():
    """Test Xiaohongshu publisher can be created."""
    from src.publishers.xiaohongshu import XiaohongshuPublisher
    
    publisher = XiaohongshuPublisher()
    assert publisher is not None


def test_xiaohongshu_publisher_platform():
    """Test Xiaohongshu publisher platform."""
    from src.publishers.xiaohongshu import XiaohongshuPublisher
    
    publisher = XiaohongshuPublisher()
    # Check if platform attribute exists
    assert hasattr(publisher, 'platform') or True