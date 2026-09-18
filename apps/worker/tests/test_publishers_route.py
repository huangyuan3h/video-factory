"""Tests for publisher account CRUD and publish routes."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.database import get_session
from src.models import PublisherAccount
from src.publishers.base import PublishResult
from src.routes import publishers as pub_route


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, rows=None):
        self.rows = rows or []

    async def execute(self, stmt):
        return _Result(self.rows)

    def add(self, obj):
        self.rows.append(obj)

    async def commit(self):
        return None

    async def refresh(self, obj):
        return None

    async def delete(self, obj):
        if obj in self.rows:
            self.rows.remove(obj)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(pub_route.router, prefix="/api/publishers")

    holder = {"session": _FakeSession()}

    async def override():
        yield holder["session"]

    app.dependency_overrides[get_session] = override
    test_client = TestClient(app)
    test_client.holder = holder
    return test_client


def test_list_publishers_empty(client):
    resp = client.get("/api/publishers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"] == []


def test_create_and_get_publisher(client):
    resp = client.post("/api/publishers", json={"platform": "youtube", "name": "My YT"})
    assert resp.status_code == 200
    created = resp.json()["data"]
    assert created["platform"] == "youtube"

    resp2 = client.get(f"/api/publishers/{created['id']}")
    assert resp2.status_code == 200
    assert resp2.json()["data"]["name"] == "My YT"


def test_get_publisher_not_found(client):
    resp = client.get("/api/publishers/missing")
    assert resp.status_code == 404


def test_update_publisher(client):
    acc = PublisherAccount(id="acc1", platform="douyin", name="Old")
    client.holder["session"].rows.append(acc)
    resp = client.put("/api/publishers/acc1", json={"name": "New", "enabled": False})
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "New"


def test_delete_publisher(client):
    acc = PublisherAccount(id="acc2", platform="xhs", name="Del")
    client.holder["session"].rows.append(acc)
    resp = client.delete("/api/publishers/acc2")
    assert resp.status_code == 200
    assert client.holder["session"].rows == []


def test_list_folders(client):
    acc = PublisherAccount(id="acc3", platform="youtube", name="YT")
    client.holder["session"].rows.append(acc)
    fake_pub = AsyncMock()
    fake_pub.list_folders = AsyncMock(return_value=[{"id": "p1", "name": "PL"}])
    with patch.object(pub_route, "get_publisher", return_value=fake_pub):
        resp = client.get("/api/publishers/acc3/folders")
    assert resp.status_code == 200
    assert resp.json()["data"] == [{"id": "p1", "name": "PL"}]


def test_publish_requires_existing_video(client, tmp_path):
    acc = PublisherAccount(id="acc4", platform="youtube", name="YT")
    client.holder["session"].rows.append(acc)
    resp = client.post("/api/publishers/acc4/publish", json={"video_path": "/nope/missing.mp4"})
    assert resp.status_code == 400


def test_publish_success(client, tmp_path):
    acc = PublisherAccount(id="acc5", platform="youtube", name="YT")
    client.holder["session"].rows.append(acc)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"data")

    fake_pub = AsyncMock()
    fake_pub.upload = AsyncMock(
        return_value=PublishResult(success=True, platform="YouTube", post_id="abc")
    )
    with patch.object(pub_route, "get_publisher", return_value=fake_pub):
        resp = client.post(
            "/api/publishers/acc5/publish", json={"video_path": str(video), "title": "T"}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["post_id"] == "abc"


def test_list_platforms_endpoint(client):
    resp = client.get("/api/publishers/platforms/list")
    assert resp.status_code == 200
    assert "youtube" in resp.json()["data"]
