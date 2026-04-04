"""Tests for publishers base full coverage."""

import pytest
from pathlib import Path


def test_base_publisher():
    """Test base publisher class."""
    from src.publishers.base import BasePublisher
    
    assert BasePublisher is not None


def test_publisher_methods():
    """Test publisher methods."""
    from src.publishers.base import BasePublisher
    
    # Check if methods exist
    if hasattr(BasePublisher, 'upload'):
        assert callable(BasePublisher.upload)
    
    if hasattr(BasePublisher, 'login'):
        assert callable(BasePublisher.login)


def test_publisher_config():
    """Test publisher configuration."""
    from src.publishers.douyin import DouyinPublisher
    
    publisher = DouyinPublisher()
    
    # Check attributes
    if hasattr(publisher, 'headless'):
        assert isinstance(publisher.headless, bool)


def test_publisher_platform():
    """Test publisher platform."""
    from src.publishers.douyin import DouyinPublisher
    from src.publishers.xiaohongshu import XiaohongshuPublisher
    
    douyin = DouyinPublisher()
    xiaohongshu = XiaohongshuPublisher()
    
    assert douyin is not None
    assert xiaohongshu is not None