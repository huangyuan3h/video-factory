"""Tests for the book -> series -> episode pipeline.

No real TTS/Pexels/DB is used: the session is faked and ``generate_video`` is
mocked so only splitting, persistence and route validation are exercised.
"""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.database import get_session
from src.models import Series
from src.routes import series as series_route
from src.services import book_service

BOOK = """第一章 起点
央行宣布降息，市场情绪回暖。这是第一章的正文内容，用于测试章节切分。
第二章 转折
亚太股市普遍上涨，科技板块领涨。这是第二章的正文内容。
第三章 终局
投资者开始重新评估风险，资金流向债券。这是第三章的正文内容。
"""

MARKDOWN_BOOK = """# Chapter One
First chapter body text.

# Chapter Two
Second chapter body text.

# Chapter Three
Third chapter body text.
"""


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


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(book_service.settings, "data_dir", tmp_path)
    session = _FakeSession()
    app = FastAPI()
    app.include_router(series_route.router, prefix="/api/series")

    async def _override_session():
        yield session

    app.dependency_overrides[get_session] = _override_session
    with TestClient(app) as c:
        c.session = session  # type: ignore[attr-defined]
        c.data_dir = tmp_path  # type: ignore[attr-defined]
        yield c


# --------------------------------------------------------------------------- #
# Splitter
# --------------------------------------------------------------------------- #

def test_split_book_on_chinese_chapter_headings():
    episodes = book_service.split_book(BOOK)
    assert [e["title"] for e in episodes] == ["第一章 起点", "第二章 转折", "第三章 终局"]
    assert [e["index"] for e in episodes] == [1, 2, 3]
    assert "央行宣布降息" in episodes[0]["content"]
    assert episodes[0]["char_count"] == len(episodes[0]["content"])


def test_split_book_on_markdown_headings():
    episodes = book_service.split_book(MARKDOWN_BOOK)
    assert len(episodes) == 3
    assert episodes[0]["title"] == "Chapter One"
    assert "First chapter body" in episodes[0]["content"]


def test_split_book_paragraph_fallback():
    text = "第一段内容。\n\n第二段内容。\n\n第三段内容。"
    episodes = book_service.split_book(text)
    assert len(episodes) >= 2
    assert all(e["content"] for e in episodes)


def test_split_book_trims_long_content_to_max_chars():
    long_body = "字" * 2000
    text = f"第一章 开始\n{long_body}\n第二章 结束\n短内容"
    episodes = book_service.split_book(text, max_chars=500)
    assert episodes[0]["char_count"] <= 500


def test_split_book_caps_episode_count():
    text = "\n".join(f"第{n}章 标题\n内容{n}" for n in ["一", "二", "三", "四", "五"])
    episodes = book_service.split_book(text, max_episodes=2)
    assert len(episodes) == 2


def test_split_book_empty_returns_empty():
    assert book_service.split_book("") == []
    assert book_service.split_book("   \n  ") == []


def test_decode_text_handles_utf8_bom_and_gbk():
    assert book_service.decode_text("第一章".encode("utf-8-sig")) == "第一章"
    assert book_service.decode_text("第一章".encode("gb18030")) == "第一章"


def test_save_and_load_episodes_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(book_service.settings, "data_dir", tmp_path)
    episodes = book_service.split_book(BOOK)
    path = book_service.save_episodes("my-book", episodes)
    assert path == tmp_path / "series" / "my-book" / "episodes.json"
    assert path.exists()
    assert book_service.load_episodes("my-book") == episodes
    assert book_service.load_episodes("missing") == []


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

def test_from_book_json_creates_series_and_episodes(client):
    res = client.post("/api/series/from-book", json={"title": "我的书", "text": BOOK})
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["name"] == "我的书"
    assert data["episode_count"] == 3
    assert len(data["episodes"]) == 3
    slug = data["slug"]
    sidecar = client.data_dir / "series" / slug / "episodes.json"
    assert sidecar.exists()


def test_import_book_json_into_existing_series(client):
    client.session.rows["s1"] = Series(id="s1", name="旧系列", slug="old-slug")
    res = client.post("/api/series/s1/import-book", json={"text": BOOK})
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["series_id"] == "s1"
    assert data["episode_count"] == 3
    assert book_service.load_episodes("old-slug")

    listed = client.get("/api/series/s1/episodes").json()["data"]
    assert listed["episode_count"] == 3


def test_import_book_multipart_txt(client):
    client.session.rows["s1"] = Series(id="s1", name="书", slug="book-slug")
    res = client.post(
        "/api/series/s1/import-book",
        files={"file": ("book.txt", BOOK.encode("utf-8"), "text/plain")},
    )
    assert res.status_code == 200
    assert res.json()["data"]["episode_count"] == 3


def test_import_book_rejects_unsupported_extension(client):
    client.session.rows["s1"] = Series(id="s1", name="书", slug="book-slug")
    res = client.post(
        "/api/series/s1/import-book",
        files={"file": ("book.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert res.status_code == 400


def test_import_book_empty_text_rejected(client):
    client.session.rows["s1"] = Series(id="s1", name="书", slug="book-slug")
    res = client.post("/api/series/s1/import-book", json={"text": "   "})
    assert res.status_code == 400


def test_import_book_unknown_series_404(client):
    res = client.post("/api/series/missing/import-book", json={"text": BOOK})
    assert res.status_code == 404


def test_generate_episodes_queues_general_portrait_tasks(client, monkeypatch):
    client.session.rows["s1"] = Series(id="s1", name="书", slug="book-slug")
    book_service.save_episodes("book-slug", book_service.split_book(BOOK))

    from src.routes import videos

    mock_generate = AsyncMock(
        return_value={"success": True, "data": {"id": "video-1", "task_dir": "/tmp/x"}}
    )
    with patch.object(videos, "generate_video", mock_generate):
        res = client.post("/api/series/s1/generate-episodes?limit=2")

    assert res.status_code == 200
    data = res.json()["data"]
    assert data["queued"] == 2
    assert mock_generate.await_count == 2
    for call in mock_generate.await_args_list:
        request = call.args[0]
        assert request.content_type == "general"
        assert request.series_id == "s1"
        assert request.background_source == "online"
        assert request.resolution == "portrait"
        assert request.content


def test_generate_episodes_default_limit_is_smoke_sized(client, monkeypatch):
    client.session.rows["s1"] = Series(id="s1", name="书", slug="book-slug")
    book_service.save_episodes("book-slug", book_service.split_book(BOOK))

    from src.routes import videos

    mock_generate = AsyncMock(
        return_value={"success": True, "data": {"id": "video-1", "task_dir": "/tmp/x"}}
    )
    with patch.object(videos, "generate_video", mock_generate):
        res = client.post("/api/series/s1/generate-episodes")

    assert res.json()["data"]["queued"] == 3
    assert mock_generate.await_count == 3


def test_generate_episodes_without_import_returns_400(client):
    client.session.rows["s1"] = Series(id="s1", name="书", slug="empty-slug")
    res = client.post("/api/series/s1/generate-episodes")
    assert res.status_code == 400


def test_generate_episodes_unknown_series_404(client):
    res = client.post("/api/series/missing/generate-episodes")
    assert res.status_code == 404
