"""Tests for the book -> series -> episode pipeline.

No real TTS/Pexels/DB is used: the session is faked and ``generate_video`` is
mocked so only splitting, persistence and route validation are exercised.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.database import get_session
from src.models import Series
from src.routes import series as series_route
from src.services import book_service

_FILLER = "补充正文内容。" * 40  # ~280 chars

BOOK = f"""第一章 起点
央行宣布降息，市场情绪回暖。这是第一章的正文内容，用于测试章节切分。{_FILLER}
第二章 转折
亚太股市普遍上涨，科技板块领涨。这是第二章的正文内容。{_FILLER}
第三章 终局
投资者开始重新评估风险，资金流向债券。这是第三章的正文内容。{_FILLER}
"""

MARKDOWN_BOOK = f"""# Chapter One
First chapter body text. {_FILLER}

# Chapter Two
Second chapter body text. {_FILLER}

# Chapter Three
Third chapter body text. {_FILLER}
"""


def _chapter_body(repeats: int = 80) -> str:
    return "正文内容。" * repeats


TOC_BOOK = (
    "目录\n"
    "第一章 央行困境 ........ 1\n"
    "第二章 失去的十年 ........ 20\n"
    "第三章 结构改革 ........ 45\n"
    "\n"
    "第一章 央行困境\n" + _chapter_body() + "\n\n"
    "第二章 失去的十年\n" + _chapter_body() + "\n\n"
    "第三章 结构改革\n" + _chapter_body() + "\n\n"
    "T a b l e  o f  C o n t e n t s\n"
    "第一章 央行困境\n"
    "第二章 失去的十年\n"
    "第三章 结构改革\n"
)


def _make_pdf(text: str) -> bytes:
    """Build a tiny single-page PDF containing ``text`` (real pypdf output)."""
    import io

    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    buf = io.BytesIO()
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(buf)
    return buf.getvalue()


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


def test_split_book_skips_toc_uses_real_chapter_bodies():
    episodes = book_service.split_book(TOC_BOOK)
    assert [e["title"] for e in episodes] == ["第一章 央行困境", "第二章 失去的十年", "第三章 结构改革"]
    for episode in episodes:
        assert episode["char_count"] > 200
        assert "正文内容" in episode["content"]


def test_split_book_does_not_treat_inline_sentences_as_headings():
    text = (
        "第一章 开端\n"
        "第一章是本书的引言部分，这里讲了很多背景，但这不是标题。\n"
        + _chapter_body() + "\n"
        "第二章 发展\n" + _chapter_body()
    )
    episodes = book_service.split_book(text)
    assert [e["title"] for e in episodes] == ["第一章 开端", "第二章 发展"]


def test_split_book_merges_outline_like_sections():
    # A TOC-only entry (unique title, no real body) should not become a tiny episode.
    text = (
        "目录\n"
        "序章 概述\n"
        "第一章 真正开始\n" + _chapter_body() + "\n"
    )
    episodes = book_service.split_book(text)
    assert episodes
    assert all(e["char_count"] >= 160 for e in episodes)


def test_split_book_trims_long_content_to_max_chars():
    long_body = "字" * 2000
    text = f"第一章 开始\n{long_body}\n第二章 结束\n短内容"
    episodes = book_service.split_book(text, max_chars=500)
    assert episodes[0]["char_count"] <= 500


def test_split_book_caps_episode_count():
    text = "\n".join(f"第{n}章 标题\n内容{n}。{_FILLER}" for n in ["一", "二", "三", "四", "五"])
    episodes = book_service.split_book(text, max_episodes=2)
    assert len(episodes) == 2


def test_split_book_empty_returns_empty():
    assert book_service.split_book("") == []
    assert book_service.split_book("   \n  ") == []


def test_decode_text_handles_utf8_bom_and_gbk():
    assert book_service.decode_text("第一章".encode("utf-8-sig")) == "第一章"
    assert book_service.decode_text("第一章".encode("gb18030")) == "第一章"


def test_looks_like_pdf_detects_magic_bytes():
    assert book_service.looks_like_pdf(b"%PDF-1.7\n...")
    assert book_service.looks_like_pdf(b"  %PDF-1.4")
    assert not book_service.looks_like_pdf(b"plain text")
    assert not book_service.looks_like_pdf(None)


def test_decode_text_extracts_pdf_by_magic_and_filename():
    pdf = _make_pdf("Hello PDF Book")
    assert "Hello PDF Book" in book_service.decode_text(pdf)
    assert "Hello PDF Book" in book_service.decode_text(pdf, filename="book.pdf")


def test_extract_pdf_text_rejects_unreadable_bytes():
    with pytest.raises(ValueError):
        book_service.extract_pdf_text(b"%PDF-1.4 not really a pdf")
    with pytest.raises(ValueError):
        book_service.extract_pdf_text(b"%PDF-1.7\n")


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


def test_import_book_multipart_pdf(client):
    client.session.rows["s1"] = Series(id="s1", name="书", slug="book-slug")
    pdf = _make_pdf("Chapter One Body Chapter Two Body")
    res = client.post(
        "/api/series/s1/import-book",
        files={"file": ("book.pdf", pdf, "application/pdf")},
    )
    assert res.status_code == 200
    assert res.json()["data"]["episode_count"] >= 1


def test_import_book_rejects_unsupported_extension(client):
    client.session.rows["s1"] = Series(id="s1", name="书", slug="book-slug")
    res = client.post(
        "/api/series/s1/import-book",
        files={"file": ("book.docx", b"PK\x03\x04binary", "application/msword")},
    )
    assert res.status_code == 400


def test_import_book_invalid_pdf_rejected(client):
    client.session.rows["s1"] = Series(id="s1", name="书", slug="book-slug")
    res = client.post(
        "/api/series/s1/import-book",
        files={"file": ("book.pdf", b"%PDF-1.4 broken", "application/pdf")},
    )
    assert res.status_code == 400


def test_import_book_empty_text_rejected(client):
    client.session.rows["s1"] = Series(id="s1", name="书", slug="book-slug")
    res = client.post("/api/series/s1/import-book", json={"text": "   "})
    assert res.status_code == 400


def test_import_book_unknown_series_404(client):
    res = client.post("/api/series/missing/import-book", json={"text": BOOK})
    assert res.status_code == 404


def test_generate_episodes_queues_book_portrait_tasks(client, monkeypatch):
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
        assert request.content_type == "book"
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


# --------------------------------------------------------------------------- #
# type=book request + task metadata
# --------------------------------------------------------------------------- #

def test_book_request_is_book_and_defaults_to_online():
    from src.routes.videos import VideoGenerateRequest

    req = VideoGenerateRequest(type="book", title="第一章", content="正文内容")
    assert req.is_book() is True
    assert req.is_news() is False
    assert req.background_source == "online"


def test_book_request_respects_explicit_local_source():
    from src.routes.videos import VideoGenerateRequest

    req = VideoGenerateRequest(
        type="book", title="第一章", content="正文内容", background_source="local"
    )
    assert req.background_source == "local"


def test_book_request_requires_title_and_content_like_general():
    from src.routes.videos import VideoGenerateRequest

    with pytest.raises(ValueError):
        VideoGenerateRequest(type="book", title="只有标题")
    with pytest.raises(ValueError):
        VideoGenerateRequest(type="book", content="只有正文")


def test_generate_route_accepts_type_book():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.routes.videos import router, video_tasks

    app = FastAPI()
    app.include_router(router, prefix="/api/videos")
    client = TestClient(app)

    with patch("src.routes.videos.run_video_generation"):
        response = client.post(
            "/api/videos/generate",
            json={"type": "book", "title": "第一章", "content": "章节正文"},
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["content_type"] == "book"
    task = video_tasks[data["id"]]
    assert task["content_type"] == "book"
    assert task["type"] == "book"
    assert task["payload"]["content_type"] == "book"


@pytest.mark.asyncio
async def test_init_task_persists_content_type(tmp_path):
    from src.core.task_logger import TaskLogger
    from src.services import video_service

    task_logger = TaskLogger("t-book", tmp_path)
    req = SimpleNamespace(
        title="第一章",
        voice="zh-CN-XiaoxiaoNeural",
        resolution_width=1080,
        resolution_height=1920,
        content_type="book",
    )
    await video_service._init_task(task_logger, req)

    status = task_logger.get_status()
    assert status["content_type"] == "book"
    assert status["type"] == "book"


def test_enrich_task_surfaces_book_type(tmp_path):
    import json

    from src.routes.videos import _enrich_task

    (tmp_path / "status.json").write_text(
        json.dumps({"content_type": "book", "type": "book"}), encoding="utf-8"
    )
    enriched = _enrich_task({"id": "x", "task_dir": str(tmp_path)})
    assert enriched["content_type"] == "book"
    assert enriched["type"] == "book"


@pytest.mark.asyncio
async def test_book_materials_ignore_synthetic_source(tmp_path):
    from src.core.task_logger import TaskLogger
    from src.services import video_service

    img = tmp_path / "stock.jpg"
    img.write_bytes(b"x")

    req = SimpleNamespace(
        content_type="book",
        resolution_width=1080,
        resolution_height=1920,
        background_source="synthetic",
    )
    script = SimpleNamespace(
        segments=[SimpleNamespace(text="s", keywords=["金融"], duration_estimate=10)]
    )
    logger = TaskLogger("t-book-mat", tmp_path)

    fetcher = MagicMock()
    fetcher.fetch_videos = AsyncMock(return_value=[])
    fetcher.fetch_book_images = AsyncMock(return_value=[img])

    with patch.object(video_service, "MaterialFetcher", return_value=fetcher), \
         patch.object(video_service, "get_general_settings", AsyncMock(return_value={})):
        await video_service._fetch_materials(script, req, logger)

    for call in fetcher.fetch_videos.call_args_list:
        assert call.kwargs["source"] != "synthetic"
    for call in fetcher.fetch_book_images.call_args_list:
        assert call.kwargs["source"] != "synthetic"
