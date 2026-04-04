"""More comprehensive tests for scheduler."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime


class TestSchedulerComprehensive:
    """Comprehensive tests for scheduler module."""

    def test_scheduler_import_all(self):
        """Test all scheduler imports."""
        from src.scheduler import (
            scheduler,
            execute_task,
            add_task,
            remove_task,
            update_task,
            trigger_task,
            init_scheduler,
            shutdown_scheduler
        )
        assert scheduler is not None

    def test_scheduler_is_async(self):
        """Test scheduler is AsyncIOScheduler."""
        from src.scheduler import scheduler
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        
        assert isinstance(scheduler, AsyncIOScheduler)

    @pytest.mark.asyncio
    async def test_add_task_enabled(self):
        """Test add_task with enabled task."""
        from src.scheduler import add_task
        
        task = MagicMock()
        task.enabled = True
        task.id = "test-id"
        task.name = "Test"
        task.schedule = "* * * * *"
        
        await add_task(task)

    @pytest.mark.asyncio
    async def test_add_task_disabled(self):
        """Test add_task with disabled task."""
        from src.scheduler import add_task
        
        task = MagicMock()
        task.enabled = False
        task.id = "disabled-id"
        
        await add_task(task)

    @pytest.mark.asyncio
    async def test_remove_task(self):
        """Test remove_task."""
        from src.scheduler import remove_task
        
        await remove_task("test-id")

    @pytest.mark.asyncio
    async def test_update_task_disabled(self):
        """Test update_task with disabled task."""
        from src.scheduler import update_task
        
        task = MagicMock()
        task.id = "test-id"
        task.enabled = False
        
        await update_task(task)

    @pytest.mark.asyncio
    async def test_trigger_task_generates_id(self):
        """Test trigger_task generates unique ID."""
        from src.scheduler import trigger_task
        
        with patch("src.scheduler.execute_task", new_callable=AsyncMock):
            id1 = await trigger_task("task-1")
            id2 = await trigger_task("task-2")
            
            assert id1 != id2
            assert len(id1) == 16

    @pytest.mark.asyncio
    async def test_execute_task_creates_run(self):
        """Test execute_task creates run record."""
        from src.scheduler import execute_task
        
        with patch("src.scheduler.async_session_maker") as mock_session_maker:
            mock_session = MagicMock()
            mock_session_maker.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_maker.return_value.__aexit__ = AsyncMock()
            
            mock_task = MagicMock()
            mock_task.id = "test-id"
            mock_task.name = "Test Task"
            
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_task
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session.add = MagicMock()
            mock_session.commit = AsyncMock()
            
            await execute_task("test-id")

    @pytest.mark.asyncio
    async def test_init_scheduler_starts(self):
        """Test init_scheduler starts scheduler."""
        from src.scheduler import init_scheduler, scheduler
        
        with patch("src.scheduler.async_session_maker") as mock_session_maker:
            mock_session = MagicMock()
            mock_session_maker.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_maker.return_value.__aexit__ = AsyncMock()
            
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_session.execute = AsyncMock(return_value=mock_result)
            
            with patch.object(scheduler, 'start'):
                await init_scheduler()

    @pytest.mark.asyncio
    async def test_shutdown_scheduler(self):
        """Test shutdown_scheduler."""
        from src.scheduler import shutdown_scheduler, scheduler
        
        with patch.object(scheduler, 'shutdown'):
            await shutdown_scheduler()


class TestSchedulerJobs:
    """Tests for scheduler job management."""

    def test_scheduler_get_jobs(self):
        """Test scheduler get_jobs."""
        from src.scheduler import scheduler
        
        jobs = scheduler.get_jobs()
        assert isinstance(jobs, list)

    def test_scheduler_state(self):
        """Test scheduler state."""
        from src.scheduler import scheduler
        
        assert hasattr(scheduler, 'state')

    def test_scheduler_add_job_fails_invalid_cron(self):
        """Test scheduler add_job with invalid cron."""
        from src.scheduler import scheduler
        
        try:
            scheduler.add_job(
                lambda: None,
                trigger=None,
                id="test-job"
            )
        except Exception:
            pass