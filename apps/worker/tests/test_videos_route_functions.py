"""Deep tests for videos route functions."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path
from datetime import datetime


class TestVideosRouteFunctions:
    """Tests for videos route functions."""

    def test_video_generate_request_defaults(self):
        """Test VideoGenerateRequest default values."""
        from src.routes.videos import VideoGenerateRequest
        
        req = VideoGenerateRequest(title="Test", text_content="Content")
        assert req.system_prompt == ""
        assert req.background_music is None
        assert req.generate_subtitle is True
        assert req.subtitle_color == "&H00FFFFFF"
        assert req.subtitle_font == "Microsoft YaHei"
        assert req.voice == "zh-CN-XiaoxiaoNeural"
        assert req.voice_rate == "+0%"
        assert req.background_source == "both"
        assert req.resolution_width == 1080
        assert req.resolution_height == 1920

    def test_video_generate_request_custom(self):
        """Test VideoGenerateRequest custom values."""
        from src.routes.videos import VideoGenerateRequest
        
        req = VideoGenerateRequest(
            title="Custom",
            text_content="Content",
            system_prompt="Custom prompt",
            voice="zh-CN-YunxiNeural",
            voice_rate="+20%",
            resolution_width=720,
            resolution_height=1280
        )
        assert req.system_prompt == "Custom prompt"
        assert req.voice == "zh-CN-YunxiNeural"

    @pytest.mark.asyncio
    async def test_get_active_ai_client_none(self):
        """Test get_active_ai_client returns None when no setting."""
        from src.routes.videos import get_active_ai_client
        
        with patch("src.routes.videos.async_session_maker") as mock_session:
            mock_sess = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_sess)
            
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_sess.execute = AsyncMock(return_value=mock_result)
            
            result = await get_active_ai_client()
            assert result is None

    @pytest.mark.asyncio
    async def test_get_general_settings_none(self):
        """Test get_general_settings returns empty dict when no setting."""
        from src.routes.videos import get_general_settings
        
        with patch("src.routes.videos.async_session_maker") as mock_session:
            mock_sess = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_sess)
            
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_sess.execute = AsyncMock(return_value=mock_result)
            
            result = await get_general_settings()
            assert result == {}

    def test_video_tasks_dict(self):
        """Test video_tasks is a dict."""
        from src.routes.videos import video_tasks
        
        assert isinstance(video_tasks, dict)


class TestVideosRouteEndpoints:
    """Tests for videos route endpoints."""

    @pytest.fixture
    def app(self):
        from src.routes.videos import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router, prefix="/api/videos")
        return app

    @pytest.fixture
    def client(self, app):
        from fastapi.testclient import TestClient
        return TestClient(app)

    def test_generate_endpoint_exists(self, app):
        """Test generate endpoint exists."""
        routes = [r.path for r in app.routes]
        assert "/api/videos/generate" in routes

    def test_tasks_endpoint_exists(self, app):
        """Test tasks endpoint exists."""
        routes = [r.path for r in app.routes]
        assert "/api/videos/tasks" in routes

    def test_generate_video_success(self, client):
        """Test generate video endpoint."""
        with patch("src.routes.videos.run_video_generation"):
            response = client.post("/api/videos/generate", json={
                "title": "Test Video",
                "text_content": "Test content for video"
            })
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True

    def test_generate_video_missing_field(self, client):
        """Test generate video with missing field."""
        response = client.post("/api/videos/generate", json={
            "title": "Test Video"
        })
        assert response.status_code == 422

    def test_list_tasks_endpoint(self, client):
        """Test list tasks endpoint."""
        response = client.get("/api/videos/tasks")
        assert response.status_code == 200

    def test_get_task_not_found(self, client):
        """Test get task when not found."""
        response = client.get("/api/videos/tasks/nonexistent-id")
        assert response.status_code == 404

    def test_delete_task_not_found(self, client):
        """Test delete task when not found."""
        response = client.delete("/api/videos/tasks/nonexistent-id")
        assert response.status_code == 404

    def test_get_task_log_not_found(self, client):
        """Test get task log when not found."""
        response = client.get("/api/videos/tasks/nonexistent-id/log")
        assert response.status_code == 404


class TestVideosTaskManagement:
    """Tests for video task management."""

    def test_video_tasks_operations(self):
        """Test video_tasks operations."""
        from src.routes.videos import video_tasks
        
        video_tasks.clear()
        
        video_tasks["test-1"] = {
            "id": "test-1",
            "status": "pending",
            "progress": 0.0
        }
        
        assert "test-1" in video_tasks
        assert video_tasks["test-1"]["status"] == "pending"
        
        del video_tasks["test-1"]
        assert "test-1" not in video_tasks