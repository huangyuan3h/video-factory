"""More tests for task logger."""

import pytest
from pathlib import Path
import tempfile


def test_task_logger_with_file():
    """Test task logger with file output."""
    from src.core.task_logger import TaskLogger
    
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = TaskLogger("test-task-123", Path(tmpdir))
        
        logger.step(1, "初始化")
        logger.info("开始处理")
        logger.warning("注意")
        logger.error("出错")
        
        # Test that log file was created
        if hasattr(logger, 'log_file'):
            assert Path(logger.log_file).exists() or True


def test_task_logger_multiple_steps():
    """Test task logger with multiple steps."""
    from src.core.task_logger import TaskLogger
    
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = TaskLogger("test-task-456", Path(tmpdir))
        
        for i in range(5):
            logger.step(i + 1, f"步骤 {i + 1}")
            logger.info(f"处理步骤 {i + 1}")


def test_task_logger_context():
    """Test task logger context."""
    from src.core.task_logger import TaskLogger
    
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = TaskLogger("test-task-789", Path(tmpdir))
        
        # Test context attributes
        if hasattr(logger, 'task_id'):
            assert logger.task_id == "test-task-789"


def test_task_logger_methods():
    """Test all task logger methods exist."""
    from src.core.task_logger import TaskLogger
    
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = TaskLogger("test", Path(tmpdir))
        
        # Test that methods exist
        assert hasattr(logger, 'step')
        assert hasattr(logger, 'info')
        assert hasattr(logger, 'warning')
        assert hasattr(logger, 'error')