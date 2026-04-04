"""Additional tests for core init."""

import pytest


def test_core_imports():
    """Test core module imports."""
    from src.core import AIClient, EdgeTTSEngine, VideoGenerator
    
    assert AIClient is not None
    assert EdgeTTSEngine is not None
    assert VideoGenerator is not None


def test_core_ai_client_creation():
    """Test AI client creation."""
    from src.core.ai_client import AIClient
    
    client = AIClient(base_url="https://api.test.com", api_key="test", model="gpt-4")
    assert client is not None


def test_core_video_generator_creation():
    """Test video generator creation."""
    from src.core.video_generator import VideoGenerator
    from pathlib import Path
    
    gen = VideoGenerator(output_dir=Path("/tmp"))
    assert gen is not None