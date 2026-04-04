"""Tests for TTS engine module."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_tts_engine_creation():
    """Test TTS engine can be created."""
    from src.core.tts_engine import EdgeTTSEngine
    
    engine = EdgeTTSEngine()
    assert engine is not None


@pytest.mark.asyncio
async def test_tts_engine_synthesize_mock():
    """Test TTS synthesize with mock."""
    from src.core.tts_engine import EdgeTTSEngine
    
    engine = EdgeTTSEngine()
    
    with patch("edge_tts.Communicate") as mock_communicate:
        mock_instance = MagicMock()
        mock_communicate.return_value = mock_instance
        mock_instance.save = AsyncMock()
        
        result = await engine.synthesize("测试文本", "zh-CN-XiaoxiaoNeural")
        assert result is not None