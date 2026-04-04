"""Tests for models module."""

import pytest


def test_ai_setting_model():
    """Test AISetting model."""
    from src.models import AISetting
    
    assert AISetting is not None


def test_source_model():
    """Test Source model."""
    from src.models import Source
    
    assert Source is not None


def test_task_model():
    """Test Task model."""
    from src.models import Task
    
    assert Task is not None


def test_run_model():
    """Test Run model."""
    from src.models import Run
    
    assert Run is not None


def test_publisher_account_model():
    """Test PublisherAccount model."""
    from src.models import PublisherAccount
    
    assert PublisherAccount is not None


def test_tts_setting_model():
    """Test TTSSetting model."""
    from src.models import TTSSetting
    
    assert TTSSetting is not None


def test_general_setting_model():
    """Test GeneralSetting model."""
    from src.models import GeneralSetting
    
    assert GeneralSetting is not None


def test_system_prompt_model():
    """Test SystemPrompt model."""
    from src.models import SystemPrompt
    
    assert SystemPrompt is not None