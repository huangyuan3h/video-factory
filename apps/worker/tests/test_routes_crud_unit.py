"""Unit tests for DB-backed CRUD routes, synthetic routes, and the AI client.

Covers:
- src/routes/ai_settings.py
- src/routes/general_settings.py
- src/routes/runs.py
- src/routes/sources.py
- src/routes/system_prompts.py
- src/routes/tasks.py
- src/routes/synthetic.py
- src/core/ai_client.py

The route handlers are awaited directly against a real in-memory/file sqlite
async session so the whole handler body is exercised (no network, no real
LLM/ComfyUI).
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.database import Base
from src.models import AISetting, Run, Source, SystemPrompt, Task

# ---------------------------------------------------------------------------
# Shared async session fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def session(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'unit.db'}",
        poolclass=NullPool,
        future=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with maker() as db:
        yield db

    await engine.dispose()


def _assert_404(exc_info):
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# ai_settings
# ---------------------------------------------------------------------------


async def test_ai_settings_list_empty(session):
    from src.routes import ai_settings

    resp = await ai_settings.list_ai_settings(session)
    assert resp.success is True
    assert resp.data == []


async def test_ai_settings_get_active_none(session):
    from src.routes import ai_settings

    resp = await ai_settings.get_active_ai_setting(session)
    assert resp.success is False
    assert "No active" in resp.error


async def test_ai_settings_create_list_and_active(session):
    from src.routes import ai_settings
    from src.schemas.ai_setting import AISettingCreate

    created = await ai_settings.create_ai_setting(
        AISettingCreate(
            name="Primary",
            base_url="https://api.test.com/v1",
            api_key="sk-test",
            model_id="gpt-4o",
            temperature=0.5,
            max_tokens=2048,
        ),
        session,
    )
    assert created.success is True
    assert created.data.name == "Primary"
    assert created.data.is_active is True

    listed = await ai_settings.list_ai_settings(session)
    assert len(listed.data) == 1

    active = await ai_settings.get_active_ai_setting(session)
    assert active.success is True
    assert active.data.id == created.data.id


async def test_ai_settings_update(session):
    from src.routes import ai_settings
    from src.schemas.ai_setting import AISettingUpdate

    session.add(
        AISetting(id="ai1", name="Old", base_url="https://old/v1", api_key="k", model_id="m1")
    )
    await session.commit()

    resp = await ai_settings.update_ai_setting(
        "ai1",
        AISettingUpdate(name="New", model_id="m2", temperature=1.1),
        session,
    )
    assert resp.success is True
    assert resp.data.name == "New"
    assert resp.data.model_id == "m2"
    assert resp.data.temperature == 1.1


async def test_ai_settings_update_not_found(session):
    from src.routes import ai_settings
    from src.schemas.ai_setting import AISettingUpdate

    with pytest.raises(HTTPException) as err:
        await ai_settings.update_ai_setting("missing", AISettingUpdate(name="X"), session)
    _assert_404(err)


async def test_ai_settings_activate_deactivates_others(session):
    from src.routes import ai_settings

    session.add_all(
        [
            AISetting(id="a1", name="A", base_url="u", api_key="k", model_id="m", is_active=True),
            AISetting(id="a2", name="B", base_url="u", api_key="k", model_id="m", is_active=True),
        ]
    )
    await session.commit()

    resp = await ai_settings.activate_ai_setting("a1", session)
    assert resp.success is True
    assert resp.data.is_active is True

    listed = await ai_settings.list_ai_settings(session)
    by_id = {row.id: row for row in listed.data}
    assert by_id["a1"].is_active is True
    assert by_id["a2"].is_active is False


async def test_ai_settings_activate_not_found(session):
    from src.routes import ai_settings

    with pytest.raises(HTTPException) as err:
        await ai_settings.activate_ai_setting("nope", session)
    _assert_404(err)


async def test_ai_settings_delete(session):
    from src.routes import ai_settings

    session.add(AISetting(id="del1", name="D", base_url="u", api_key="k", model_id="m"))
    await session.commit()

    resp = await ai_settings.delete_ai_setting("del1", session)
    assert resp.success is True
    listed = await ai_settings.list_ai_settings(session)
    assert listed.data == []


async def test_ai_settings_delete_not_found(session):
    from src.routes import ai_settings

    with pytest.raises(HTTPException) as err:
        await ai_settings.delete_ai_setting("missing", session)
    _assert_404(err)


async def test_ai_settings_test_success(session):
    from src.routes import ai_settings

    session.add(
        AISetting(
            id="t1",
            name="T",
            base_url="https://api.test.com/v1",
            api_key="sk-test",
            model_id="gpt-4o",
        )
    )
    await session.commit()

    fake_response = MagicMock()
    fake_response.model = "gpt-4o"
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(return_value=fake_response)

    with patch("openai.AsyncOpenAI", return_value=fake_client):
        resp = await ai_settings.test_ai_setting("t1", session)

    assert resp.success is True
    assert resp.data["success"] is True
    assert resp.data["model"] == "gpt-4o"
    assert "latency_ms" in resp.data


async def test_ai_settings_test_failure(session):
    from src.routes import ai_settings

    session.add(AISetting(id="t2", name="T", base_url="u", api_key="k", model_id="m"))
    await session.commit()

    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("boom"))

    with patch("openai.AsyncOpenAI", return_value=fake_client):
        resp = await ai_settings.test_ai_setting("t2", session)

    assert resp.success is True
    assert resp.data["success"] is False
    assert "boom" in resp.data["error"]


async def test_ai_settings_test_not_found(session):
    from src.routes import ai_settings

    with pytest.raises(HTTPException) as err:
        await ai_settings.test_ai_setting("missing", session)
    _assert_404(err)


# ---------------------------------------------------------------------------
# general_settings
# ---------------------------------------------------------------------------


async def test_general_settings_get_creates_default(session):
    from src.routes import general_settings

    resp = await general_settings.get_general_setting(session)
    assert resp.success is True
    assert resp.data.output_dir == "./data/output"
    assert resp.data.video_resolution_width == 1080
    assert resp.data.video_resolution_height == 1920


async def test_general_settings_update_and_get(session):
    from src.routes import general_settings
    from src.schemas.general_setting import GeneralSettingUpdate

    await general_settings.get_general_setting(session)

    resp = await general_settings.update_general_setting(
        GeneralSettingUpdate(
            output_dir="/tmp/out", video_resolution_width=720, pexels_api_key="pk"
        ),
        session,
    )
    assert resp.success is True
    assert resp.data.output_dir == "/tmp/out"
    assert resp.data.video_resolution_width == 720
    assert resp.data.pexels_api_key == "pk"

    again = await general_settings.get_general_setting(session)
    assert again.data.output_dir == "/tmp/out"


# ---------------------------------------------------------------------------
# runs
# ---------------------------------------------------------------------------


async def test_runs_list_empty(session):
    from src.routes import runs

    resp = await runs.list_runs(None, None, 1, 20, session)
    assert resp.success is True
    assert resp.data.total == 0
    assert resp.data.items == []


async def test_runs_list_with_filters(session):
    from src.routes import runs

    session.add_all(
        [
            Task(id="task1", name="Task", source_id="s1", schedule="0 * * * *"),
            Run(id="r1", task_id="task1", status="completed"),
            Run(id="r2", task_id="task1", status="failed"),
        ]
    )
    await session.commit()

    all_runs = await runs.list_runs(None, None, 1, 20, session)
    assert all_runs.data.total == 2

    completed = await runs.list_runs(None, "completed", 1, 20, session)
    assert completed.data.total == 1
    assert completed.data.items[0].id == "r1"

    by_task = await runs.list_runs("task1", None, 1, 1, session)
    assert by_task.data.total == 2
    assert len(by_task.data.items) == 1


async def test_runs_get_with_published_to(session):
    from src.routes import runs

    session.add_all(
        [
            Task(id="task2", name="Task", source_id="s1", schedule="0 * * * *"),
            Run(
                id="r3",
                task_id="task2",
                status="completed",
                published_to=json.dumps(["youtube", "douyin"]),
            ),
        ]
    )
    await session.commit()

    resp = await runs.get_run("r3", session)
    assert resp.success is True
    assert resp.data.published_to == ["youtube", "douyin"]


async def test_runs_get_not_found(session):
    from src.routes import runs

    with pytest.raises(HTTPException) as err:
        await runs.get_run("missing", session)
    _assert_404(err)


# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------


async def test_sources_list_empty_and_filters(session):
    from src.routes import sources

    empty = await sources.list_sources(None, None, session)
    assert empty.data == []

    session.add_all(
        [
            Source(id="s1", type="rss", name="RSS", enabled=True),
            Source(id="s2", type="news_api", name="News", enabled=False),
        ]
    )
    await session.commit()

    assert len((await sources.list_sources(None, None, session)).data) == 2
    assert len((await sources.list_sources("rss", None, session)).data) == 1
    assert len((await sources.list_sources(None, False, session)).data) == 1


async def test_sources_create_get_list(session):
    from src.routes import sources
    from src.schemas.source import SourceCreate

    created = await sources.create_source(
        SourceCreate(
            type="rss",
            name="Feed",
            url="https://example.com/rss",
            keywords=["ai", "tech"],
        ),
        session,
    )
    assert created.success is True
    assert created.data.keywords == ["ai", "tech"]

    got = await sources.get_source(created.data.id, session)
    assert got.data.name == "Feed"

    assert len((await sources.list_sources(None, None, session)).data) == 1


async def test_sources_create_without_keywords(session):
    from src.routes import sources
    from src.schemas.source import SourceCreate

    created = await sources.create_source(SourceCreate(type="custom", name="Bare"), session)
    assert created.success is True
    assert created.data.keywords in (None, [])


async def test_sources_get_not_found(session):
    from src.routes import sources

    with pytest.raises(HTTPException) as err:
        await sources.get_source("missing", session)
    _assert_404(err)


async def test_sources_update_including_keywords(session):
    from src.routes import sources
    from src.schemas.source import SourceUpdate

    session.add(Source(id="sx", type="rss", name="Old", enabled=True))
    await session.commit()

    resp = await sources.update_source(
        "sx",
        SourceUpdate(name="Updated", keywords=["k1", "k2"], enabled=False),
        session,
    )
    assert resp.data.name == "Updated"
    assert resp.data.keywords == ["k1", "k2"]
    assert resp.data.enabled is False


async def test_sources_update_not_found(session):
    from src.routes import sources
    from src.schemas.source import SourceUpdate

    with pytest.raises(HTTPException) as err:
        await sources.update_source("missing", SourceUpdate(name="X"), session)
    _assert_404(err)


async def test_sources_delete(session):
    from src.routes import sources

    session.add(Source(id="sd", type="rss", name="ToDelete"))
    await session.commit()

    resp = await sources.delete_source("sd", session)
    assert resp.success is True
    assert (await sources.list_sources(None, None, session)).data == []


async def test_sources_delete_not_found(session):
    from src.routes import sources

    with pytest.raises(HTTPException) as err:
        await sources.delete_source("missing", session)
    _assert_404(err)


# ---------------------------------------------------------------------------
# system_prompts
# ---------------------------------------------------------------------------


async def test_system_prompts_list_empty(session):
    from src.routes import system_prompts

    resp = await system_prompts.list_system_prompts(session)
    assert resp.success is True
    assert resp.data == []


async def test_system_prompts_create_and_default_deactivates(session):
    from src.routes import system_prompts
    from src.schemas.system_prompt import SystemPromptCreate

    first = await system_prompts.create_system_prompt(
        SystemPromptCreate(name="P1", content="c1", is_default=True), session
    )
    assert first.data.is_default is True

    second = await system_prompts.create_system_prompt(
        SystemPromptCreate(name="P2", content="c2", is_default=True), session
    )
    assert second.data.is_default is True

    listed = await system_prompts.list_system_prompts(session)
    by_id = {p.id: p for p in listed.data}
    assert by_id[first.data.id].is_default is False
    assert by_id[second.data.id].is_default is True


async def test_system_prompts_update_and_default_deactivates(session):
    from src.routes import system_prompts
    from src.schemas.system_prompt import SystemPromptUpdate

    session.add_all(
        [
            SystemPrompt(id="p1", name="P1", content="c1", is_default=True),
            SystemPrompt(id="p2", name="P2", content="c2", is_default=False),
        ]
    )
    await session.commit()

    resp = await system_prompts.update_system_prompt(
        "p2", SystemPromptUpdate(content="new", is_default=True), session
    )
    assert resp.data.content == "new"

    listed = await system_prompts.list_system_prompts(session)
    by_id = {p.id: p for p in listed.data}
    assert by_id["p1"].is_default is False
    assert by_id["p2"].is_default is True


async def test_system_prompts_update_not_found(session):
    from src.routes import system_prompts
    from src.schemas.system_prompt import SystemPromptUpdate

    with pytest.raises(HTTPException) as err:
        await system_prompts.update_system_prompt(
            "missing", SystemPromptUpdate(name="X"), session
        )
    _assert_404(err)


async def test_system_prompts_set_default(session):
    from src.routes import system_prompts

    session.add_all(
        [
            SystemPrompt(id="d1", name="D1", content="c", is_default=True),
            SystemPrompt(id="d2", name="D2", content="c", is_default=False),
        ]
    )
    await session.commit()

    resp = await system_prompts.set_default_system_prompt("d2", session)
    assert resp.data.is_default is True

    listed = await system_prompts.list_system_prompts(session)
    by_id = {p.id: p for p in listed.data}
    assert by_id["d1"].is_default is False
    assert by_id["d2"].is_default is True


async def test_system_prompts_set_default_not_found(session):
    from src.routes import system_prompts

    with pytest.raises(HTTPException) as err:
        await system_prompts.set_default_system_prompt("missing", session)
    _assert_404(err)


async def test_system_prompts_delete(session):
    from src.routes import system_prompts

    session.add(SystemPrompt(id="pd", name="PD", content="c"))
    await session.commit()

    resp = await system_prompts.delete_system_prompt("pd", session)
    assert resp.success is True
    assert (await system_prompts.list_system_prompts(session)).data == []


async def test_system_prompts_delete_not_found(session):
    from src.routes import system_prompts

    with pytest.raises(HTTPException) as err:
        await system_prompts.delete_system_prompt("missing", session)
    _assert_404(err)


# ---------------------------------------------------------------------------
# tasks
# ---------------------------------------------------------------------------


async def test_tasks_list_empty_and_filter(session):
    from src.routes import tasks

    assert (await tasks.list_tasks(None, session)).data == []

    session.add_all(
        [
            Task(id="t1", name="T1", source_id="s1", schedule="* * * * *", enabled=True),
            Task(id="t2", name="T2", source_id="s1", schedule="* * * * *", enabled=False),
        ]
    )
    await session.commit()

    assert len((await tasks.list_tasks(None, session)).data) == 2
    assert len((await tasks.list_tasks(False, session)).data) == 1


async def test_tasks_create_schedules(session):
    from src.routes import tasks as tasks_route
    from src.schemas.task import TaskCreate

    with patch.object(tasks_route, "schedule_add_task", new=AsyncMock()) as mock_add:
        resp = await tasks_route.create_task(
            TaskCreate(name="New", source_id="s1", schedule="0 8 * * *"), session
        )
    assert resp.success is True
    assert resp.data.name == "New"
    mock_add.assert_awaited_once()


async def test_tasks_get_not_found(session):
    from src.routes import tasks

    with pytest.raises(HTTPException) as err:
        await tasks.get_task("missing", session)
    _assert_404(err)


async def test_tasks_get(session):
    from src.routes import tasks

    session.add(Task(id="tg", name="Get", source_id="s1", schedule="0 * * * *"))
    await session.commit()

    resp = await tasks.get_task("tg", session)
    assert resp.success is True
    assert resp.data.name == "Get"


async def test_tasks_update_schedules(session):
    from src.routes import tasks as tasks_route
    from src.schemas.task import TaskUpdate

    session.add(Task(id="tu", name="Old", source_id="s1", schedule="0 * * * *"))
    await session.commit()

    with patch.object(
        tasks_route, "schedule_update_task", new=AsyncMock()
    ) as mock_update:
        resp = await tasks_route.update_task(
            "tu", TaskUpdate(name="New", enabled=False), session
        )
    assert resp.data.name == "New"
    assert resp.data.enabled is False
    mock_update.assert_awaited_once()


async def test_tasks_update_not_found(session):
    from src.routes import tasks as tasks_route
    from src.schemas.task import TaskUpdate

    with pytest.raises(HTTPException) as err:
        await tasks_route.update_task("missing", TaskUpdate(name="X"), session)
    _assert_404(err)


async def test_tasks_delete_schedules(session):
    from src.routes import tasks as tasks_route

    session.add(Task(id="td", name="ToDelete", source_id="s1", schedule="0 * * * *"))
    await session.commit()

    with patch.object(
        tasks_route, "schedule_remove_task", new=AsyncMock()
    ) as mock_remove:
        resp = await tasks_route.delete_task("td", session)
    assert resp.success is True
    mock_remove.assert_awaited_once_with("td")
    assert (await tasks_route.list_tasks(None, session)).data == []


async def test_tasks_delete_not_found(session):
    from src.routes import tasks

    with pytest.raises(HTTPException) as err:
        await tasks.delete_task("missing", session)
    _assert_404(err)


async def test_tasks_run_now(session):
    from src.routes import tasks as tasks_route

    session.add(Task(id="tr", name="Run", source_id="s1", schedule="0 * * * *"))
    await session.commit()

    with patch.object(
        tasks_route, "schedule_trigger_task", new=AsyncMock(return_value="run-42")
    ) as mock_trigger:
        resp = await tasks_route.run_task_now("tr", session)
    assert resp.success is True
    assert resp.data["run_id"] == "run-42"
    mock_trigger.assert_awaited_once_with("tr")


async def test_tasks_run_not_found(session):
    from src.routes import tasks

    with pytest.raises(HTTPException) as err:
        await tasks.run_task_now("missing", session)
    _assert_404(err)


# ---------------------------------------------------------------------------
# synthetic
# ---------------------------------------------------------------------------


async def test_synthetic_status_variants():
    from src.routes import synthetic

    with patch.object(synthetic, "is_enabled", return_value=False), patch.object(
        synthetic, "is_available", return_value=False
    ):
        body = await synthetic.status()
    assert body["enabled"] is False
    assert "disabled" in body["hint"]

    with patch.object(synthetic, "is_enabled", return_value=True), patch.object(
        synthetic, "is_available", return_value=True
    ):
        body = await synthetic.status()
    assert body["hint"] == "ComfyUI reachable"

    with patch.object(synthetic, "is_enabled", return_value=True), patch.object(
        synthetic, "is_available", return_value=False
    ):
        body = await synthetic.status()
    assert body["available"] is False
    assert "fallback" in body["hint"]


async def test_synthetic_generate_disabled_409():
    from src.routes import synthetic

    with patch.object(synthetic, "is_enabled", return_value=False):
        with pytest.raises(HTTPException) as err:
            await synthetic.generate(synthetic.SyntheticRequest(prompt="a cat"))
    assert err.value.status_code == 409


async def test_synthetic_generate_success(tmp_path):
    from src.routes import synthetic

    png = tmp_path / "out.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    with patch.object(synthetic, "is_enabled", return_value=True), patch.object(
        synthetic, "generate_image", new=AsyncMock(return_value=png)
    ):
        response = await synthetic.generate(
            synthetic.SyntheticRequest(prompt="a cat", width=512, height=512)
        )
    assert response.media_type == "image/png"
    assert response.path == png


async def test_synthetic_generate_failure_503():
    from src.routes import synthetic

    with patch.object(synthetic, "is_enabled", return_value=True), patch.object(
        synthetic, "generate_image", new=AsyncMock(return_value=None)
    ):
        with pytest.raises(HTTPException) as err:
            await synthetic.generate(synthetic.SyntheticRequest(prompt="a cat"))
    assert err.value.status_code == 503


async def test_synthetic_batch_disabled_409():
    from src.routes import synthetic

    with patch.object(synthetic, "is_enabled", return_value=False):
        with pytest.raises(HTTPException) as err:
            await synthetic.batch(synthetic.BatchSyntheticRequest(prompts=["a"]))
    assert err.value.status_code == 409


async def test_synthetic_batch_success(tmp_path):
    from src.routes import synthetic

    paths = [tmp_path / "a.png", tmp_path / "b.png"]
    with patch.object(synthetic, "is_enabled", return_value=True), patch(
        "src.services.synthetic_service.generate_images",
        new=AsyncMock(return_value=paths),
    ):
        body = await synthetic.batch(synthetic.BatchSyntheticRequest(prompts=["a", "b"]))
    assert body["success"] is True
    assert body["count"] == 2


async def test_synthetic_batch_failure_503():
    from src.routes import synthetic

    with patch.object(synthetic, "is_enabled", return_value=True), patch(
        "src.services.synthetic_service.generate_images", new=AsyncMock(return_value=[])
    ):
        with pytest.raises(HTTPException) as err:
            await synthetic.batch(synthetic.BatchSyntheticRequest(prompts=["a"]))
    assert err.value.status_code == 503


async def test_synthetic_video_status_variants():
    from src.routes import synthetic

    with patch.object(synthetic, "video_is_enabled", return_value=False), patch.object(
        synthetic, "video_is_available", return_value=False
    ):
        body = await synthetic.video_status()
    assert body["enabled"] is False
    assert "disabled" in body["hint"]

    with patch.object(synthetic, "video_is_enabled", return_value=True), patch.object(
        synthetic, "video_is_available", return_value=True
    ):
        body = await synthetic.video_status()
    assert body["hint"] == "ComfyUI reachable"

    with patch.object(synthetic, "video_is_enabled", return_value=True), patch.object(
        synthetic, "video_is_available", return_value=False
    ):
        body = await synthetic.video_status()
    assert body["available"] is False
    assert body["hint"] == "ComfyUI not reachable"


async def test_synthetic_video_generate_disabled_409():
    from src.routes import synthetic

    with patch.object(synthetic, "video_is_enabled", return_value=False):
        with pytest.raises(HTTPException) as err:
            await synthetic.video_generate(synthetic.VideoRequest(prompt="clip"))
    assert err.value.status_code == 409


async def test_synthetic_video_generate_success(tmp_path):
    from src.routes import synthetic

    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"video-bytes")
    with patch.object(synthetic, "video_is_enabled", return_value=True), patch.object(
        synthetic, "generate_video_clip", new=AsyncMock(return_value=clip)
    ):
        response = await synthetic.video_generate(synthetic.VideoRequest(prompt="clip"))
    assert response.media_type == "video/mp4"


async def test_synthetic_video_generate_webm_media_type(tmp_path):
    from src.routes import synthetic

    clip = tmp_path / "clip.webm"
    clip.write_bytes(b"webm-bytes")
    with patch.object(synthetic, "video_is_enabled", return_value=True), patch.object(
        synthetic, "generate_video_clip", new=AsyncMock(return_value=clip)
    ):
        response = await synthetic.video_generate(synthetic.VideoRequest(prompt="clip"))
    assert response.media_type == "video/webm"


async def test_synthetic_video_generate_failure_503():
    from src.routes import synthetic

    with patch.object(synthetic, "video_is_enabled", return_value=True), patch.object(
        synthetic, "generate_video_clip", new=AsyncMock(return_value=None)
    ):
        with pytest.raises(HTTPException) as err:
            await synthetic.video_generate(synthetic.VideoRequest(prompt="clip"))
    assert err.value.status_code == 503


# ---------------------------------------------------------------------------
# ai_client
# ---------------------------------------------------------------------------


def _ai_client(model: str = "gpt-4o"):
    from src.core.ai_client import AIClient

    return AIClient(base_url="https://api.test.com/v1", api_key="sk-test", model=model)


def _response_with(content):
    response = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    response.choices = [choice]
    return response


async def test_ai_client_generate_script_strict_json():
    client = _ai_client()
    payload = {
        "title": "T",
        "segments": [{"text": "hello", "keywords": ["a"], "duration_estimate": 30}],
        "total_duration_estimate": 30,
    }
    fake = MagicMock()
    fake.chat.completions.create = AsyncMock(return_value=_response_with(json.dumps(payload)))
    client.client = fake

    script = await client.generate_script("content", title="T")
    assert script.title == "T"
    assert script.segments[0].text == "hello"
    assert script.total_duration_estimate == 30


async def test_ai_client_generate_script_code_fence():
    client = _ai_client()
    raw = '```json\n{"title": "Fenced", "segments": [], "total_duration_estimate": 1}\n```'
    fake = MagicMock()
    fake.chat.completions.create = AsyncMock(return_value=_response_with(raw))
    client.client = fake

    script = await client.generate_script("content")
    assert script.title == "Fenced"


async def test_ai_client_generate_script_lenient_trailing_comma():
    client = _ai_client()
    raw = '{"title": "Lenient", "segments": [], "total_duration_estimate": 5,}'
    fake = MagicMock()
    fake.chat.completions.create = AsyncMock(return_value=_response_with(raw))
    client.client = fake

    script = await client.generate_script("content")
    assert script.title == "Lenient"


async def test_ai_client_generate_script_lenient_write_failure():
    client = _ai_client()
    raw = '{"title": "NoWrite", "segments": [], "total_duration_estimate": 5,}'
    fake = MagicMock()
    fake.chat.completions.create = AsyncMock(return_value=_response_with(raw))
    client.client = fake

    with patch("pathlib.Path.write_text", side_effect=OSError("no tmp")):
        script = await client.generate_script("content")
    assert script.title == "NoWrite"


async def test_ai_client_generate_script_extracts_outermost_object():
    client = _ai_client()
    raw = 'sure! {"title": "Outer", "segments": [], "total_duration_estimate": 7} done'
    fake = MagicMock()
    fake.chat.completions.create = AsyncMock(return_value=_response_with(raw))
    client.client = fake

    script = await client.generate_script("content")
    assert script.title == "Outer"


async def test_ai_client_generate_script_unparseable_raises():
    client = _ai_client()
    fake = MagicMock()
    fake.chat.completions.create = AsyncMock(return_value=_response_with("not json at all"))
    client.client = fake

    with pytest.raises(Exception):
        await client.generate_script("content")


async def test_ai_client_generate_script_empty_content():
    client = _ai_client()
    fake = MagicMock()
    fake.chat.completions.create = AsyncMock(return_value=_response_with(None))
    client.client = fake

    script = await client.generate_script("content", title="Fallback")
    assert script.title == "Fallback"
    assert script.segments == []
    assert script.total_duration_estimate == 180


async def test_ai_client_generate_script_ling_model():
    client = _ai_client(model="ling-3")
    fake = MagicMock()
    fake.chat.completions.create = AsyncMock(
        return_value=_response_with(
            '{"title": "Ling", "segments": [], "total_duration_estimate": 9}'
        )
    )
    client.client = fake

    script = await client.generate_script("content")
    assert script.title == "Ling"
    kwargs = fake.chat.completions.create.await_args.kwargs
    assert "temperature" not in kwargs
    assert "response_format" not in kwargs


async def test_ai_client_summarize_success():
    client = _ai_client()
    fake = MagicMock()
    fake.chat.completions.create = AsyncMock(return_value=_response_with("摘要"))
    client.client = fake

    assert await client.summarize("long content") == "摘要"


async def test_ai_client_summarize_error_raises():
    client = _ai_client()
    fake = MagicMock()
    fake.chat.completions.create = AsyncMock(side_effect=RuntimeError("api down"))
    client.client = fake

    with pytest.raises(RuntimeError):
        await client.summarize("content")


async def test_ai_client_extract_keywords_success():
    client = _ai_client()
    fake = MagicMock()
    fake.chat.completions.create = AsyncMock(
        return_value=_response_with('{"keywords": ["a", "b"]}')
    )
    client.client = fake

    assert await client.extract_keywords("content") == ["a", "b"]


async def test_ai_client_extract_keywords_error_returns_empty():
    client = _ai_client()
    fake = MagicMock()
    fake.chat.completions.create = AsyncMock(side_effect=RuntimeError("nope"))
    client.client = fake

    assert await client.extract_keywords("content") == []


async def test_ai_client_optimize_content_custom_prompt():
    client = _ai_client()
    fake = MagicMock()
    fake.chat.completions.create = AsyncMock(return_value=_response_with("  重写后的内容  "))
    client.client = fake

    result = await client.optimize_content("原文", system_prompt=" rewrite this ")
    assert result == "重写后的内容"
    messages = fake.chat.completions.create.await_args.kwargs["messages"]
    assert messages[0]["content"] == "rewrite this"


async def test_ai_client_optimize_content_default_prompt_empty_returns_original():
    client = _ai_client()
    fake = MagicMock()
    fake.chat.completions.create = AsyncMock(return_value=_response_with(""))
    client.client = fake

    assert await client.optimize_content("原文") == "原文"


async def test_ai_client_optimize_content_exception_returns_original():
    client = _ai_client()
    fake = MagicMock()
    fake.chat.completions.create = AsyncMock(side_effect=RuntimeError("boom"))
    client.client = fake

    assert await client.optimize_content("原文") == "原文"


def test_ai_client_get_fallback_client_vercel():
    from src.core import ai_client as mod

    client = _ai_client()
    with patch.object(mod, "AsyncOpenAI", return_value=MagicMock()), patch.object(
        mod.settings, "vercel_gateway_api_key", "vk"
    ), patch.object(mod.settings, "vercel_api_key", None):
        fallback = client.get_fallback_client()
    assert fallback is not client
    assert fallback.model == "openai/gpt-4o-mini"
    assert fallback.base_url == mod.settings.vercel_gateway_url


def test_ai_client_get_fallback_client_deepseek():
    from src.core import ai_client as mod

    client = _ai_client()
    with patch.object(mod, "AsyncOpenAI", return_value=MagicMock()), patch.object(
        mod.settings, "vercel_gateway_api_key", None
    ), patch.object(mod.settings, "vercel_api_key", None), patch.object(
        mod.settings, "deepseek_api_key", "dk"
    ):
        fallback = client.get_fallback_client()
    assert fallback is not client
    assert fallback.model == mod.settings.deepseek_model


def test_ai_client_get_fallback_client_self():
    from src.core import ai_client as mod

    client = _ai_client()
    with patch.object(mod.settings, "vercel_gateway_api_key", None), patch.object(
        mod.settings, "vercel_api_key", None
    ), patch.object(mod.settings, "deepseek_api_key", None):
        assert client.get_fallback_client() is client
