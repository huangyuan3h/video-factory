"""Additional tests for database module."""

import pytest


def test_database_engine_property():
    """Test database engine property."""
    from src.database import engine
    
    assert engine is not None


def test_database_session_property():
    """Test database session property."""
    from src.database import async_session_maker
    
    assert async_session_maker is not None


def test_database_base_property():
    """Test database base property."""
    from src.database import Base
    
    assert Base is not None


def test_database_models():
    """Test database models are imported."""
    from src import models
    
    assert hasattr(models, 'AISetting')
    assert hasattr(models, 'Source')
    assert hasattr(models, 'Task')
    assert hasattr(models, 'Run')