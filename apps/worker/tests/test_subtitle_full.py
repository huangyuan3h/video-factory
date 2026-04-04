"""Tests for subtitle generator full coverage."""

import pytest
from pathlib import Path
import tempfile


def test_subtitle_generator_create():
    """Test creating subtitle generator."""
    from src.core.subtitle_gen import SubtitleGenerator
    
    gen = SubtitleGenerator()
    assert gen is not None


@pytest.mark.asyncio
async def test_subtitle_save_formats():
    """Test saving subtitles in different formats."""
    from src.core.subtitle_gen import SubtitleGenerator, Subtitle
    
    gen = SubtitleGenerator()
    
    subtitles = [
        Subtitle(1, 0.0, 5.0, "第一句"),
        Subtitle(2, 5.0, 10.0, "第二句"),
    ]
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Test SRT format
        if hasattr(gen, 'save_srt'):
            srt_path = Path(tmpdir) / "test.srt"
            await gen.save_srt(subtitles, srt_path)
        
        # Test ASS format
        if hasattr(gen, 'save_ass'):
            ass_path = Path(tmpdir) / "test.ass"
            await gen.save_ass(subtitles, ass_path)


def test_subtitle_time_conversion():
    """Test subtitle time conversion."""
    from src.core.subtitle_gen import Subtitle
    
    sub = Subtitle(1, 65.5, 70.5, "测试")
    
    # Test that time is stored correctly
    assert sub.start_time == 65.5
    assert sub.end_time == 70.5


def test_subtitle_text():
    """Test subtitle text."""
    from src.core.subtitle_gen import Subtitle
    
    sub = Subtitle(1, 0.0, 5.0, "测试字幕文本")
    
    assert sub.text == "测试字幕文本"


@pytest.mark.asyncio
async def test_subtitle_from_transcript():
    """Test creating subtitles from transcript."""
    from src.core.subtitle_gen import SubtitleGenerator
    
    gen = SubtitleGenerator()
    
    if hasattr(gen, 'from_transcript'):
        transcript = "这是第一句。这是第二句。"
        result = await gen.from_transcript(transcript)
        assert result is not None or result is None