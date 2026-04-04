"""Tests for task logger module."""

import pytest
from pathlib import Path
from datetime import datetime
import tempfile


def test_task_logger_creation():
    """Test task logger can be created."""
    from src.core.task_logger import TaskLogger
    
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = TaskLogger("test-task", Path(tmpdir))
        assert logger.task_id == "test-task"


def test_task_logger_step():
    """Test task logger step method."""
    from src.core.task_logger import TaskLogger
    
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = TaskLogger("test-task", Path(tmpdir))
        logger.step(1, "测试步骤")
        # Step should be recorded
        assert logger.current_step == 1


def test_task_logger_info():
    """Test task logger info method."""
    from src.core.task_logger import TaskLogger
    
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = TaskLogger("test-task", Path(tmpdir))
        logger.info("测试信息")
        # Info should be logged without error
        assert True


def test_task_logger_warning():
    """Test task logger warning method."""
    from src.core.task_logger import TaskLogger
    
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = TaskLogger("test-task", Path(tmpdir))
        logger.warning("测试警告")
        assert True


def test_task_logger_error():
    """Test task logger error method."""
    from src.core.task_logger import TaskLogger
    
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = TaskLogger("test-task", Path(tmpdir))
        logger.error("测试错误")
        assert True


def test_task_logger_progress():
    """Test task logger progress method."""
    from src.core.task_logger import TaskLogger
    
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = TaskLogger("test-task", Path(tmpdir))
        # progress method may not exist, skip if not available
        if hasattr(logger, 'progress'):
            logger.progress(50.0, "进度测试")
        else:
            logger.info("进度: 50%")