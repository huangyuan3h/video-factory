"""Deep tests for task_logger module."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile
import json


class TestTaskLoggerDeep:
    """Deep tests for TaskLogger."""

    def test_task_logger_complete(self):
        """Test TaskLogger complete method."""
        from src.core.task_logger import TaskLogger
        
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = TaskLogger("test-id", Path(tmpdir))
            logger.complete(Path(tmpdir) / "output.mp4")
            
            status_file = Path(tmpdir) / "status.json"
            assert status_file.exists()

    def test_task_logger_fail(self):
        """Test TaskLogger fail method."""
        from src.core.task_logger import TaskLogger
        
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = TaskLogger("test-id", Path(tmpdir))
            logger.fail("Test error")
            
            status_file = Path(tmpdir) / "status.json"
            assert status_file.exists()

    def test_task_logger_save_script(self):
        """Test TaskLogger save_script method."""
        from src.core.task_logger import TaskLogger
        
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = TaskLogger("test-id", Path(tmpdir))
            script = {
                "segments": [{"text": "Test", "keywords": ["test"]}]
            }
            logger.save_script(script)
            
            script_file = Path(tmpdir) / "script.json"
            assert script_file.exists()

    def test_task_logger_status_updates(self):
        """Test TaskLogger status updates."""
        from src.core.task_logger import TaskLogger
        
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = TaskLogger("test-id", Path(tmpdir))
            
            logger.step(1, "Step 1")
            logger.info("Info message")
            logger.set_progress(0.25)
            
            status_file = Path(tmpdir) / "status.json"
            if status_file.exists():
                with open(status_file) as f:
                    status = json.load(f)
                    assert status["current_step"] == 1

    def test_task_logger_log_file(self):
        """Test TaskLogger log file."""
        from src.core.task_logger import TaskLogger
        
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = TaskLogger("test-id", Path(tmpdir))
            logger.info("Test log message")
            
            log_file = Path(tmpdir) / "task.log"
            assert log_file.exists()
            with open(log_file) as f:
                content = f.read()
                assert "Test log message" in content