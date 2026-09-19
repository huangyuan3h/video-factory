"""Dense key-point script / chapter-relevant material tests for ``type=book``.

Covers the two user-facing fixes:
1. Book episodes always take the dense "要点压缩" rewrite + script prompt.
2. Book material fetching prefers images and never falls back to the global
   finance/news ``FALLBACK_KEYWORDS`` when a keyword does not translate.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.task_logger import TaskLogger
from src.services import book_script
from src.services import video_service as vs
from src.services.material.material_fetcher import (
    BOOK_FALLBACK_KEYWORDS,
    FALLBACK_KEYWORDS,
    MaterialFetcher,
    book_fallback_keywords,
    derive_book_search_terms,
)


def _book_request(**overrides):
    base = dict(
        content_type="book",
        title="第一章 泡沫经济的形成",
        text_content="泡沫经济是平成日本经济史的开端。",
        system_prompt="",
        rewrite_content=False,
        voice="zh-CN-XiaoxiaoNeural",
        resolution_width=1080,
        resolution_height=1920,
        background_source="online",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _seg(text="要点", keywords=None, duration=20):
    seg = MagicMock()
    seg.text = text
    seg.keywords = keywords if keywords is not None else ["泡沫经济", "日元升值"]
    seg.duration_estimate = duration
    return seg


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #


def test_dense_prompts_are_chinese_key_point_prompts():
    assert "要点" in book_script.book_dense_rewrite_prompt()
    assert "3-5" in book_script.book_dense_rewrite_prompt()
    assert "JSON" in book_script.book_dense_script_prompt()
    assert "45-90" in book_script.book_dense_script_prompt()
    # Helpers return the constants (single source of truth).
    assert book_script.book_dense_rewrite_prompt() == book_script.BOOK_DENSE_REWRITE_PROMPT
    assert book_script.book_dense_script_prompt() == book_script.BOOK_DENSE_SCRIPT_PROMPT


# --------------------------------------------------------------------------- #
# Forced dense rewrite
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_book_rewrite_forced_even_when_rewrite_flag_false(tmp_path):
    tl = TaskLogger("book-rw-force", tmp_path)
    ai = MagicMock()
    ai.optimize_content = AsyncMock(return_value="压缩后的要点")
    req = _book_request(rewrite_content=False)

    await vs._maybe_rewrite_content(ai, req, tl)

    ai.optimize_content.assert_awaited_once()
    kwargs = ai.optimize_content.await_args.kwargs
    assert kwargs["system_prompt"] == book_script.BOOK_DENSE_REWRITE_PROMPT
    assert "第一章 泡沫经济的形成" in kwargs["user_prompt"]
    assert req.content == "压缩后的要点"
    assert tl.status["book_dense"] is True


@pytest.mark.asyncio
async def test_book_rewrite_explicit_prompt_wins(tmp_path):
    tl = TaskLogger("book-rw-explicit", tmp_path)
    ai = MagicMock()
    ai.optimize_content = AsyncMock(return_value="用户自定义")
    req = _book_request(rewrite_content=False, rewrite_prompt="只用三句话")

    await vs._maybe_rewrite_content(ai, req, tl)

    assert ai.optimize_content.await_args.kwargs["system_prompt"] == "只用三句话"


@pytest.mark.asyncio
async def test_non_book_rewrite_still_respects_flag(tmp_path):
    tl = TaskLogger("general-rw", tmp_path)
    ai = MagicMock()
    ai.optimize_content = AsyncMock()
    req = _book_request(content_type="general", rewrite_content=False)

    await vs._maybe_rewrite_content(ai, req, tl)

    ai.optimize_content.assert_not_awaited()


# --------------------------------------------------------------------------- #
# Dense script prompt
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_generate_script_book_uses_dense_prompt(tmp_path):
    tl = TaskLogger("book-script", tmp_path)
    script = MagicMock()
    script.model_dump.return_value = {"segments": []}
    script.segments = []
    ai = MagicMock()
    ai.generate_script = AsyncMock(return_value=script)

    await vs._generate_script(ai, _book_request(), tl)

    kwargs = ai.generate_script.await_args.kwargs
    assert kwargs["system_prompt"] == book_script.BOOK_DENSE_SCRIPT_PROMPT
    assert tl.status["book_dense"] is True


@pytest.mark.asyncio
async def test_generate_script_book_keeps_user_system_prompt(tmp_path):
    tl = TaskLogger("book-script-user", tmp_path)
    script = MagicMock()
    script.model_dump.return_value = {"segments": []}
    script.segments = []
    ai = MagicMock()
    ai.generate_script = AsyncMock(return_value=script)

    await vs._generate_script(ai, _book_request(system_prompt="我的风格"), tl)

    assert ai.generate_script.await_args.kwargs["system_prompt"] == "我的风格"


@pytest.mark.asyncio
async def test_init_task_marks_book_dense(tmp_path):
    tl = TaskLogger("book-init", tmp_path)
    await vs._init_task(tl, _book_request())
    assert tl.status["book_dense"] is True
    assert tl.status["type"] == "book"


# --------------------------------------------------------------------------- #
# Search term derivation
# --------------------------------------------------------------------------- #


def test_derive_book_search_terms_maps_heisei_domain():
    terms = derive_book_search_terms(["泡沫经济", "日元升值"], "失去的三十年")
    assert "bubble economy" in terms
    assert "yen appreciation" in terms
    assert "japan lost decades" in terms


def test_derive_book_search_terms_keeps_latin_title_tokens():
    terms = derive_book_search_terms([], "The Plaza Accord and Abenomics")
    assert any("plaza accord" in t for t in terms)
    assert "the plaza accord and abenomics" in terms


def test_book_fallback_keywords_tied_to_title_tokens():
    fallbacks = book_fallback_keywords("第一章 泡沫经济", ["日元"])
    assert "bubble economy" in fallbacks
    assert "japanese yen" in fallbacks


def test_book_fallback_keywords_neutral_when_unknown_domain():
    fallbacks = book_fallback_keywords("A Chapter With No CJK Tokens", [])
    assert fallbacks == list(BOOK_FALLBACK_KEYWORDS)
    assert not (set(fallbacks) & set(FALLBACK_KEYWORDS))


# --------------------------------------------------------------------------- #
# Material fetcher book mode
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_book_fetcher_untranslated_uses_book_fallback_not_finance():
    fetcher = MaterialFetcher(book_mode=True, book_title="第一章 泡沫经济")
    with patch.object(
        fetcher.pexels, "fetch_images", new_callable=AsyncMock, return_value=[]
    ) as mock_pexels, patch.object(
        fetcher.pixabay, "fetch_images", new_callable=AsyncMock, return_value=[]
    ):
        await fetcher.fetch_images(["完全未翻译的中文词"], count=1, source="pexels")

    assert mock_pexels.await_count >= 1
    queried = [
        " ".join(call.args[0]) if call.args else ""
        for call in mock_pexels.await_args_list
    ]
    joined = " ".join(queried)
    # Book-specific fallback terms are used...
    assert "bubble economy" in joined
    # ...and the global finance/news fallback is never used.
    for banned in ("stock market", "world news", "finance", "breaking news"):
        assert banned not in joined


@pytest.mark.asyncio
async def test_general_fetcher_still_uses_news_safe_fallback():
    fetcher = MaterialFetcher()
    with patch.object(
        fetcher.pexels, "fetch_images", new_callable=AsyncMock, return_value=[]
    ) as mock_pexels, patch.object(
        fetcher.pixabay, "fetch_images", new_callable=AsyncMock, return_value=[]
    ):
        await fetcher.fetch_images(["完全未翻译的中文词"], count=1, source="pexels")

    queried = [
        " ".join(call.args[0]) if call.args else ""
        for call in mock_pexels.await_args_list
    ]
    assert any("stock market" in q for q in queried)


@pytest.mark.asyncio
async def test_book_materials_prefer_images_and_title_aware(tmp_path):
    img = tmp_path / "i.jpg"
    img.write_bytes(b"x")
    fetcher = MagicMock()
    fetcher.fetch_images = AsyncMock(return_value=[img])
    fetcher.fetch_videos = AsyncMock()
    ctor = MagicMock(return_value=fetcher)
    req = _book_request()
    script = MagicMock()
    script.segments = [_seg(duration=20)]
    logger = TaskLogger("book-mat", tmp_path)

    with patch.object(vs, "get_general_settings", AsyncMock(return_value={})), patch.object(
        vs, "MaterialFetcher", ctor
    ), patch.object(vs.settings, "assets_dir", tmp_path):
        result = await vs._fetch_materials(script, req, logger)

    assert result == [img]
    assert ctor.call_args.kwargs["book_mode"] is True
    assert ctor.call_args.kwargs["book_title"] == "第一章 泡沫经济的形成"
    fetcher.fetch_images.assert_awaited_once()
    fetcher.fetch_videos.assert_not_called()
    assert req._materials_per_segment == [[img]]


@pytest.mark.asyncio
async def test_book_materials_falls_back_to_videos_then_gradient(tmp_path):
    tl = TaskLogger("book-mat-fallback", tmp_path)
    clip = tmp_path / "v.mp4"
    fetcher = MagicMock()
    fetcher.fetch_images = AsyncMock(return_value=[])
    fetcher.fetch_videos = AsyncMock(return_value=[clip])
    req = _book_request()
    script = MagicMock()
    script.segments = [_seg(duration=20)]

    with patch.object(vs, "get_general_settings", AsyncMock(return_value={})), patch.object(
        vs, "MaterialFetcher", MagicMock(return_value=fetcher)
    ), patch.object(vs.settings, "assets_dir", tmp_path):
        result = await vs._fetch_materials(script, req, tl)
    assert result == [clip]

    # Both empty -> gradient placeholder.
    fetcher.fetch_videos = AsyncMock(return_value=[])
    placeholder = MagicMock()

    with patch.object(vs, "get_general_settings", AsyncMock(return_value={})), patch.object(
        vs, "MaterialFetcher", MagicMock(return_value=fetcher)
    ), patch.object(vs.settings, "assets_dir", tmp_path), patch(
        "src.services.cover_service._create_gradient_background", return_value=placeholder
    ):
        result = await vs._fetch_materials(script, req, tl)
    assert result == [tmp_path / "images" / "placeholder_seg0.png"]


@pytest.mark.asyncio
async def test_book_materials_ignore_synthetic_source(tmp_path):
    tl = TaskLogger("book-mat-synth", tmp_path)
    img = tmp_path / "s.jpg"
    fetcher = MagicMock()
    fetcher.fetch_images = AsyncMock(return_value=[img])
    fetcher.fetch_videos = AsyncMock(return_value=[])
    req = _book_request(background_source="synthetic")
    script = MagicMock()
    script.segments = [_seg(duration=20)]

    with patch.object(vs, "get_general_settings", AsyncMock(return_value={})), patch.object(
        vs, "MaterialFetcher", MagicMock(return_value=fetcher)
    ), patch.object(vs.settings, "assets_dir", tmp_path):
        await vs._fetch_materials(script, req, tl)

    for call in fetcher.fetch_images.call_args_list:
        assert call.kwargs["source"] != "synthetic"
