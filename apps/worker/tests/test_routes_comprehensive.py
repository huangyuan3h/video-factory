"""More comprehensive tests for routes."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock


class TestRoutesComprehensive:
    """Comprehensive tests for all routes."""

    def test_ai_settings_list_route_exists(self):
        """Test AI settings list route exists."""
        from src.routes.ai_settings import router
        
        routes = [r.path for r in router.routes]
        assert "" in routes or "/" in routes

    def test_ai_settings_create_route_exists(self):
        """Test AI settings create route exists."""
        from src.routes.ai_settings import router
        
        methods = [r.methods for r in router.routes]
        assert any("POST" in m for m in methods)

    def test_ai_settings_update_route_exists(self):
        """Test AI settings update route exists."""
        from src.routes.ai_settings import router
        
        routes = [r.path for r in router.routes]
        assert any("/{setting_id}" in r for r in routes)

    def test_ai_settings_activate_route_exists(self):
        """Test AI settings activate route exists."""
        from src.routes.ai_settings import router
        
        routes = [r.path for r in router.routes]
        assert any("/activate" in r for r in routes)

    def test_ai_settings_test_route_exists(self):
        """Test AI settings test route exists."""
        from src.routes.ai_settings import router
        
        routes = [r.path for r in router.routes]
        assert any("/test" in r for r in routes)

    def test_ai_settings_delete_route_exists(self):
        """Test AI settings delete route exists."""
        from src.routes.ai_settings import router
        
        methods = [r.methods for r in router.routes]
        assert any("DELETE" in m for m in methods)

    def test_system_prompts_routes_exist(self):
        """Test system prompts routes exist."""
        from src.routes.system_prompts import router
        
        routes = [r.path for r in router.routes]
        assert len(routes) > 0

    def test_sources_routes_exist(self):
        """Test sources routes exist."""
        from src.routes.sources import router
        
        routes = [r.path for r in router.routes]
        assert len(routes) > 0

    def test_tasks_routes_exist(self):
        """Test tasks routes exist."""
        from src.routes.tasks import router
        
        routes = [r.path for r in router.routes]
        assert len(routes) > 0

    def test_runs_routes_exist(self):
        """Test runs routes exist."""
        from src.routes.runs import router
        
        routes = [r.path for r in router.routes]
        assert len(routes) > 0

    def test_tts_settings_routes_exist(self):
        """Test TTS settings routes exist."""
        from src.routes.tts_settings import router
        
        routes = [r.path for r in router.routes]
        assert len(routes) > 0

    def test_general_settings_routes_exist(self):
        """Test general settings routes exist."""
        from src.routes.general_settings import router
        
        routes = [r.path for r in router.routes]
        assert len(routes) > 0


class TestRoutesModels:
    """Tests for route models."""

    def test_ai_setting_create_model(self):
        """Test AISettingCreate model."""
        from src.schemas import AISettingCreate
        
        data = AISettingCreate(
            name="Test",
            base_url="http://test",
            api_key="key",
            model_id="model"
        )
        assert data.name == "Test"

    def test_ai_setting_update_model(self):
        """Test AISettingUpdate model."""
        from src.schemas import AISettingUpdate
        
        data = AISettingUpdate(name="Updated")
        assert data.name == "Updated"

    def test_system_prompt_create_model(self):
        """Test SystemPromptCreate model."""
        from src.schemas import SystemPromptCreate
        
        data = SystemPromptCreate(name="Test", content="Content")
        assert data.name == "Test"

    def test_system_prompt_update_model(self):
        """Test SystemPromptUpdate model."""
        from src.schemas import SystemPromptUpdate
        
        data = SystemPromptUpdate(name="Updated")
        assert data.name == "Updated"

    def test_source_create_model(self):
        """Test SourceCreate model."""
        from src.schemas import SourceCreate
        
        data = SourceCreate(type="rss", name="Test", url="http://test")
        assert data.type == "rss"

    def test_source_update_model(self):
        """Test SourceUpdate model."""
        from src.schemas import SourceUpdate
        
        data = SourceUpdate(name="Updated")
        assert data.name == "Updated"

    def test_task_create_model(self):
        """Test TaskCreate model."""
        from src.schemas import TaskCreate
        
        data = TaskCreate(name="Test Task", source_id="test-source", schedule="0 * * * *")
        assert data.name == "Test Task"
        assert data.source_id == "test-source"

    def test_task_update_model(self):
        """Test TaskUpdate model."""
        from src.schemas import TaskUpdate
        
        data = TaskUpdate(name="Updated")
        assert data.name == "Updated"

    def test_tts_setting_update_model(self):
        """Test TTSSettingUpdate model."""
        from src.schemas import TTSSettingUpdate
        
        data = TTSSettingUpdate(voice="zh-CN-XiaoxiaoNeural")
        assert data.voice == "zh-CN-XiaoxiaoNeural"

    def test_general_setting_update_model(self):
        """Test GeneralSettingUpdate model."""
        from src.schemas import GeneralSettingUpdate
        
        data = GeneralSettingUpdate(output_dir="/tmp")
        assert data.output_dir == "/tmp"


class TestApiResponse:
    """Tests for ApiResponse model."""

    def test_api_response_success(self):
        """Test ApiResponse success."""
        from src.schemas import ApiResponse
        
        response = ApiResponse(success=True, data={"test": "value"})
        assert response.success is True
        assert response.data == {"test": "value"}

    def test_api_response_failure(self):
        """Test ApiResponse failure."""
        from src.schemas import ApiResponse
        
        response = ApiResponse(success=False, error="Test error")
        assert response.success is False
        assert response.error == "Test error"


class TestPaginatedResponse:
    """Tests for PaginatedResponse model."""

    def test_paginated_response(self):
        """Test PaginatedResponse."""
        from src.schemas import PaginatedResponse
        
        response = PaginatedResponse(
            items=[{"id": 1}, {"id": 2}],
            total=10,
            page=1,
            page_size=2
        )
        assert len(response.items) == 2
        assert response.total == 10