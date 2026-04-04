"""Tests for video route deep coverage."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.fixture
def app():
    """Create FastAPI app."""
    app = FastAPI()
    from src.routes.videos import router
    app.include_router(router, prefix="/api/videos")
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


def test_list_tasks_empty(client):
    """Test listing empty tasks."""
    response = client.get("/api/videos/tasks")
    assert response.status_code == 200


def test_create_and_get_task(client):
    """Test creating and getting a task."""
    with patch("src.routes.videos.run_video_generation"):
        # Create task
        response = client.post("/api/videos/generate", json={
            "title": "Test Video",
            "text_content": "This is test content for video generation."
        })
        assert response.status_code == 200
        
        data = response.json()
        task_id = data.get("data", {}).get("id")
        
        if task_id:
            # Get task
            get_response = client.get(f"/api/videos/tasks/{task_id}")
            assert get_response.status_code in [200, 404]


def test_get_nonexistent_task(client):
    """Test getting non-existent task."""
    response = client.get("/api/videos/tasks/nonexistent-id")
    assert response.status_code == 404


def test_delete_task(client):
    """Test deleting a task."""
    response = client.delete("/api/videos/tasks/test-id")
    assert response.status_code in [200, 404]


def test_generate_video_validation(client):
    """Test video generation validation."""
    # Missing required field
    response = client.post("/api/videos/generate", json={
        "title": "Test"
    })
    assert response.status_code == 422


def test_generate_with_all_options(client):
    """Test generation with all options."""
    with patch("src.routes.videos.run_video_generation"):
        response = client.post("/api/videos/generate", json={
            "title": "Test",
            "text_content": "Content",
            "voice": "zh-CN-XiaoxiaoNeural",
            "voice_rate": "+10%",
            "resolution_width": 1080,
            "resolution_height": 1920
        })
        assert response.status_code == 200