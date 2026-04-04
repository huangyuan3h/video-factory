"""Tests for publisher deep coverage."""

import pytest
from pathlib import Path


def test_publisher_init():
    """Test publisher initialization."""
    from src.publishers.douyin import DouyinPublisher
    from src.publishers.xiaohongshu import XiaohongshuPublisher
    
    douyin = DouyinPublisher()
    xiaohongshu = XiaohongshuPublisher()
    
    assert douyin is not None
    assert xiaohongshu is not None


def test_publisher_platforms():
    """Test publisher platforms."""
    from src.publishers.douyin import DouyinPublisher
    from src.publishers.xiaohongshu import XiaohongshuPublisher
    
    douyin = DouyinPublisher()
    xiaohongshu = XiaohongshuPublisher()
    
    if hasattr(douyin, 'platform'):
        assert douyin.platform == 'douyin'
    if hasattr(xiaohongshu, 'platform'):
        assert xiaohongshu.platform == 'xiaohongshu'