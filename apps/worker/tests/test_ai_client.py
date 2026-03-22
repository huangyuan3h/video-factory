"""Tests for AI client."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.ai_client import AIClient, GeneratedScript, ScriptSegment


class TestScriptSegment:
    """Tests for ScriptSegment model."""

    def test_create_script_segment(self):
        """Test creating a script segment."""
        segment = ScriptSegment(
            text="这是测试文本",
            keywords=["测试", "文本"],
            duration_estimate=60,
        )
        assert segment.text == "这是测试文本"
        assert segment.keywords == ["测试", "文本"]
        assert segment.duration_estimate == 60


class TestGeneratedScript:
    """Tests for GeneratedScript model."""

    def test_create_generated_script(self):
        """Test creating a generated script."""
        segments = [
            ScriptSegment(text="第一段", keywords=["a"], duration_estimate=30),
            ScriptSegment(text="第二段", keywords=["b"], duration_estimate=60),
        ]
        script = GeneratedScript(
            title="测试标题",
            segments=segments,
            total_duration_estimate=90,
        )
        assert script.title == "测试标题"
        assert len(script.segments) == 2
        assert script.total_duration_estimate == 90


class TestAIClient:
    """Tests for AIClient."""

    def test_init_with_defaults(self):
        """Test client initialization with default values."""
        with patch("src.core.ai_client.settings") as mock_settings:
            mock_settings.openai_base_url = None
            mock_settings.openai_api_key = "test-key-from-settings"
            mock_settings.openai_model = "gpt-4o"
            
            client = AIClient()
            assert client.api_key == "test-key-from-settings"

    def test_init_with_custom_values(self):
        """Test client initialization with custom values."""
        client = AIClient(
            base_url="https://custom.api.com/v1",
            api_key="custom-key",
            model="gpt-4",
        )
        assert client.base_url == "https://custom.api.com/v1"
        assert client.api_key == "custom-key"
        assert client.model == "gpt-4"

    @pytest.mark.asyncio
    async def test_generate_script_success(self):
        """Test successful script generation."""
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = json.dumps({
            "title": "AI的未来",
            "segments": [
                {
                    "text": "人工智能正在改变世界",
                    "keywords": ["AI", "科技"],
                    "duration_estimate": 45,
                },
                {
                    "text": "机器学习是核心驱动力",
                    "keywords": ["机器学习", "核心"],
                    "duration_estimate": 60,
                },
            ],
            "total_duration_estimate": 105,
        })
        mock_response.choices = [mock_choice]

        with patch("src.core.ai_client.AsyncOpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_openai.return_value = mock_client

            client = AIClient(api_key="test-key")
            result = await client.generate_script(
                content="人工智能的发展历程",
                title="AI的未来",
            )

        assert isinstance(result, GeneratedScript)
        assert result.title == "AI的未来"
        assert len(result.segments) == 2
        assert result.segments[0].text == "人工智能正在改变世界"
        assert result.segments[0].keywords == ["AI", "科技"]
        assert result.total_duration_estimate == 105

    @pytest.mark.asyncio
    async def test_generate_script_with_custom_prompt(self):
        """Test script generation with custom system prompt."""
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = json.dumps({
            "title": "自定义标题",
            "segments": [
                {
                    "text": "自定义内容",
                    "keywords": ["自定义"],
                    "duration_estimate": 30,
                },
            ],
            "total_duration_estimate": 30,
        })
        mock_response.choices = [mock_choice]

        with patch("src.core.ai_client.AsyncOpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_openai.return_value = mock_client

            client = AIClient(api_key="test-key")
            result = await client.generate_script(
                content="测试内容",
                title="测试标题",
                system_prompt="你是一个专业的视频脚本撰写专家",
            )

        assert result.title == "自定义标题"
        assert len(result.segments) == 1

    @pytest.mark.asyncio
    async def test_generate_script_empty_response(self):
        """Test handling empty API response."""
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = None
        mock_response.choices = [mock_choice]

        with patch("src.core.ai_client.AsyncOpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_openai.return_value = mock_client

            client = AIClient(api_key="test-key")
            result = await client.generate_script(
                content="测试内容",
                title="测试标题",
            )

        assert result.title == "测试标题"
        assert result.segments == []

    @pytest.mark.asyncio
    async def test_generate_script_api_error(self):
        """Test handling API error."""
        with patch("src.core.ai_client.AsyncOpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                side_effect=Exception("API Error")
            )
            mock_openai.return_value = mock_client

            client = AIClient(api_key="test-key")
            
            with pytest.raises(Exception, match="API Error"):
                await client.generate_script(
                    content="测试内容",
                    title="测试标题",
                )


class TestSummarize:
    """Tests for summarize method."""

    @pytest.mark.asyncio
    async def test_summarize_success(self):
        """Test successful summarization."""
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "这是一个简短的摘要。"
        mock_response.choices = [mock_choice]

        with patch("src.core.ai_client.AsyncOpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_openai.return_value = mock_client

            client = AIClient(api_key="test-key")
            result = await client.summarize("这是一段很长的文本内容...")

        assert result == "这是一个简短的摘要。"


class TestExtractKeywords:
    """Tests for extract_keywords method."""

    @pytest.mark.asyncio
    async def test_extract_keywords_success(self):
        """Test successful keyword extraction."""
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = json.dumps({
            "keywords": ["人工智能", "机器学习", "深度学习"]
        })
        mock_response.choices = [mock_choice]

        with patch("src.core.ai_client.AsyncOpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_openai.return_value = mock_client

            client = AIClient(api_key="test-key")
            result = await client.extract_keywords("人工智能和机器学习的内容")

        assert result == ["人工智能", "机器学习", "深度学习"]

    @pytest.mark.asyncio
    async def test_extract_keywords_error_returns_empty(self):
        """Test that keyword extraction returns empty list on error."""
        with patch("src.core.ai_client.AsyncOpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                side_effect=Exception("Network error")
            )
            mock_openai.return_value = mock_client

            client = AIClient(api_key="test-key")
            result = await client.extract_keywords("测试内容")

        assert result == []