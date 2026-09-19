"""Focused tests for the type=news pipeline (GNews articles + images).

All network calls are mocked; no real GNews/Pexels requests are made.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.sources.base import ContentItem


def _gnews_payload():
    return {
        "totalArticles": 2,
        "articles": [
            {
                "title": "央行宣布降息",
                "description": "央行今日宣布下调利率以刺激经济。",
                "content": "央行今日宣布下调利率……",
                "url": "https://news.example.com/a1",
                "image": "https://img.example.com/a1.jpg",
                "publishedAt": "2026-01-02T03:04:05Z",
                "source": {"name": "示例新闻", "url": "https://news.example.com"},
            },
            {
                "title": "亚太股市上涨",
                "description": "受降息影响，亚太股市普遍上涨。",
                "url": "https://news.example.com/a2",
                "image": "https://img.example.com/a2.png",
                "publishedAt": "2026-01-02T04:00:00Z",
                "source": "APAC Daily",
            },
        ],
    }


def _mock_response(json_data=None, content=b"", headers=None):
    resp = MagicMock()
    resp.json.return_value = json_data if json_data is not None else {}
    resp.content = content
    resp.headers = headers or {}
    resp.raise_for_status = MagicMock()
    return resp


# --------------------------------------------------------------------------- #
# NewsAPISource (GNews shape)
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_gnews_source_parses_image_and_string_source():
    from src.sources.news_api import NewsAPISource

    source = NewsAPISource(name="GNews", api_key="k", provider="gnews", country="cn", lang="zh")

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = _mock_response(json_data=_gnews_payload())
        items = await source.fetch(count=2)

    assert len(items) == 2
    assert items[0].image_url == "https://img.example.com/a1.jpg"
    assert items[0].source_name == "示例新闻"
    assert items[1].source_name == "APAC Daily"
    assert items[0].url == "https://news.example.com/a1"
    assert items[0].published_at is not None

    # GNews uses max/apikey and top-headlines without a query
    _, kwargs = mock_get.call_args
    assert kwargs["params"]["apikey"] == "k"
    assert kwargs["params"]["max"] == 2
    assert kwargs["params"]["lang"] == "zh"
    assert "/top-headlines" in mock_get.call_args[0][0]


@pytest.mark.asyncio
async def test_gnews_source_search_endpoint_and_query():
    from src.sources.news_api import NewsAPISource

    source = NewsAPISource(name="GNews", api_key="k", provider="gnews")

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = _mock_response(json_data=_gnews_payload())
        items = await source.search("央行 降息", count=5)

    assert items
    url = mock_get.call_args[0][0]
    assert "/search" in url
    assert mock_get.call_args[1]["params"]["q"] == "央行 降息"
    assert mock_get.call_args[1]["params"]["max"] == 5


@pytest.mark.asyncio
async def test_newsapi_provider_still_uses_header_and_page_size():
    from src.sources.news_api import NewsAPISource

    source = NewsAPISource(name="NewsAPI", api_key="k", provider="newsapi", country="us")

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = _mock_response(json_data={"articles": []})
        await source.fetch(count=7)

    assert mock_get.call_args[1]["headers"]["X-Api-Key"] == "k"
    assert mock_get.call_args[1]["params"]["pageSize"] == 7
    assert "/top-headlines" in mock_get.call_args[0][0]


# --------------------------------------------------------------------------- #
# Request model
# --------------------------------------------------------------------------- #

def test_news_request_allows_missing_content():
    from src.routes.videos import VideoGenerateRequest

    req = VideoGenerateRequest(type="news", news_query="科技")
    assert req.is_news() is True
    assert req.content_type == "news"
    assert req.text_content == ""


def test_news_request_accepts_camelcase_aliases():
    from src.routes.videos import VideoGenerateRequest

    req = VideoGenerateRequest(contentType="news", newsQuery="AI", newsMaxArticles=3)
    assert req.is_news() is True
    assert req.news_query == "AI"
    assert req.news_max_articles == 3


def test_general_request_still_requires_content():
    from src.routes.videos import VideoGenerateRequest

    with pytest.raises(ValueError):
        VideoGenerateRequest(title="Only title")


def test_news_request_requires_some_seed():
    from src.routes.videos import VideoGenerateRequest

    with pytest.raises(ValueError):
        VideoGenerateRequest(type="news")


# --------------------------------------------------------------------------- #
# news_service
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_load_articles_requires_api_key(monkeypatch):
    from src.config import settings
    from src.services import news_service

    monkeypatch.setattr(settings, "gnews_api_key", None)
    news_service.clear_news_cache()
    req = SimpleNamespace(news_provider="gnews", news_max_articles=3)

    with pytest.raises(ValueError):
        await news_service._load_articles(req, "x")


@pytest.mark.asyncio
async def test_download_article_images_saves_and_skips_failures(tmp_path):
    from src.services.news_service import download_article_images

    items = [
        ContentItem(title="a", content="", image_url="https://img.example.com/a.jpg"),
        ContentItem(title="b", content="", image_url="https://img.example.com/broken.png"),
        ContentItem(title="c", content="", image_url=None),
    ]

    first = _mock_response(content=b"JPEGDATA", headers={"content-type": "image/jpeg"})
    second = MagicMock()
    second.raise_for_status.side_effect = RuntimeError("404")

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [first, second]
        paths = await download_article_images(items, tmp_path)

    assert len(paths) == 1
    assert paths[0].exists()
    assert paths[0].read_bytes() == b"JPEGDATA"
    assert paths[0].parent == tmp_path / "news_images"


@pytest.mark.asyncio
async def test_download_article_images_sends_browser_headers_on_403_then_succeeds(tmp_path):
    from src.services.news_service import download_article_images

    items = [
        ContentItem(
            title="被拒的 VOA 图",
            content="",
            url="https://www.voanews.com/a/story",
            image_url="https://gdb.voanews.com/ABC.jpg",
        ),
        ContentItem(
            title="成功的图",
            content="",
            url="https://www.voanews.com/a/other",
            image_url="https://gdb.voanews.com/DEF.jpg",
        ),
    ]

    forbidden = MagicMock()
    forbidden.status_code = 403
    forbidden.raise_for_status.side_effect = RuntimeError("403 Forbidden")
    forbidden.content = b""

    ok = MagicMock()
    ok.status_code = 200
    ok.raise_for_status = MagicMock()
    ok.headers = {}  # no content-type -> magic-byte sniffing
    ok.content = b"\xff\xd8\xff\xe0JPEGDATA"

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [forbidden, ok]
        paths = await download_article_images(items, tmp_path)

    assert len(paths) == 1
    assert paths[0].suffix == ".jpg"
    assert paths[0].read_bytes() == b"\xff\xd8\xff\xe0JPEGDATA"
    assert mock_get.call_count == 2
    for call, item in zip(mock_get.call_args_list, items):
        headers = call.kwargs["headers"]
        assert "Mozilla/5.0" in headers["User-Agent"]
        assert headers["Accept"]
        assert headers["Accept-Language"]
        assert headers["Referer"] == item.url


@pytest.mark.asyncio
async def test_download_article_images_referer_falls_back_to_image_host(tmp_path):
    from src.services.news_service import download_article_images

    item = ContentItem(
        title="no article url",
        content="",
        url=None,
        image_url="https://gdb.voanews.com/ABC.jpg",
    )
    ok = MagicMock()
    ok.status_code = 200
    ok.raise_for_status = MagicMock()
    ok.headers = {"content-type": "image/png"}
    ok.content = b"PNGDATA"

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = ok
        paths = await download_article_images([item], tmp_path)

    assert len(paths) == 1
    assert mock_get.call_args.kwargs["headers"]["Referer"] == "https://gdb.voanews.com/"


@pytest.mark.asyncio
async def test_resolve_news_content_fills_title_content_and_metadata(tmp_path):
    from src.core.task_logger import TaskLogger
    from src.services import news_service

    news_service.clear_news_cache()
    items = [
        ContentItem(
            title="头条标题",
            content="头条描述",
            url="https://news.example.com/a1",
            image_url="https://img.example.com/a1.jpg",
            source_name="示例新闻",
        ),
        ContentItem(title="第二条", content="第二条描述", source_name="来源二"),
    ]
    req = SimpleNamespace(
        content_type="news",
        title=None,
        content=None,
        news_query="头条",
        news_provider="gnews",
        news_max_articles=2,
    )
    logger = TaskLogger("t-news", tmp_path)

    with patch.object(news_service, "_load_articles", AsyncMock(return_value=items)), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = _mock_response(content=b"PNG", headers={"content-type": "image/png"})
        meta = await news_service.resolve_news_content(req, tmp_path, logger)

    assert req.title == "头条标题"
    assert "头条描述" in req.content
    assert meta["source_name"] == "示例新闻"
    assert meta["source_url"] == "https://news.example.com/a1"
    assert meta["image_count"] == 1
    assert (tmp_path / "news_articles.json").exists()
    assert len(getattr(req, "_news_images")) == 1


@pytest.mark.asyncio
async def test_resolve_news_content_no_articles_uses_user_content(tmp_path):
    from src.core.task_logger import TaskLogger
    from src.services import news_service

    news_service.clear_news_cache()
    req = SimpleNamespace(
        content_type="news",
        title=None,
        content="用户提供的正文",
        news_query="x",
        news_provider="gnews",
        news_max_articles=2,
    )
    logger = TaskLogger("t-news2", tmp_path)

    with patch.object(news_service, "_load_articles", AsyncMock(return_value=[])):
        meta = await news_service.resolve_news_content(req, tmp_path, logger)

    assert meta["image_count"] == 0
    assert req.title == "用户提供的正文"
    assert getattr(req, "_news_images") == []


# --------------------------------------------------------------------------- #
# video_service news materials
# --------------------------------------------------------------------------- #

def _script():
    return SimpleNamespace(
        segments=[
            SimpleNamespace(text="s1", keywords=["金融"], duration_estimate=10),
            SimpleNamespace(text="s2", keywords=["科技"], duration_estimate=10),
        ]
    )


@pytest.mark.asyncio
async def test_fetch_news_materials_uses_article_images(tmp_path):
    from src.core.task_logger import TaskLogger
    from src.services import video_service

    img1 = tmp_path / "n1.jpg"
    img2 = tmp_path / "n2.jpg"
    img1.write_bytes(b"x")
    img2.write_bytes(b"x")

    req = SimpleNamespace(
        content_type="news",
        resolution_width=1920,
        resolution_height=1080,
        _news_images=[img1, img2],
    )
    logger = TaskLogger("t-mat", tmp_path)

    with patch.object(video_service, "MaterialFetcher") as mock_fetcher:
        flat = await video_service._fetch_news_materials(_script(), req, logger)

    assert flat == [img1, img2]
    assert getattr(req, "_materials_per_segment") == [[img1], [img2]]
    mock_fetcher.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_news_materials_falls_back_online_never_synthetic(tmp_path):
    from src.core.task_logger import TaskLogger
    from src.services import video_service

    fallback_img = tmp_path / "stock.jpg"
    fallback_img.write_bytes(b"x")

    req = SimpleNamespace(
        content_type="news",
        resolution_width=1920,
        resolution_height=1080,
        _news_images=[],
    )
    logger = TaskLogger("t-mat2", tmp_path)

    fetcher = MagicMock()
    fetcher.fetch_images = AsyncMock(return_value=[fallback_img])
    fetcher.fetch_videos = AsyncMock(return_value=[])

    with patch.object(video_service, "MaterialFetcher", return_value=fetcher), \
         patch.object(video_service, "get_general_settings", AsyncMock(return_value={})):
        flat = await video_service._fetch_news_materials(_script(), req, logger)

    # Two segments -> fallback image assigned once per segment.
    assert flat == [fallback_img, fallback_img]
    for call in fetcher.fetch_images.call_args_list:
        assert call.kwargs["source"] == "online"
    # synthetic helpers must not be invoked on the news path
    assert fetcher.fetch_videos.await_count == 0


# --------------------------------------------------------------------------- #
# Route + task metadata
# --------------------------------------------------------------------------- #

def test_generate_route_accepts_type_news():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.routes.videos import router, video_tasks

    app = FastAPI()
    app.include_router(router, prefix="/api/videos")
    client = TestClient(app)

    with patch("src.routes.videos.run_video_generation"):
        response = client.post("/api/videos/generate", json={"type": "news", "news_query": "央行"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["content_type"] == "news"
    task = video_tasks[data["id"]]
    assert task["content_type"] == "news"
    assert task["payload"]["content_type"] == "news"


def test_enrich_task_copies_source_metadata(tmp_path):
    import json

    from src.routes.videos import _enrich_task

    (tmp_path / "status.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "content_type": "news",
                "source_name": "示例新闻",
                "source_url": "https://news.example.com/a1",
            }
        ),
        encoding="utf-8",
    )

    enriched = _enrich_task({"id": "x", "task_dir": str(tmp_path)})
    assert enriched["content_type"] == "news"
    assert enriched["source_name"] == "示例新闻"
    assert enriched["source_url"] == "https://news.example.com/a1"
