"""Tests for database module."""

import pytest
from unittest.mock import MagicMock, patch


def test_database_session_maker():
    """Test async_session_maker creation."""
    from src.database import async_session_maker
    
    assert async_session_maker is not None


def test_database_engine():
    """Test engine creation."""
    from src.database import engine
    
    assert engine is not None


def test_database_base():
    """Test Base model."""
    from src.database import Base
    
    assert Base is not None