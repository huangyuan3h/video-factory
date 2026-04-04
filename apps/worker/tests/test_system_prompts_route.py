"""Tests for system prompts route."""

import pytest


def test_system_prompts_router():
    """Test system prompts router exists."""
    from src.routes.system_prompts import router
    
    assert router is not None


def test_system_prompts_imports():
    """Test system prompts imports."""
    from src.routes import system_prompts
    
    assert system_prompts is not None