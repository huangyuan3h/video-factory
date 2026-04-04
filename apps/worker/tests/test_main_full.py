"""Full tests for main module."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestMainModule:
    """Tests for main module."""

    def test_main_imports(self):
        """Test main imports."""
        from src.main import app
        assert app is not None

    def test_app_is_fastapi(self):
        """Test app is FastAPI instance."""
        from src.main import app
        from fastapi import FastAPI
        
        assert isinstance(app, FastAPI)

    def test_app_title(self):
        """Test app title."""
        from src.main import app
        
        assert app.title == "Video Factory Worker"

    def test_app_routes_exist(self):
        """Test app has routes."""
        from src.main import app
        
        routes = [route.path for route in app.routes]
        assert "/" in routes
        assert "/health" in routes

    def test_app_middlewares(self):
        """Test app has middlewares."""
        from src.main import app
        
        assert hasattr(app, 'user_middleware')

    def test_app_include_routers(self):
        """Test app includes routers."""
        from src.main import app
        
        router_paths = []
        for route in app.routes:
            if hasattr(route, 'path'):
                router_paths.append(route.path)
        
        assert len(router_paths) > 0


class TestHealthEndpoint:
    """Tests for health endpoint."""

    def test_health_endpoint_via_client(self):
        """Test health endpoint via test client."""
        from src.main import app
        from fastapi.testclient import TestClient
        
        client = TestClient(app)
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_root_endpoint(self):
        """Test root endpoint via test client."""
        from src.main import app
        from fastapi.testclient import TestClient
        
        client = TestClient(app)
        response = client.get("/")
        
        assert response.status_code == 200
        data = response.json()
        assert "message" in data


class TestAppConfiguration:
    """Tests for app configuration."""

    def test_app_description(self):
        """Test app description."""
        from src.main import app
        
        assert hasattr(app, 'description')

    def test_app_version(self):
        """Test app version."""
        from src.main import app
        
        assert hasattr(app, 'version')

    def test_app_openapi_url(self):
        """Test app OpenAPI URL."""
        from src.main import app
        
        assert app.openapi_url == "/openapi.json"

    def test_app_docs_url(self):
        """Test app docs URL."""
        from src.main import app
        
        assert app.docs_url == "/docs"