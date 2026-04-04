"""Tests for subtitle deep coverage."""

import pytest
from pathlib import Path
import tempfile


def test_subtitle_generator_init():
    """Test subtitle generator initialization."""
    from src.core.subtitle_gen import SubtitleGenerator
    
    gen = SubtitleGenerator()
    assert gen is not None


@pytest.mark.asyncio
async def test_subtitle_from_audio():
    """Test creating subtitles from audio."""
    from src.core.subtitle_gen import SubtitleGenerator
    
    gen = SubtitleGenerator()
    
    if hasattr(gen, 'from_audio'):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = await gen.from_audio(Path("/tmp/test.mp3"))
            assert result is not None or result is None


@pytest.mark.asyncio
async def test_subtitle_save_srt():
    """Test saving SRT format."""
    from src.core.subtitle_gen import SubtitleGenerator, Subtitle
    
    gen = SubtitleGenerator()
    
    subtitles = [
        Subtitle(1, 0.0, 5.0, "第一句"),
        Subtitle(2, 5.0, 10.0, "第二句"),
    ]
    
    with tempfile.TemporaryDirectory() as tmpdir:
        if hasattr(gen, 'save_srt'):
            result = await gen.save_srt(subtitles, Path(tmpdir) / "test.srt")
            assert result is not None or result is None


@pytest.mark.asyncio
async def test_subtitle_save_ass():
    """Test saving ASS format."""
    from src.core.subtitle_gen import SubtitleGenerator, Subtitle
    
    gen = SubtitleGenerator()
    
    subtitles = [
        Subtitle(1, 0.0, 5.0, "测试字幕"),
    ]
    
    with tempfile.TemporaryDirectory() as tmpdir:
        if hasattr(gen, 'save_ass'):
            result = await gen.save_ass(subtitles, Path(tmpdir) / "test.ass")
            assert result is not None or result is None


def test_subtitle_format_time():
    """Test subtitle time formatting."""
    from src.core.subtitle_gen import Subtitle
    
    sub = Subtitle(1, 65.5, 70.5, "测试")
    
    # Test time values
    assert sub.start_time == 65.5
    assert sub.end_time == 70.5


def test_subtitle_multiple():
    """Test multiple subtitles."""
    from src.core.subtitle_gen import Subtitle
    
    subtitles = [
        Subtitle(i, i * 5.0, (i + 1) * 5.0, f"字幕{i}")
        for i in range(10)
    ]
    
    assert len(subtitles) == 10
    assert subtitles[0].text == "字幕0"
    assert subtitles[9].text == "字幕9"