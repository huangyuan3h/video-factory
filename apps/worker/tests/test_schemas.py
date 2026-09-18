"""Tests for schemas module."""

import pytest


def test_source_response_schema():
    """Test SourceResponse schema."""
    from src.schemas import SourceResponse
    
    assert SourceResponse is not None


def test_source_response_parses_json_keywords():
    """DB stores keywords as a JSON string; response must expose a list."""
    from datetime import datetime

    from src.schemas import SourceResponse

    now = datetime.now()
    model = SourceResponse.model_validate(
        {
            "id": "s1",
            "type": "rss",
            "name": "feed",
            "keywords": '["ai", "news"]',
            "enabled": True,
            "created_at": now,
            "updated_at": now,
        }
    )
    assert model.keywords == ["ai", "news"]
    # plain comma string also tolerated
    model2 = SourceResponse.model_validate(
        {
            "id": "s2",
            "type": "rss",
            "name": "feed",
            "keywords": "a, b",
            "enabled": True,
            "created_at": now,
            "updated_at": now,
        }
    )
    assert model2.keywords == ["a", "b"]


def test_task_response_schema():
    """Test TaskResponse schema."""
    from src.schemas import TaskResponse
    
    assert TaskResponse is not None


def test_run_response_schema():
    """Test RunResponse schema."""
    from src.schemas import RunResponse
    
    assert RunResponse is not None


def test_ai_setting_response_schema():
    """Test AISettingResponse schema."""
    from src.schemas import AISettingResponse
    
    assert AISettingResponse is not None


def test_publisher_account_response_schema():
    """Test PublisherAccountResponse schema."""
    from src.schemas import PublisherAccountResponse
    
    assert PublisherAccountResponse is not None


def test_tts_setting_response_schema():
    """Test TTSSettingResponse schema."""
    from src.schemas import TTSSettingResponse
    
    assert TTSSettingResponse is not None


def test_general_setting_response_schema():
    """Test GeneralSettingResponse schema."""
    from src.schemas import GeneralSettingResponse
    
    assert GeneralSettingResponse is not None


def test_system_prompt_response_schema():
    """Test SystemPromptResponse schema."""
    from src.schemas import SystemPromptResponse
    
    assert SystemPromptResponse is not None