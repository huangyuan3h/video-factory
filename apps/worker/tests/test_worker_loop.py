"""Tests for the worker poll loop and entrypoint."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src import worker as worker_mod


@pytest.mark.asyncio
async def test_poll_loop_handles_jobs_then_exits():
    jobs = [
        {"task_id": "j1", "task_dir": "/tmp/j1", "request": {"title": "t", "content": "c"}, "backend": "db"},
        {"task_id": "j2", "task_dir": "/tmp/j2", "request": {"title": "t", "content": "c"}, "backend": "redis"},
    ]
    calls = {"n": 0}

    async def fake_claim(timeout=5):
        if calls["n"] >= len(jobs):
            raise KeyboardInterrupt
        job = jobs[calls["n"]]
        calls["n"] += 1
        return job

    handler = AsyncMock(side_effect=[RuntimeError("boom"), None])
    mark = AsyncMock()

    with patch.object(worker_mod, "init_db", AsyncMock()), patch.object(
        worker_mod, "claim_next_job", fake_claim
    ), patch.object(worker_mod, "_handle_job", handler), patch.object(
        worker_mod, "mark_job", mark
    ), patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(KeyboardInterrupt):
            await worker_mod._poll_loop()

    assert handler.await_count == 2
    # only the DB job gets its status persisted on failure
    mark.assert_awaited_once()
    assert mark.await_args.args[0] == "j1"


def test_main_handles_keyboard_interrupt():
    with patch.object(worker_mod, "_poll_loop", MagicMock(return_value=None)), patch.object(
        worker_mod.asyncio, "run", side_effect=KeyboardInterrupt
    ):
        worker_mod.main()  # should swallow KeyboardInterrupt
