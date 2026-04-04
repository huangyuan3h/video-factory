"""Full tests for scheduler module."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime


class TestSchedulerModule:
    """Tests for scheduler module."""

    def test_scheduler_imports(self):
        """Test scheduler imports."""
        from src.scheduler import scheduler, execute_task, add_task, remove_task
        from src.scheduler import update_task, trigger_task, init_scheduler, shutdown_scheduler
        
        assert scheduler is not None
        assert execute_task is not None
        assert add_task is not None
        assert remove_task is not None

    def test_scheduler_instance(self):
        """Test scheduler is AsyncIOScheduler."""
        from src.scheduler import scheduler
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        
        assert isinstance(scheduler, AsyncIOScheduler)

    @pytest.mark.asyncio
    async def test_add_task_disabled(self):
        """Test add_task with disabled task."""
        from src.scheduler import add_task
        
        task = MagicMock()
        task.enabled = False
        task.id = "test-id"
        task.name = "Test Task"
        task.schedule = "* * * * *"
        
        await add_task(task)
        
    @pytest.mark.asyncio
    async def test_remove_task_not_exists(self):
        """Test remove_task when job doesn't exist."""
        from src.scheduler import remove_task
        
        await remove_task("non-existent-id")

    @pytest.mark.asyncio
    async def test_update_task_disabled(self):
        """Test update_task with disabled task."""
        from src.scheduler import update_task
        
        task = MagicMock()
        task.id = "test-id"
        task.enabled = False
        
        await update_task(task)

    @pytest.mark.asyncio
    async def test_trigger_task(self):
        """Test trigger_task function."""
        from src.scheduler import trigger_task
        
        with patch("src.scheduler.execute_task", new_callable=AsyncMock):
            run_id = await trigger_task("test-task-id")
            assert run_id is not None
            assert len(run_id) == 16

    @pytest.mark.asyncio
    async def test_shutdown_scheduler(self):
        """Test shutdown_scheduler function."""
        from src.scheduler import shutdown_scheduler, scheduler
        
        with patch.object(scheduler, 'shutdown'):
            await shutdown_scheduler()

    @pytest.mark.asyncio
    async def test_execute_task_not_found(self):
        """Test execute_task when task not found."""
        from src.scheduler import execute_task
        
        with patch("src.scheduler.async_session_maker") as mock_session_maker:
            mock_session = MagicMock()
            mock_session_maker.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_maker.return_value.__aexit__ = AsyncMock()
            
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_session.execute = AsyncMock(return_value=mock_result)
            
            await execute_task("non-existent-id")

    @pytest.mark.asyncio
    async def test_init_scheduler(self):
        """Test init_scheduler function."""
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


class TestSchedulerJobs:
    """Tests for scheduler job management."""

    def test_scheduler_get_job(self):
        """Test scheduler get_job method."""
        from src.scheduler import scheduler
        
        job = scheduler.get_job("non-existent-job")
        assert job is None

    def test_scheduler_get_jobs(self):
        """Test scheduler get_jobs method."""
        from src.scheduler import scheduler
        
        jobs = scheduler.get_jobs()
        assert isinstance(jobs, list)

    @pytest.mark.asyncio
    async def test_add_task_with_cron(self):
        """Test add_task with valid cron expression."""
        from src.scheduler import add_task, scheduler
        
        task = MagicMock()
        task.enabled = True
        task.id = "cron-test-id"
        task.name = "Cron Task"
        task.schedule = "0 * * * *"
        
        await add_task(task)

    @pytest.mark.asyncio
    async def test_add_task_invalid_cron(self):
        """Test add_task with invalid cron expression."""
        from src.scheduler import add_task
        
        task = MagicMock()
        task.enabled = True
        task.id = "invalid-cron-id"
        task.name = "Invalid Cron Task"
        task.schedule = "invalid-cron"
        
        await add_task(task)


class TestSchedulerIntegration:
    """Integration tests for scheduler."""

    def test_scheduler_state(self):
        """Test scheduler state."""
        from src.scheduler import scheduler
        
        assert hasattr(scheduler, 'state')

    def test_scheduler_running(self):
        """Test scheduler is not running initially."""
        from src.scheduler import scheduler
        from apscheduler.schedulers.base import STATE_RUNNING
        
        assert scheduler.state != STATE_RUNNING

    def test_trigger_task_returns_run_id(self):
        """Test trigger_task returns valid run_id."""
        from src.scheduler import trigger_task
        import asyncio
        
        async def test():
            with patch("src.scheduler.execute_task", new_callable=AsyncMock):
                run_id = await trigger_task("test-id")
                assert run_id is not None
                assert len(run_id) == 16
                return run_id
        
        run_id1 = asyncio.run(test())
        run_id2 = asyncio.run(test())
        
        assert run_id1 != run_id2