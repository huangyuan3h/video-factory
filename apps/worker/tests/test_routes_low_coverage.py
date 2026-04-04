"""Additional tests for low coverage routes."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock


class TestRoutesLowCoverage:
    """Tests for low coverage routes."""

    def test_ai_settings_routes_structure(self):
        """Test AI settings routes structure."""
        from src.routes.ai_settings import router
        
        routes = [r.path for r in router.routes]
        assert "" in routes or "/" in routes

    def test_system_prompts_routes_structure(self):
        """Test system prompts routes structure."""
        from src.routes.system_prompts import router
        
        routes = [r.path for r in router.routes]
        assert len(routes) > 0

    def test_tasks_routes_structure(self):
        """Test tasks routes structure."""
        from src.routes.tasks import router
        
        routes = [r.path for r in router.routes]
        assert len(routes) > 0

    def test_sources_routes_structure(self):
        """Test sources routes structure."""
        from src.routes.sources import router
        
        routes = [r.path for r in router.routes]
        assert len(routes) > 0

    def test_runs_routes_structure(self):
        """Test runs routes structure."""
        from src.routes.runs import router
        
        routes = [r.path for r in router.routes]
        assert len(routes) > 0

    def test_tts_settings_routes_structure(self):
        """Test TTS settings routes structure."""
        from src.routes.tts_settings import router
        
        routes = [r.path for r in router.routes]
        assert len(routes) > 0

    def test_general_settings_routes_structure(self):
        """Test general settings routes structure."""
        from src.routes.general_settings import router
        
        routes = [r.path for r in router.routes]
        assert len(routes) > 0


class TestSchemasValidation:
    """Tests for schema validation."""

    def test_ai_setting_create_validation(self):
        """Test AISettingCreate validation."""
        from src.schemas import AISettingCreate
        
        data = AISettingCreate(
            name="Test",
            base_url="http://test",
            api_key="key",
            model_id="model"
        )
        assert data.name == "Test"

    def test_source_create_validation(self):
        """Test SourceCreate validation."""
        from src.schemas import SourceCreate
        
        data = SourceCreate(
            type="rss",
            name="Test Source",
            url="http://test.com/rss"
        )
        assert data.type == "rss"

    def test_system_prompt_create_validation(self):
        """Test SystemPromptCreate validation."""
        from src.schemas import SystemPromptCreate
        
        data = SystemPromptCreate(
            name="Test Prompt",
            content="Test content",
            is_default=False
        )
        assert data.name == "Test Prompt"

    def test_tts_setting_update_validation(self):
        """Test TTSSettingUpdate validation."""
        from src.schemas import TTSSettingUpdate
        
        data = TTSSettingUpdate(
            voice="zh-CN-XiaoxiaoNeural",
            rate="+10%"
        )
        assert data.voice == "zh-CN-XiaoxiaoNeural"

    def test_general_setting_update_validation(self):
        """Test GeneralSettingUpdate validation."""
        from src.schemas import GeneralSettingUpdate
        
        data = GeneralSettingUpdate(
            output_dir="/tmp/output",
            video_resolution_width=1920,
            video_resolution_height=1080
        )
        assert data.output_dir == "/tmp/output"


class TestModels:
    """Tests for database models."""

    def test_ai_setting_model(self):
        """Test AISetting model."""
        from src.models import AISetting
        
        assert hasattr(AISetting, '__tablename__')
        assert AISetting.__tablename__ == "ai_settings"

    def test_task_model(self):
        """Test Task model."""
        from src.models import Task
        
        assert hasattr(Task, '__tablename__')
        assert Task.__tablename__ == "tasks"

    def test_source_model(self):
        """Test Source model."""
        from src.models import Source
        
        assert hasattr(Source, '__tablename__')
        assert Source.__tablename__ == "sources"

    def test_run_model(self):
        """Test Run model."""
        from src.models import Run
        
        assert hasattr(Run, '__tablename__')
        assert Run.__tablename__ == "runs"

    def test_system_prompt_model(self):
        """Test SystemPrompt model."""
        from src.models import SystemPrompt
        
        assert hasattr(SystemPrompt, '__tablename__')
        assert SystemPrompt.__tablename__ == "system_prompts"

    def test_tts_setting_model(self):
        """Test TTSSetting model."""
        from src.models import TTSSetting
        
        assert hasattr(TTSSetting, '__tablename__')
        assert TTSSetting.__tablename__ == "tts_settings"

    def test_general_setting_model(self):
        """Test GeneralSetting model."""
        from src.models import GeneralSetting
        
        assert hasattr(GeneralSetting, '__tablename__')
        assert GeneralSetting.__tablename__ == "general_settings"


class TestConfig:
    """Tests for config module."""

    def test_settings_singleton(self):
        """Test settings singleton."""
        from src.config import settings
        
        assert settings is not None

    def test_settings_attributes(self):
        """Test settings attributes."""
        from src.config import settings
        
        assert hasattr(settings, 'database_url')
        assert hasattr(settings, 'debug')
        assert hasattr(settings, 'host')
        assert hasattr(settings, 'port')

    def test_settings_defaults(self):
        """Test settings defaults."""
        from src.config import settings
        
        assert settings.host == "0.0.0.0"
        assert settings.port == 8000