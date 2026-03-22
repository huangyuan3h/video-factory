"""Shared test fixtures."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def mock_openai_response():
    """Mock OpenAI API response for script generation."""
    mock_choice = MagicMock()
    mock_choice.message.content = '''{
        "title": "测试视频标题",
        "segments": [
            {
                "text": "这是第一段内容，讲述了视频的主要观点。",
                "keywords": ["科技", "创新"],
                "duration_estimate": 45
            },
            {
                "text": "第二段内容深入探讨了相关细节。",
                "keywords": ["细节", "深入"],
                "duration_estimate": 60
            },
            {
                "text": "最后一段总结全文核心观点。",
                "keywords": ["总结", "核心"],
                "duration_estimate": 30
            }
        ],
        "total_duration_estimate": 135
    }'''
    
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


@pytest.fixture
def mock_tts_engine():
    """Mock TTS engine."""
    engine = MagicMock()
    engine.synthesize = AsyncMock(return_value=Path("/tmp/test_audio.mp3"))
    engine.get_duration = AsyncMock(return_value=10.5)
    return engine


@pytest.fixture
def mock_material_fetcher():
    """Mock material fetcher."""
    fetcher = MagicMock()
    fetcher.fetch_videos = AsyncMock(return_value=[])
    fetcher.fetch_images = AsyncMock(return_value=[
        Path("/tmp/image1.jpg"),
        Path("/tmp/image2.jpg"),
    ])
    return fetcher


@pytest.fixture
def mock_subtitle_gen():
    """Mock subtitle generator."""
    from src.core.subtitle_gen import Subtitle
    
    gen = MagicMock()
    gen.generate = AsyncMock(return_value=[
        Subtitle(index=1, start_time=0.0, end_time=5.0, text="测试字幕"),
    ])
    gen.save_ass = AsyncMock(return_value=Path("/tmp/subtitles.ass"))
    return gen


@pytest.fixture
def mock_ai_client(mock_openai_response):
    """Mock AI client."""
    from src.core.ai_client import GeneratedScript, ScriptSegment
    
    client = MagicMock()
    client.generate_script = AsyncMock(return_value=GeneratedScript(
        title="测试视频",
        segments=[
            ScriptSegment(text="第一段内容", keywords=["关键词1"], duration_estimate=60),
            ScriptSegment(text="第二段内容", keywords=["关键词2"], duration_estimate=60),
        ],
        total_duration_estimate=120,
    ))
    return client


@pytest_asyncio.fixture
async def video_generator_with_mocks(mock_ai_client, mock_tts_engine, mock_material_fetcher, mock_subtitle_gen):
    """Video generator with all dependencies mocked."""
    from src.core.video_generator import VideoGenerator
    
    generator = VideoGenerator(
        ai_client=mock_ai_client,
        tts_engine=mock_tts_engine,
        material_fetcher=mock_material_fetcher,
        subtitle_gen=mock_subtitle_gen,
        output_dir=Path("/tmp"),
    )
    return generator