"""Tests for the series CRUD routes."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from src.routes import series as series_route
from src.schemas import SeriesCreate, SeriesUpdate


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self):
        self.rows: dict = {}

    async def execute(self, stmt):
        return _Result(list(self.rows.values()))

    async def get(self, model, key):
        return self.rows.get(key)

    def add(self, obj):
        self.rows[obj.id] = obj

    async def commit(self):
        return None

    async def refresh(self, obj):
        now = datetime.now()
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = now

    async def delete(self, obj):
        self.rows.pop(obj.id, None)


def test_slugify_keeps_cjk():
    assert series_route.slugify("我的健康系列", "fallback") == "我的健康系列"
    assert series_route.slugify("My Health Series!", "fallback") == "my-health-series"
    assert series_route.slugify("   ", "series-abc") == "series-abc"
    assert series_route.slugify("a--b", "x") == "a-b"


@pytest.mark.asyncio
async def test_create_and_get_series():
    session = _FakeSession()
    with patch.object(series_route, "_unique_slug", AsyncMock(return_value="my-series")):
        res = await series_route.create_series(SeriesCreate(name="我的系列"), session)
    assert res.success is True
    sid = res.data.id
    assert res.data.slug == "my-series"

    got = await series_route.get_series(sid, session)
    assert got.data.name == "我的系列"


@pytest.mark.asyncio
async def test_list_series():
    session = _FakeSession()
    with patch.object(series_route, "_unique_slug", AsyncMock(return_value="s1")):
        await series_route.create_series(SeriesCreate(name="A"), session)
    res = await series_route.list_series(session)
    assert res.success is True
    assert len(res.data) == 1


@pytest.mark.asyncio
async def test_get_series_not_found():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await series_route.get_series("missing", _FakeSession())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_series():
    session = _FakeSession()
    with patch.object(series_route, "_unique_slug", AsyncMock(return_value="s1")):
        created = await series_route.create_series(SeriesCreate(name="A"), session)
    res = await series_route.update_series(created.data.id, SeriesUpdate(name="B"), session)
    assert res.data.name == "B"


@pytest.mark.asyncio
async def test_delete_series():
    session = _FakeSession()
    with patch.object(series_route, "_unique_slug", AsyncMock(return_value="s1")):
        created = await series_route.create_series(SeriesCreate(name="A"), session)
    res = await series_route.delete_series(created.data.id, session)
    assert res.success is True
    assert session.rows == {}


@pytest.mark.asyncio
async def test_unique_slug_appends_suffix():
    class _SeqSession:
        def __init__(self):
            self.calls = 0

        async def execute(self, stmt):
            self.calls += 1
            return _Result([object()] if self.calls == 1 else [])

    slug = await series_route._unique_slug(_SeqSession(), "my-series")
    assert slug == "my-series-2"
