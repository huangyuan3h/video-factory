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
from src.config import settings
from src.services.material.material_fetcher import (
    BOOK_FALLBACK_KEYWORDS,
    FALLBACK_KEYWORDS,
    MaterialFetcher,
    book_fallback_keywords,
    build_book_segment_query,
    chapter_anchor_terms,
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
    assert "6-12" in book_script.book_dense_rewrite_prompt()
    assert "JSON" in book_script.book_dense_script_prompt()
    # Book episodes target a 3-4 minute spoken length (~180-240s).
    assert "180-240" in book_script.book_dense_script_prompt()
    assert "6-12" in book_script.book_dense_script_prompt()
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
    script.model_dump.return_value = {"segments": [{"text": "要点"}]}
    script.segments = [_seg()]
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
    script.model_dump.return_value = {"segments": [{"text": "要点"}]}
    script.segments = [_seg()]
    ai = MagicMock()
    ai.generate_script = AsyncMock(return_value=script)

    await vs._generate_script(ai, _book_request(system_prompt="我的风格"), tl)

    assert ai.generate_script.await_args.kwargs["system_prompt"] == "我的风格"


# --------------------------------------------------------------------------- #
# Empty-segments fail-fast / retry guard
# --------------------------------------------------------------------------- #


def _empty_script():
    script = MagicMock()
    script.model_dump.return_value = {"title": "t", "segments": []}
    script.segments = []
    return script


@pytest.mark.asyncio
async def test_generate_script_retries_once_then_succeeds(tmp_path):
    tl = TaskLogger("book-script-retry", tmp_path)
    good = MagicMock()
    good.model_dump.return_value = {"segments": [{"text": "要点"}]}
    good.segments = [_seg()]
    ai = MagicMock()
    ai.generate_script = AsyncMock(side_effect=[_empty_script(), good])

    result = await vs._generate_script(ai, _book_request(), tl)

    assert result is good
    assert ai.generate_script.await_count == 2
    assert (tmp_path / "script.json").exists()


@pytest.mark.asyncio
async def test_generate_script_raises_after_two_empty_scripts(tmp_path):
    tl = TaskLogger("book-script-empty", tmp_path)
    ai = MagicMock()
    ai.generate_script = AsyncMock(return_value=_empty_script())

    with pytest.raises(ValueError, match="0 个段落"):
        await vs._generate_script(ai, _book_request(), tl)

    # Exactly one retry (two calls total), and the guard stops the pipeline
    # before any TTS/compose work.
    assert ai.generate_script.await_count == 2


# --------------------------------------------------------------------------- #
# Book rewrite second compression pass
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_book_rewrite_forces_second_pass_when_still_too_long(tmp_path):
    tl = TaskLogger("book-rw-double", tmp_path)
    long_text = "泡" * 2000
    short_text = "要" * 1200
    ai = MagicMock()
    ai.optimize_content = AsyncMock(side_effect=[long_text, short_text])
    req = _book_request(text_content="原" * 2500)

    await vs._maybe_rewrite_content(ai, req, tl)

    assert ai.optimize_content.await_count == 2
    assert req.content == short_text
    # Second pass instructs a hard 1000-1400 字 target.
    assert "1000-1400" in ai.optimize_content.await_args.kwargs["system_prompt"]


@pytest.mark.asyncio
async def test_book_rewrite_skips_second_pass_when_short(tmp_path):
    tl = TaskLogger("book-rw-once", tmp_path)
    ai = MagicMock()
    ai.optimize_content = AsyncMock(return_value="要" * 1200)
    req = _book_request(text_content="原" * 2500)

    await vs._maybe_rewrite_content(ai, req, tl)

    ai.optimize_content.assert_awaited_once()


# --------------------------------------------------------------------------- #
# Book cover keywords
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_generate_cover_book_uses_chapter_title_keywords(tmp_path):
    tl = TaskLogger("book-cover", tmp_path)
    cover = tmp_path / "cover.png"

    with patch.object(vs, "get_general_settings", AsyncMock(return_value={})), patch.object(
        vs, "generate_cover_image", AsyncMock(return_value=cover)
    ) as gen:
        result = await vs._generate_cover(_book_request(), tmp_path, tl)

    assert result == cover
    keywords = gen.await_args.kwargs["keywords"]
    assert keywords  # not the old empty [] -> "abstract"
    assert "bubble economy" in keywords


@pytest.mark.asyncio
async def test_generate_cover_general_keeps_empty_keywords(tmp_path):
    tl = TaskLogger("general-cover", tmp_path)
    cover = tmp_path / "cover.png"

    with patch.object(vs, "get_general_settings", AsyncMock(return_value={})), patch.object(
        vs, "generate_cover_image", AsyncMock(return_value=cover)
    ) as gen:
        await vs._generate_cover(_book_request(content_type="general"), tmp_path, tl)

    assert gen.await_args.kwargs["keywords"] == []


@pytest.mark.asyncio
async def test_init_task_marks_book_dense(tmp_path):
    tl = TaskLogger("book-init", tmp_path)
    await vs._init_task(tl, _book_request())
    assert tl.status["book_dense"] is True
    assert tl.status["type"] == "book"


# --------------------------------------------------------------------------- #
# Search term derivation
# --------------------------------------------------------------------------- #


def test_book_image_hold_default_is_four_seconds():
    assert settings.book_image_hold_seconds == 4.0
    assert settings.book_slide_transition_seconds == 0.5
    # Cover card stays at 3.0 unless there is a reason to change it.
    assert settings.book_cover_hold_seconds == 3.0


def test_derive_book_search_terms_maps_heisei_domain():
    terms = derive_book_search_terms(["泡沫经济", "日元升值"], "失去的三十年")
    assert "bubble economy" in terms
    assert "yen appreciation" in terms
    assert "japan lost decades" in terms


def test_chapter_anchor_terms_stable_and_specific():
    anchor = chapter_anchor_terms("第一章 泡沫经济的形成")
    assert anchor
    # Specific domain terms lead; the bare generic "economy" does not.
    assert "bubble economy" in anchor
    assert "economy" not in anchor


def test_build_book_segment_query_prepends_anchor_and_limits_terms():
    title = "第一章 泡沫经济的形成"
    anchor = chapter_anchor_terms(title)
    query = build_book_segment_query(title, ["泡沫经济", "日元升值"], anchor=anchor)
    # At most 3 focused terms; the chapter anchor always leads.
    assert len(query) <= 3
    assert query[: len(anchor)] == anchor
    # Generic filler is never the whole query when narrower terms exist.
    assert query != ["economy"]


def test_build_book_segment_query_generic_only_falls_back():
    # Unknown chapter + untranslated keyword -> nothing derived -> caller falls
    # back to book fallbacks rather than the finance/news list.
    query = build_book_segment_query("无标题", ["完全未翻译的中文词"])
    assert query == []
    assert not (set(book_fallback_keywords("无标题", ["完全未翻译的中文词"])) & set(FALLBACK_KEYWORDS))


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
    fetcher.fetch_book_images = AsyncMock(return_value=[img])
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
    fetcher.fetch_book_images.assert_awaited_once()
    fetcher.fetch_videos.assert_not_called()
    assert req._materials_per_segment == [[img]]
    # The query carries the chapter anchor so stills stay on theme.
    query = fetcher.fetch_book_images.await_args.kwargs["query"]
    assert "bubble economy" in query


@pytest.mark.asyncio
async def test_book_materials_targets_four_second_cadence(tmp_path):
    img = tmp_path / "i.jpg"
    img.write_bytes(b"x")
    fetcher = MagicMock()
    fetcher.fetch_book_images = AsyncMock(return_value=[img])
    fetcher.fetch_videos = AsyncMock()
    req = _book_request()
    script = MagicMock()
    script.segments = [_seg(duration=30)]
    logger = TaskLogger("book-cadence", tmp_path)

    with patch.object(vs, "get_general_settings", AsyncMock(return_value={})), patch.object(
        vs, "MaterialFetcher", MagicMock(return_value=fetcher)
    ), patch.object(vs.settings, "assets_dir", tmp_path):
        await vs._fetch_materials(script, req, logger)

    # ~4s per still: a 30s segment asks for 8 images (was 10 at 3s).
    assert fetcher.fetch_book_images.await_args.kwargs["count"] == 8


@pytest.mark.asyncio
async def test_book_materials_dedupe_skips_repeated_images(tmp_path):
    """Same file returned for every segment must only be used once."""
    img = tmp_path / "pexels_42.jpg"
    img.write_bytes(b"x")
    fetcher = MagicMock()
    fetcher.fetch_book_images = AsyncMock(return_value=[img])
    fetcher.fetch_videos = AsyncMock(return_value=[])
    req = _book_request()
    script = MagicMock()
    script.segments = [_seg(duration=20), _seg(duration=20)]
    logger = TaskLogger("book-dedupe", tmp_path)

    with patch.object(vs, "get_general_settings", AsyncMock(return_value={})), patch.object(
        vs, "MaterialFetcher", MagicMock(return_value=fetcher)
    ), patch.object(vs.settings, "assets_dir", tmp_path):
        result = await vs._fetch_materials(script, req, logger)

    # First segment keeps the still; the repeat is dropped, so the second
    # segment degrades to its own placeholder rather than reusing it.
    assert req._materials_per_segment[0] == [img]
    assert img not in req._materials_per_segment[1]
    assert any("跳过重复素材" in entry["message"] for entry in logger.logs)


@pytest.mark.asyncio
async def test_book_materials_keep_unique_images_for_long_episode(tmp_path):
    pool = []
    for j in range(200):
        p = tmp_path / f"i{j}.jpg"
        p.write_bytes(b"x")
        pool.append(p)

    def take(**kwargs):
        chunk = pool[: kwargs["count"]]
        del pool[: kwargs["count"]]
        return chunk

    fetcher = MagicMock()
    fetcher.fetch_book_images = AsyncMock(side_effect=take)
    fetcher.fetch_videos = AsyncMock()
    req = _book_request()
    script = MagicMock()
    script.segments = [_seg(duration=30) for _ in range(12)]
    logger = TaskLogger("book-cap", tmp_path)

    with patch.object(vs, "get_general_settings", AsyncMock(return_value={})), patch.object(
        vs, "MaterialFetcher", MagicMock(return_value=fetcher)
    ), patch.object(vs.settings, "assets_dir", tmp_path):
        result = await vs._fetch_materials(script, req, logger)

    # 12 segments x 8 stills = 96 unique images, no repeats.
    assert len(result) == 96
    assert len({p.stem for p in result}) == 96
    assert all(len(seg) == 8 for seg in req._materials_per_segment)


@pytest.mark.asyncio
async def test_book_materials_falls_back_to_videos_then_gradient(tmp_path):
    tl = TaskLogger("book-mat-fallback", tmp_path)
    clip = tmp_path / "v.mp4"
    fetcher = MagicMock()
    fetcher.fetch_book_images = AsyncMock(return_value=[])
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
    fetcher.fetch_book_images = AsyncMock(return_value=[img])
    fetcher.fetch_videos = AsyncMock(return_value=[])
    req = _book_request(background_source="synthetic")
    script = MagicMock()
    script.segments = [_seg(duration=20)]

    with patch.object(vs, "get_general_settings", AsyncMock(return_value={})), patch.object(
        vs, "MaterialFetcher", MagicMock(return_value=fetcher)
    ), patch.object(vs.settings, "assets_dir", tmp_path):
        await vs._fetch_materials(script, req, tl)

    for call in fetcher.fetch_book_images.call_args_list:
        assert call.kwargs["source"] != "synthetic"
