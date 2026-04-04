"""Tests for video generation API routes."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch

from src.routes.videos import router, video_tasks


@pytest.fixture
def app():
    """Create FastAPI app with videos router."""
    app = FastAPI()
    app.include_router(router, prefix="/api/videos")
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


class TestGenerateVideo:
    """Tests for POST /api/videos/generate endpoint."""

    def test_generate_video_success(self, client):
        """Test successful video generation request."""
        with patch("src.routes.videos.run_video_generation"):
            response = client.post("/api/videos/generate", json={
                "title": "测试视频",
                "text_content": "这是一段测试内容，用于生成视频。",
            })
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "id" in data["data"]
            assert data["data"]["status"] == "pending"

    def test_generate_video_missing_required_field(self, client):
        """Test video generation with missing required field."""
        response = client.post("/api/videos/generate", json={
            "title": "测试视频",
        })
        
        assert response.status_code == 422


class TestGetTaskStatus:
    """Tests for GET /api/videos/tasks/{task_id} endpoint."""

    def test_get_existing_task(self, client):
        """Test getting an existing task."""
        video_tasks["test-task-1"] = {
            "id": "test-task-1",
            "status": "processing",
            "progress": 0.5,
            "message": "Generating video...",
        }
        
        response = client.get("/api/videos/tasks/test-task-1")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["id"] == "test-task-1"
        assert data["data"]["progress"] == 0.5

    def test_get_non_existing_task(self, client):
        """Test getting a non-existing task."""
        response = client.get("/api/videos/tasks/non-existing-id")
        
        assert response.status_code == 404

    def test_get_completed_task(self, client):
        """Test getting a completed task."""
        video_tasks["completed-task"] = {
            "id": "completed-task",
            "status": "completed",
            "progress": 1.0,
            "message": "Video generation completed",
            "video_path": "/tmp/output.mp4",
        }
        
        response = client.get("/api/videos/tasks/completed-task")
        
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["status"] == "completed"
        assert data["data"]["video_path"] == "/tmp/output.mp4"

    def test_get_failed_task(self, client):
        """Test getting a failed task."""
        video_tasks["failed-task"] = {
            "id": "failed-task",
            "status": "failed",
            "progress": 0.3,
            "message": "API Error",
            "error": "Connection timeout",
        }
        
        response = client.get("/api/videos/tasks/failed-task")
        
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["status"] == "failed"
        assert data["data"]["error"] == "Connection timeout"


class TestListTasks:
    """Tests for GET /api/videos/tasks endpoint."""

    def test_list_empty_tasks(self, client):
        """Test listing tasks when empty."""
        video_tasks.clear()
        
        response = client.get("/api/videos/tasks")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"] == []

    def test_list_multiple_tasks(self, client):
        """Test listing multiple tasks."""
        video_tasks.clear()
        video_tasks["task-1"] = {"id": "task-1", "status": "pending"}
        video_tasks["task-2"] = {"id": "task-2", "status": "processing"}
        video_tasks["task-3"] = {"id": "task-3", "status": "completed"}
        
        response = client.get("/api/videos/tasks")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 3

    def test_list_tasks_includes_all_fields(self, client):
        """Test that listed tasks include all expected fields."""
        video_tasks.clear()
        video_tasks["full-task"] = {
            "id": "full-task",
            "status": "completed",
            "progress": 1.0,
            "message": "Done",
            "created_at": "2024-01-01T00:00:00",
            "request": {"title": "Test"},
        }
        
        response = client.get("/api/videos/tasks")
        
        assert response.status_code == 200
        task = response.json()["data"][0]
        assert "id" in task
        assert "status" in task
        assert "progress" in task
        assert "message" in task


class TestDeleteTask:
    """Tests for DELETE /api/videos/tasks/{task_id} endpoint."""

    def test_delete_existing_task(self, client):
        """Test deleting an existing task."""
        video_tasks["delete-me"] = {"id": "delete-me", "status": "completed"}
        
        response = client.delete("/api/videos/tasks/delete-me")
        
        assert response.status_code == 200
        assert "delete-me" not in video_tasks

    def test_delete_non_existing_task(self, client):
        """Test deleting a non-existing task."""
        response = client.delete("/api/videos/tasks/non-existing")
        
        assert response.status_code == 404

    def test_delete_and_recreate_task(self, client):
        """Test deleting and recreating a task with same ID."""
        video_tasks["recreate"] = {"id": "recreate", "status": "old"}
        
        client.delete("/api/videos/tasks/recreate")
        
        video_tasks["recreate"] = {"id": "recreate", "status": "new"}
        
        response = client.get("/api/videos/tasks/recreate")
        assert response.json()["data"]["status"] == "new"


class TestVideoGenerateRequest:
    """Tests for VideoGenerateRequest model."""

    def test_default_values(self):
        """Test default values of request model."""
        from src.routes.videos import VideoGenerateRequest
        
        request = VideoGenerateRequest(
            title="Test",
            text_content="Content",
        )
        
        assert request.system_prompt == ""
        assert request.background_music is None
        assert request.generate_subtitle is True
        assert request.subtitle_color == "&H00FFFFFF"
        assert request.subtitle_font == "Microsoft YaHei"
        assert request.voice == "zh-CN-XiaoxiaoNeural"
        assert request.voice_rate == "+0%"
        assert request.background_source == "both"
        assert request.resolution_width == 1080
        assert request.resolution_height == 1920

    def test_custom_values(self):
        """Test custom values of request model."""
        from src.routes.videos import VideoGenerateRequest
        
        request = VideoGenerateRequest(
            title="Custom Title",
            text_content="Custom Content",
            system_prompt="Custom prompt",
            voice="zh-CN-YunxiNeural",
            voice_rate="+20%",
            resolution_width=720,
            resolution_height=1280,
        )
        
        assert request.title == "Custom Title"
        assert request.text_content == "Custom Content"
        assert request.system_prompt == "Custom prompt"
        assert request.voice == "zh-CN-YunxiNeural"
        assert request.voice_rate == "+20%"
        assert request.resolution_width == 720
        assert request.resolution_height == 1280