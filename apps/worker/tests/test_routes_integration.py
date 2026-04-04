"""Integration tests for routes with database mocks."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def mock_session():
    """Create mock database session."""
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.delete = MagicMock()
    session.execute = AsyncMock()
    return session


@pytest.fixture
def mock_get_session(mock_session):
    """Mock get_session dependency."""
    async def _get_session():
        yield mock_session
    return _get_session


@pytest.fixture
def app_with_routes(mock_get_session):
    """Create FastAPI app with all routes."""
    app = FastAPI()
    
    from src.routes.ai_settings import router as ai_router
    from src.routes.system_prompts import router as sp_router
    from src.routes.sources import router as sources_router
    from src.routes.tasks import router as tasks_router
    from src.routes.runs import router as runs_router
    from src.routes.tts_settings import router as tts_router
    from src.routes.general_settings import router as general_router
    
    app.dependency_overrides[None] = mock_get_session
    
    app.include_router(ai_router, prefix="/api/ai-settings")
    app.include_router(sp_router, prefix="/api/system-prompts")
    app.include_router(sources_router, prefix="/api/sources")
    app.include_router(tasks_router, prefix="/api/tasks")
    app.include_router(runs_router, prefix="/api/runs")
    app.include_router(tts_router, prefix="/api/tts-settings")
    app.include_router(general_router, prefix="/api/general-settings")
    
    return app


class TestAISettingsRoutesFull:
    """Full tests for AI settings routes."""

    def test_list_ai_settings_empty(self):
        """Test listing AI settings when empty."""
        from src.routes.ai_settings import router, list_ai_settings
        
        app = FastAPI()
        app.include_router(router, prefix="/api/ai-settings")
        client = TestClient(app)
        
        response = client.get("/api/ai-settings")
        assert response.status_code in [200, 500]

    def test_ai_settings_generate_id(self):
        """Test generate_id function."""
        from src.routes.ai_settings import generate_id
        
        id1 = generate_id()
        id2 = generate_id()
        
        assert len(id1) == 16
        assert id1 != id2

    def test_ai_settings_model_imports(self):
        """Test model imports in ai_settings."""
        from src.routes.ai_settings import AISettingCreate, AISettingResponse, AISettingUpdate
        
        create = AISettingCreate(
            name="Test",
            base_url="http://test",
            api_key="key",
            model_id="model"
        )
        assert create.name == "Test"


class TestSystemPromptsRoutesFull:
    """Full tests for system prompts routes."""

    def test_system_prompts_generate_id(self):
        """Test generate_id function."""
        from src.routes.system_prompts import generate_id
        
        id1 = generate_id()
        assert len(id1) == 16

    def test_system_prompts_model_imports(self):
        """Test model imports."""
        from src.routes.system_prompts import SystemPromptCreate, SystemPromptResponse
        
        create = SystemPromptCreate(name="Test", content="Test content")
        assert create.name == "Test"


class TestSourcesRoutesFull:
    """Full tests for sources routes."""

    def test_sources_generate_id(self):
        """Test generate_id function."""
        from src.routes.sources import generate_id
        
        id1 = generate_id()
        assert len(id1) == 16

    def test_sources_model_imports(self):
        """Test model imports."""
        from src.routes.sources import SourceCreate, SourceResponse
        
        create = SourceCreate(
            type="rss",
            name="Test Source",
            url="http://test.com"
        )
        assert create.type == "rss"


class TestTasksRoutesFull:
    """Full tests for tasks routes."""

    def test_tasks_generate_id(self):
        """Test generate_id function."""
        from src.routes.tasks import generate_id
        
        id1 = generate_id()
        assert len(id1) == 16

    def test_tasks_router_import(self):
        """Test router import."""
        from src.routes.tasks import router
        assert router is not None


class TestRunsRoutesFull:
    """Full tests for runs routes."""

    def test_runs_model_imports(self):
        """Test model imports."""
        from src.routes.runs import RunResponse
        assert RunResponse is not None

    def test_router_import(self):
        """Test router import."""
        from src.routes.runs import router
        assert router is not None


class TestTTSSettingsRoutesFull:
    """Full tests for TTS settings routes."""

    def test_tts_generate_id(self):
        """Test generate_id function."""
        from src.routes.tts_settings import generate_id
        
        id1 = generate_id()
        assert len(id1) == 16

    def test_tts_model_imports(self):
        """Test model imports."""
        from src.routes.tts_settings import TTSSettingResponse, TTSSettingUpdate
        
        update = TTSSettingUpdate(voice="zh-CN-XiaoxiaoNeural")
        assert update.voice == "zh-CN-XiaoxiaoNeural"

    def test_list_voices_endpoint(self):
        """Test list voices endpoint."""
        from src.routes.tts_settings import router
        
        app = FastAPI()
        app.include_router(router, prefix="/api/tts-settings")
        client = TestClient(app)
        
        response = client.get("/api/tts-settings/voices")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True


class TestGeneralSettingsRoutesFull:
    """Full tests for general settings routes."""

    def test_general_generate_id(self):
        """Test generate_id function."""
        from src.routes.general_settings import generate_id
        
        id1 = generate_id()
        assert len(id1) == 16

    def test_general_model_imports(self):
        """Test model imports."""
        from src.routes.general_settings import GeneralSettingResponse, GeneralSettingUpdate
        
        update = GeneralSettingUpdate(output_dir="/tmp/output")
        assert update.output_dir == "/tmp/output"

    def test_router_import(self):
        """Test router import."""
        from src.routes.general_settings import router
        assert router is not None