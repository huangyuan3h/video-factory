"""More tests for routes."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch


def test_runs_route():
    """Test runs route."""
    from src.routes.runs import router
    
    app = FastAPI()
    app.include_router(router, prefix="/api/runs")
    client = TestClient(app)
    
    assert router is not None


def test_system_prompts_route():
    """Test system prompts route."""
    from src.routes.system_prompts import router
    
    assert router is not None


def test_tts_settings_route():
    """Test TTS settings route."""
    from src.routes.tts_settings import router
    
    assert router is not None


def test_general_settings_route():
    """Test general settings route."""
    from src.routes.general_settings import router
    
    assert router is not None