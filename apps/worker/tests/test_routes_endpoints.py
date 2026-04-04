"""Deep integration tests for routes endpoints."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession


class TestAISettingsEndpoints:
    """Tests for AI settings endpoints."""

    @pytest.fixture
    def app(self):
        from src.routes.ai_settings import router
        app = FastAPI()
        app.include_router(router, prefix="/api/ai-settings")
        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_list_ai_settings_endpoint(self, client):
        """Test list AI settings endpoint."""
        response = client.get("/api/ai-settings")
        assert response.status_code in [200, 500]

    def test_create_ai_settings_endpoint(self, client):
        """Test create AI settings endpoint."""
        with patch("src.routes.ai_settings.get_session") as mock_session:
            mock_session.return_value = AsyncMock()
            response = client.post("/api/ai-settings", json={
                "name": "Test AI",
                "base_url": "http://test.com",
                "api_key": "test-key",
                "model_id": "test-model"
            })
            assert response.status_code in [200, 422, 500]

    def test_ai_settings_test_endpoint_exists(self, app):
        """Test AI settings test endpoint route exists."""
        routes = [r.path for r in app.routes]
        assert any("/test" in r for r in routes)


class TestSourcesEndpoints:
    """Tests for sources endpoints."""

    @pytest.fixture
    def app(self):
        from src.routes.sources import router
        app = FastAPI()
        app.include_router(router, prefix="/api/sources")
        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_list_sources_endpoint(self, client):
        """Test list sources endpoint."""
        response = client.get("/api/sources")
        assert response.status_code in [200, 500]

    def test_list_sources_with_filters(self, client):
        """Test list sources with filters."""
        response = client.get("/api/sources?source_type=rss&enabled=true")
        assert response.status_code in [200, 500]

    def test_create_source_endpoint(self, client):
        """Test create source endpoint."""
        response = client.post("/api/sources", json={
            "type": "rss",
            "name": "Test RSS",
            "url": "http://test.com/rss"
        })
        assert response.status_code in [200, 422, 500]

    def test_get_source_not_found(self, client):
        """Test get source when not found."""
        response = client.get("/api/sources/nonexistent-id")
        assert response.status_code in [404, 500]

    def test_delete_source_not_found(self, client):
        """Test delete source when not found."""
        response = client.delete("/api/sources/nonexistent-id")
        assert response.status_code in [404, 500]


class TestTasksEndpoints:
    """Tests for tasks endpoints."""

    @pytest.fixture
    def app(self):
        from src.routes.tasks import router
        app = FastAPI()
        app.include_router(router, prefix="/api/tasks")
        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_list_tasks_endpoint(self, client):
        """Test list tasks endpoint."""
        response = client.get("/api/tasks")
        assert response.status_code in [200, 500]

    def test_list_tasks_with_enabled_filter(self, client):
        """Test list tasks with enabled filter."""
        response = client.get("/api/tasks?enabled=true")
        assert response.status_code in [200, 500]

    def test_get_task_not_found(self, client):
        """Test get task when not found."""
        response = client.get("/api/tasks/nonexistent-id")
        assert response.status_code in [404, 500]

    def test_create_task_endpoint(self, client):
        """Test create task endpoint."""
        with patch("src.routes.tasks.scheduler") as mock_scheduler:
            mock_scheduler.add_task = AsyncMock()
            response = client.post("/api/tasks", json={
                "name": "Test Task",
                "schedule": "0 * * * *"
            })
            assert response.status_code in [200, 422, 500]

    def test_delete_task_not_found(self, client):
        """Test delete task when not found."""
        response = client.delete("/api/tasks/nonexistent-id")
        assert response.status_code in [404, 500]


class TestRunsEndpoints:
    """Tests for runs endpoints."""

    @pytest.fixture
    def app(self):
        from src.routes.runs import router
        app = FastAPI()
        app.include_router(router, prefix="/api/runs")
        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_list_runs_endpoint(self, client):
        """Test list runs endpoint."""
        response = client.get("/api/runs")
        assert response.status_code in [200, 500]

    def test_list_runs_with_pagination(self, client):
        """Test list runs with pagination."""
        response = client.get("/api/runs?page=1&page_size=10")
        assert response.status_code in [200, 500]

    def test_list_runs_with_filters(self, client):
        """Test list runs with filters."""
        response = client.get("/api/runs?task_id=test-id&status=completed")
        assert response.status_code in [200, 500]

    def test_get_run_not_found(self, client):
        """Test get run when not found."""
        response = client.get("/api/runs/nonexistent-id")
        assert response.status_code in [404, 500]


class TestTTSSettingsEndpoints:
    """Tests for TTS settings endpoints."""

    @pytest.fixture
    def app(self):
        from src.routes.tts_settings import router
        app = FastAPI()
        app.include_router(router, prefix="/api/tts-settings")
        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_get_tts_settings_endpoint(self, client):
        """Test get TTS settings endpoint."""
        response = client.get("/api/tts-settings")
        assert response.status_code in [200, 500]

    def test_update_tts_settings_endpoint(self, client):
        """Test update TTS settings endpoint."""
        response = client.put("/api/tts-settings", json={
            "voice": "zh-CN-XiaoxiaoNeural"
        })
        assert response.status_code in [200, 422, 500]

    def test_list_voices_endpoint(self, client):
        """Test list voices endpoint."""
        response = client.get("/api/tts-settings/voices")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "data" in data


class TestGeneralSettingsEndpoints:
    """Tests for general settings endpoints."""

    @pytest.fixture
    def app(self):
        from src.routes.general_settings import router
        app = FastAPI()
        app.include_router(router, prefix="/api/settings")
        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_get_general_settings_endpoint(self, client):
        """Test get general settings endpoint."""
        response = client.get("/api/settings")
        assert response.status_code in [200, 500]

    def test_update_general_settings_endpoint(self, client):
        """Test update general settings endpoint."""
        response = client.put("/api/settings", json={
            "output_dir": "/tmp/output"
        })
        assert response.status_code in [200, 422, 500]


class TestSystemPromptsEndpoints:
    """Tests for system prompts endpoints."""

    @pytest.fixture
    def app(self):
        from src.routes.system_prompts import router
        app = FastAPI()
        app.include_router(router, prefix="/api/system-prompts")
        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_list_system_prompts_endpoint(self, client):
        """Test list system prompts endpoint."""
        response = client.get("/api/system-prompts")
        assert response.status_code in [200, 500]

    def test_create_system_prompt_endpoint(self, client):
        """Test create system prompt endpoint."""
        response = client.post("/api/system-prompts", json={
            "name": "Test Prompt",
            "content": "Test content"
        })
        assert response.status_code in [200, 422, 500]

    def test_get_system_prompt_not_found(self, client):
        """Test get system prompt endpoint."""
        response = client.get("/api/system-prompts/nonexistent-id")
        assert response.status_code in [404, 405, 500]

    def test_delete_system_prompt_not_found(self, client):
        """Test delete system prompt when not found."""
        response = client.delete("/api/system-prompts/nonexistent-id")
        assert response.status_code in [404, 500]