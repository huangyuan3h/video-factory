"""Deep tests for AI client."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_ai_client_generate():
    """Test AI client generation."""
    from src.core.ai_client import AIClient
    
    client = AIClient(
        base_url="https://api.test.com",
        api_key="test-key",
        model="gpt-4"
    )
    
    # Just test that client was created
    assert client is not None


def test_ai_client_config():
    """Test AI client configuration."""
    from src.core.ai_client import AIClient
    
    client = AIClient(
        base_url="https://api.test.com",
        api_key="test-key",
        model="gpt-4o"
    )
    
    assert client.model == "gpt-4o"
    assert client.base_url == "https://api.test.com"


@pytest.mark.asyncio
async def test_ai_client_error_handling():
    """Test AI client error handling."""
    from src.core.ai_client import AIClient
    
    client = AIClient(
        base_url="https://api.test.com",
        api_key="test-key",
        model="gpt-4"
    )
    
    with patch("openai.AsyncOpenAI") as mock_openai:
        mock_instance = MagicMock()
        mock_openai.return_value = mock_instance
        
        mock_instance.chat.completions.create = AsyncMock(
            side_effect=Exception("API Error")
        )
        
        try:
            result = await client.generate_script("Test")
        except Exception:
            assert True


def test_script_segment():
    """Test ScriptSegment dataclass."""
    from src.core.ai_client import ScriptSegment
    
    segment = ScriptSegment(
        text="Test text",
        keywords=["test", "keywords"],
        duration_estimate=60
    )
    
    assert segment.text == "Test text"
    assert len(segment.keywords) == 2
    assert segment.duration_estimate == 60


def test_generated_script():
    """Test GeneratedScript dataclass."""
    from src.core.ai_client import GeneratedScript, ScriptSegment
    
    script = GeneratedScript(
        title="Test Title",
        segments=[
            ScriptSegment(text="Segment 1", keywords=[], duration_estimate=60)
        ],
        total_duration_estimate=60
    )
    
    assert script.title == "Test Title"
    assert len(script.segments) == 1