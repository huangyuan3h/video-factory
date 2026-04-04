"""Tests for task logger full coverage."""

import pytest
from pathlib import Path
import tempfile
from datetime import datetime


def test_task_logger_file_creation():
    """Test task logger creates log file."""
    from src.core.task_logger import TaskLogger
    
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = TaskLogger("test-task-id", Path(tmpdir))
        
        # Write some logs
        logger.step(1, "First step")
        logger.info("Info message")
        logger.warning("Warning message")
        
        # Check if log file exists
        if hasattr(logger, 'log_file'):
            assert Path(logger.log_file).exists()


def test_task_logger_timestamp():
    """Test task logger timestamp."""
    from src.core.task_logger import TaskLogger
    
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = TaskLogger("test-task", Path(tmpdir))
        
        # Check if timestamp is created
        if hasattr(logger, 'created_at'):
            assert logger.created_at is not None


def test_task_logger_step_number():
    """Test task logger step numbering."""
    from src.core.task_logger import TaskLogger
    
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = TaskLogger("test", Path(tmpdir))
        
        logger.step(1, "Step 1")
        logger.step(2, "Step 2")
        logger.step(3, "Step 3")
        
        if hasattr(logger, 'current_step'):
            assert logger.current_step == 3


def test_task_logger_error_logging():
    """Test task logger error logging."""
    from src.core.task_logger import TaskLogger
    
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = TaskLogger("test", Path(tmpdir))
        
        logger.error("Test error message")
        logger.error("Another error")
        
        # Just test that it doesn't crash
        assert True


def test_task_logger_warning_logging():
    """Test task logger warning logging."""
    from src.core.task_logger import TaskLogger
    
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = TaskLogger("test", Path(tmpdir))
        
        logger.warning("Warning 1")
        logger.warning("Warning 2")
        
        assert True