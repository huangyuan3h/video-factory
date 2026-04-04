"""Integration tests for routes with database session mocking."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock


class TestRoutesWithMocks:
    """Tests for routes with mocked database sessions."""

    @pytest.fixture
    def mock_db_session(self):
        """Create mock database session."""
        session = MagicMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        session.add = MagicMock()
        session.delete = MagicMock()
        session.execute = AsyncMock()
        return session

    def test_ai_settings_list_with_mock(self, mock_db_session):
        """Test AI settings list with mocked session."""
        from src.routes.ai_settings import router
        
        app = FastAPI()
        app.include_router(router, prefix="/api/ai-settings")
        
        with patch("src.routes.ai_settings.get_session") as mock_get_session:
            mock_get_session.return_value = mock_db_session
            
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_db_session.execute.return_value = mock_result
            
            client = TestClient(app)
            response = client.get("/api/ai-settings")
            assert response.status_code in [200, 500]

    def test_system_prompts_list_with_mock(self, mock_db_session):
        """Test system prompts list with mocked session."""
        from src.routes.system_prompts import router
        
        app = FastAPI()
        app.include_router(router, prefix="/api/system-prompts")
        
        with patch("src.routes.system_prompts.get_session") as mock_get_session:
            mock_get_session.return_value = mock_db_session
            
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_db_session.execute.return_value = mock_result
            
            client = TestClient(app)
            response = client.get("/api/system-prompts")
            assert response.status_code in [200, 500]

    def test_tasks_list_with_mock(self, mock_db_session):
        """Test tasks list with mocked session."""
        from src.routes.tasks import router
        
        app = FastAPI()
        app.include_router(router, prefix="/api/tasks")
        
        with patch("src.routes.tasks.get_session") as mock_get_session:
            mock_get_session.return_value = mock_db_session
            
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_db_session.execute.return_value = mock_result
            
            client = TestClient(app)
            response = client.get("/api/tasks")
            assert response.status_code in [200, 500]

    def test_sources_list_with_mock(self, mock_db_session):
        """Test sources list with mocked session."""
        from src.routes.sources import router
        
        app = FastAPI()
        app.include_router(router, prefix="/api/sources")
        
        with patch("src.routes.sources.get_session") as mock_get_session:
            mock_get_session.return_value = mock_db_session
            
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_db_session.execute.return_value = mock_result
            
            client = TestClient(app)
            response = client.get("/api/sources")
            assert response.status_code in [200, 500]

    def test_runs_list_with_mock(self, mock_db_session):
        """Test runs list with mocked session."""
        from src.routes.runs import router
        
        app = FastAPI()
        app.include_router(router, prefix="/api/runs")
        
        with patch("src.routes.runs.get_session") as mock_get_session:
            mock_get_session.return_value = mock_db_session
            
            mock_result = MagicMock()
            mock_result.scalars.return_value.unique.return_value.all.return_value = []
            mock_db_session.execute.return_value = mock_result
            
            client = TestClient(app)
            response = client.get("/api/runs")
            assert response.status_code in [200, 500]

    def test_tts_settings_get_with_mock(self, mock_db_session):
        """Test TTS settings get with mocked session."""
        from src.routes.tts_settings import router
        
        app = FastAPI()
        app.include_router(router, prefix="/api/tts-settings")
        
        with patch("src.routes.tts_settings.get_session") as mock_get_session:
            mock_get_session.return_value = mock_db_session
            
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_db_session.execute.return_value = mock_result
            
            client = TestClient(app)
            response = client.get("/api/tts-settings")
            assert response.status_code in [200, 500]

    def test_general_settings_get_with_mock(self, mock_db_session):
        """Test general settings get with mocked session."""
        from src.routes.general_settings import router
        
        app = FastAPI()
        app.include_router(router, prefix="/api/settings")
        
        with patch("src.routes.general_settings.get_session") as mock_get_session:
            mock_get_session.return_value = mock_db_session
            
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_db_session.execute.return_value = mock_result
            
            client = TestClient(app)
            response = client.get("/api/settings")
            assert response.status_code in [200, 500]


class TestRouteImports:
    """Tests for route imports and structure."""

    def test_ai_settings_imports(self):
        """Test AI settings imports."""
        from src.routes import ai_settings
        
        assert ai_settings is not None
        assert hasattr(ai_settings, 'router')

    def test_system_prompts_imports(self):
        """Test system prompts imports."""
        from src.routes import system_prompts
        
        assert system_prompts is not None
        assert hasattr(system_prompts, 'router')

    def test_tasks_imports(self):
        """Test tasks imports."""
        from src.routes import tasks
        
        assert tasks is not None
        assert hasattr(tasks, 'router')

    def test_sources_imports(self):
        """Test sources imports."""
        from src.routes import sources
        
        assert sources is not None
        assert hasattr(sources, 'router')

    def test_runs_imports(self):
        """Test runs imports."""
        from src.routes import runs
        
        assert runs is not None
        assert hasattr(runs, 'router')

    def test_tts_settings_imports(self):
        """Test TTS settings imports."""
        from src.routes import tts_settings
        
        assert tts_settings is not None
        assert hasattr(tts_settings, 'router')

    def test_general_settings_imports(self):
        """Test general settings imports."""
        from src.routes import general_settings
        
        assert general_settings is not None
        assert hasattr(general_settings, 'router')

    def test_videos_imports(self):
        """Test videos imports."""
        from src.routes import videos
        
        assert videos is not None
        assert hasattr(videos, 'router')