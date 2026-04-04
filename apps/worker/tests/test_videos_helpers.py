"""Tests for videos route helper functions."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path
import tempfile


class TestVideosHelperFunctions:
    """Tests for videos route helper functions."""

    def test_video_generate_request_full(self):
        """Test VideoGenerateRequest with all fields."""
        from src.routes.videos import VideoGenerateRequest
        
        req = VideoGenerateRequest(
            title="Full Test",
            text_content="Full content",
            system_prompt="System prompt",
            background_music="music.mp3",
            generate_subtitle=False,
            subtitle_color="&H000000FF",
            subtitle_font="Arial",
            voice="zh-CN-YunxiNeural",
            voice_rate="-10%",
            background_source="pexels",
            resolution_width=1280,
            resolution_height=720
        )
        assert req.background_music == "music.mp3"
        assert req.generate_subtitle is False
        assert req.background_source == "pexels"

    @pytest.mark.asyncio
    async def test_get_active_ai_client_with_setting(self):
        """Test get_active_ai_client with setting."""
        from src.services.settings_service import get_active_ai_client
        
        with patch("src.services.settings_service.async_session_maker") as mock_maker:
            mock_sess = AsyncMock()
            mock_maker.return_value.__aenter__ = AsyncMock(return_value=mock_sess)
            mock_maker.return_value.__aexit__ = AsyncMock()
            
            mock_setting = MagicMock()
            mock_setting.base_url = "http://test"
            mock_setting.api_key = "key"
            mock_setting.model_id = "model"
            
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_setting
            mock_sess.execute = AsyncMock(return_value=mock_result)
            
            result = await get_active_ai_client()
            assert result is not None

    @pytest.mark.asyncio
    async def test_get_general_settings_with_setting(self):
        """Test get_general_settings with setting."""
        from src.services.settings_service import get_general_settings
        
        with patch("src.services.settings_service.async_session_maker") as mock_maker:
            mock_sess = AsyncMock()
            mock_maker.return_value.__aenter__ = AsyncMock(return_value=mock_sess)
            mock_maker.return_value.__aexit__ = AsyncMock()
            
            mock_setting = MagicMock()
            mock_setting.pexels_api_key = "pexels-key"
            mock_setting.pixabay_api_key = "pixabay-key"
            
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_setting
            mock_sess.execute = AsyncMock(return_value=mock_result)
            
            result = await get_general_settings()
            assert "pexels_api_key" in result

    def test_video_tasks_global(self):
        """Test video_tasks global variable."""
        from src.routes.videos import video_tasks
        
        assert isinstance(video_tasks, dict)


class TestVideoTaskStatus:
    """Tests for video task status management."""

    @pytest.fixture
    def app(self):
        from fastapi import FastAPI
        from src.routes.videos import router
        app = FastAPI()
        app.include_router(router, prefix="/api/videos")
        return app

    @pytest.fixture
    def client(self, app):
        from fastapi.testclient import TestClient
        return TestClient(app)

    def test_task_status_pending(self, client):
        """Test task status pending."""
        from src.routes.videos import video_tasks
        
        video_tasks["pending-task"] = {
            "id": "pending-task",
            "status": "pending",
            "progress": 0.0
        }
        
        response = client.get("/api/videos/tasks/pending-task")
        assert response.status_code == 200

    def test_task_status_processing(self, client):
        """Test task status processing."""
        from src.routes.videos import video_tasks
        
        video_tasks["processing-task"] = {
            "id": "processing-task",
            "status": "processing",
            "progress": 0.5
        }
        
        response = client.get("/api/videos/tasks/processing-task")
        assert response.status_code == 200

    def test_task_status_completed(self, client):
        """Test task status completed."""
        from src.routes.videos import video_tasks
        
        video_tasks["completed-task"] = {
            "id": "completed-task",
            "status": "completed",
            "progress": 1.0,
            "video_path": "/tmp/output.mp4"
        }
        
        response = client.get("/api/videos/tasks/completed-task")
        assert response.status_code == 200

    def test_task_status_failed(self, client):
        """Test task status failed."""
        from src.routes.videos import video_tasks
        
        video_tasks["failed-task"] = {
            "id": "failed-task",
            "status": "failed",
            "error": "Test error"
        }
        
        response = client.get("/api/videos/tasks/failed-task")
        assert response.status_code == 200


class TestVideoGenerationEndpoint:
    """Tests for video generation endpoint."""

    @pytest.fixture
    def app(self):
        from fastapi import FastAPI
        from src.routes.videos import router
        app = FastAPI()
        app.include_router(router, prefix="/api/videos")
        return app

    @pytest.fixture
    def client(self, app):
        from fastapi.testclient import TestClient
        return TestClient(app)

    def test_generate_with_minimal_params(self, client):
        """Test generate with minimal params."""
        with patch("src.routes.videos.run_video_generation"):
            response = client.post("/api/videos/generate", json={
                "title": "Minimal",
                "text_content": "Minimal content"
            })
            assert response.status_code == 200

    def test_generate_with_all_params(self, client):
        """Test generate with all params."""
        with patch("src.routes.videos.run_video_generation"):
            response = client.post("/api/videos/generate", json={
                "title": "Full",
                "text_content": "Full content",
                "system_prompt": "Prompt",
                "voice": "zh-CN-YunxiNeural",
                "voice_rate": "+10%",
                "resolution_width": 720,
                "resolution_height": 1280
            })
            assert response.status_code == 200

    def test_generate_validation_error(self, client):
        """Test generate validation error."""
        response = client.post("/api/videos/generate", json={
            "title": ""
        })
        assert response.status_code == 422