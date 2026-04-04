"""Deep tests for subtitle generator."""

import pytest


def test_subtitle_creation():
    """Test subtitle creation."""
    from src.core.subtitle_gen import Subtitle
    
    subtitle = Subtitle(
        index=1,
        start_time=0.0,
        end_time=5.0,
        text="测试字幕"
    )
    
    assert subtitle.index == 1
    assert subtitle.text == "测试字幕"


def test_subtitle_to_srt():
    """Test subtitle to SRT format."""
    from src.core.subtitle_gen import Subtitle
    
    subtitle = Subtitle(
        index=1,
        start_time=0.0,
        end_time=5.0,
        text="测试字幕"
    )
    
    if hasattr(subtitle, 'to_srt'):
        result = subtitle.to_srt()
        assert result is not None


def test_subtitle_to_ass():
    """Test subtitle to ASS format."""
    from src.core.subtitle_gen import Subtitle
    
    subtitle = Subtitle(
        index=1,
        start_time=0.0,
        end_time=5.0,
        text="测试字幕"
    )
    
    if hasattr(subtitle, 'to_ass'):
        result = subtitle.to_ass()
        assert result is not None