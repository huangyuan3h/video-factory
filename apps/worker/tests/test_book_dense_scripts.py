"""Dense key-point script / chapter-relevant material tests for ``type=book``.

Covers the two user-facing fixes:
1. Book episodes always take the dense "要点压缩" rewrite + script prompt.
2. Book material fetching prefers high-quality videos, falls back to images,
   and never falls back to the global finance/news ``FALLBACK_KEYWORDS`` when a
   keyword does not translate.
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
    to_visual_search_terms,
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
    assert "朋友" in book_script.book_dense_rewrite_prompt()
    assert "JSON" in book_script.book_dense_script_prompt()
    # Book episodes target a 3-4 minute spoken length (~180-240s).
    assert "180-240" in book_script.book_dense_script_prompt()
    assert "800-1000" in book_script.book_dense_script_prompt()
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
    # Second pass instructs a hard 800-1000 字 target.
    assert "800-1000" in ai.optimize_content.await_args.kwargs["system_prompt"]


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
    # Cover uses the same visual-safe language as the episode stills.
    assert not any("bubble" in t for t in keywords)
    assert "japan real estate boom" in keywords


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


def test_book_image_hold_default_is_five_seconds():
    assert settings.book_image_hold_seconds == 5.0
    assert settings.book_slide_transition_seconds == 0.5
    # Cover card stays at 3.0 unless there is a reason to change it.
    assert settings.book_cover_hold_seconds == 3.0


def test_derive_book_search_terms_maps_heisei_domain():
    terms = derive_book_search_terms(["泡沫经济", "日元升值"], "失去的三十年")
    # Visual-safe: the polysemous word "bubble" never reaches the stock API.
    assert not any("bubble" in t for t in terms)
    assert "japan real estate boom" in terms
    assert "yen appreciation" in terms
    assert "japan lost decades" in terms


def test_chapter_anchor_terms_stable_and_specific():
    anchor = chapter_anchor_terms("第一章 泡沫经济的形成")
    assert anchor
    # Visual-safe concrete theme; never the literal word "bubble".
    assert not any("bubble" in t for t in anchor)
    assert any("japan" in t or "tokyo" in t for t in anchor)
    # Specific domain terms lead; the bare generic "economy" does not.
    assert "economy" not in anchor


def test_build_book_segment_query_leads_with_segment_visuals():
    title = "第一章 泡沫经济的形成"
    anchor = chapter_anchor_terms(title)
    query = build_book_segment_query(title, ["泡沫经济", "日元升值"], anchor=anchor)
    # At most 3 focused, visual-safe terms.
    assert len(query) <= 3
    assert not any("bubble" in t for t in query)
    # Segment-specific visuals lead; the chapter theme is only a light bias.
    assert query[0] == "yen appreciation"
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


# --------------------------------------------------------------------------- #
# Visual-safe stock language (task-09)
# --------------------------------------------------------------------------- #


def test_to_visual_search_terms_never_emits_bubble_or_foam():
    safe = to_visual_search_terms(
        ["bubble economy", "asset bubble", "bubble burst", "foam", "burst", "plaza accord"]
    )
    joined = " ".join(safe).lower()
    for banned in ("bubble", "foam", "burst"):
        assert banned not in joined
    # Concrete, on-theme replacements survive...
    assert any("tokyo" in t or "japan" in t for t in safe)
    # ...and a specific good term is untouched.
    assert "plaza accord" in safe


def test_bubble_title_anchors_and_queries_avoid_bubble():
    title = "第七章 泡沫经济的崩溃"
    anchor = chapter_anchor_terms(title)
    assert anchor
    assert not any("bubble" in t.lower() for t in anchor)

    query = build_book_segment_query(title, ["广场协议", "日经"], anchor=anchor)
    joined = " ".join(query).lower()
    assert "bubble" not in joined
    # Plaza/Nikkei/Japan visuals carry the segment.
    assert any("plaza" in t or "nikkei" in t or "japan" in t or "tokyo" in t for t in query)


def test_build_book_segment_query_plaza_accord_gets_visuals_not_bubble():
    title = "泡沫经济的形成"
    query = build_book_segment_query(title, ["广场协议"], anchor=chapter_anchor_terms(title))
    assert not any("bubble" in t.lower() for t in query)
    assert any("plaza" in t or "tokyo" in t or "japan" in t for t in query)


def test_derive_book_search_terms_collapses_overlapping_cjk():
    # 「泡沫经济」 must not also emit the 泡沫 ("asset bubble") mapping.
    terms = derive_book_search_terms([], "泡沫经济的崩溃")
    assert terms == ["japan real estate boom"]


def test_book_fallback_keywords_tied_to_title_tokens():
    fallbacks = book_fallback_keywords("第一章 泡沫经济", ["日元"])
    assert not any("bubble" in t for t in fallbacks)
    assert "japan real estate boom" in fallbacks
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
    # Visual-safe book terms are used...
    assert "japan real estate boom" in joined
    assert "bubble" not in joined
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
async def test_book_materials_prefer_videos_and_title_aware(tmp_path):
    clip = tmp_path / "v.mp4"
    fetcher = MagicMock()
    fetcher.fetch_videos = AsyncMock(return_value=[clip])
    fetcher.fetch_book_images = AsyncMock()
    ctor = MagicMock(return_value=fetcher)
    req = _book_request()
    script = MagicMock()
    script.segments = [_seg(duration=20)]
    logger = TaskLogger("book-mat", tmp_path)

    with patch.object(vs, "get_general_settings", AsyncMock(return_value={})), patch.object(
        vs, "MaterialFetcher", ctor
    ), patch.object(vs.settings, "assets_dir", tmp_path):
        result = await vs._fetch_materials(script, req, logger)

    assert result == [clip]
    assert ctor.call_args.kwargs["book_mode"] is True
    assert ctor.call_args.kwargs["book_title"] == "第一章 泡沫经济的形成"
    fetcher.fetch_videos.assert_awaited_once()
    fetcher.fetch_book_images.assert_not_called()
    assert req._materials_per_segment == [[clip]]
    query = fetcher.fetch_videos.await_args.kwargs["keywords"]
    assert not any("bubble" in term for term in query)
    assert any("japan" in term or "tokyo" in term for term in query)


@pytest.mark.asyncio
async def test_book_materials_targets_five_second_cadence(tmp_path):
    img = tmp_path / "i.jpg"
    img.write_bytes(b"x")
    fetcher = MagicMock()
    fetcher.fetch_book_images = AsyncMock(return_value=[img])
    fetcher.fetch_videos = AsyncMock(return_value=[])
    req = _book_request()
    script = MagicMock()
    script.segments = [_seg(duration=30)]
    logger = TaskLogger("book-cadence", tmp_path)

    with patch.object(vs, "get_general_settings", AsyncMock(return_value={})), patch.object(
        vs, "MaterialFetcher", MagicMock(return_value=fetcher)
    ), patch.object(vs.settings, "assets_dir", tmp_path):
        await vs._fetch_materials(script, req, logger)

    # ~5s per still: a 30s segment asks for 6 images (was 8 at 4s).
    assert fetcher.fetch_book_images.await_args.kwargs["count"] == 6


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
    fetcher.fetch_videos = AsyncMock(return_value=[])
    req = _book_request()
    script = MagicMock()
    script.segments = [_seg(duration=30) for _ in range(12)]
    logger = TaskLogger("book-cap", tmp_path)

    with patch.object(vs, "get_general_settings", AsyncMock(return_value={})), patch.object(
        vs, "MaterialFetcher", MagicMock(return_value=fetcher)
    ), patch.object(vs.settings, "assets_dir", tmp_path):
        result = await vs._fetch_materials(script, req, logger)

    # 12 segments x 6 stills = 72 unique images, no repeats.
    assert len(result) == 72
    assert len({p.stem for p in result}) == 72
    assert all(len(seg) == 6 for seg in req._materials_per_segment)


@pytest.mark.asyncio
async def test_book_materials_prefer_videos_then_fall_back_to_images(tmp_path):
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
    fetcher.fetch_book_images.assert_not_called()

    fetcher.fetch_videos = AsyncMock(return_value=[])
    img = tmp_path / "still.jpg"
    fetcher.fetch_book_images = AsyncMock(return_value=[img])
    with patch.object(vs, "get_general_settings", AsyncMock(return_value={})), patch.object(
        vs, "MaterialFetcher", MagicMock(return_value=fetcher)
    ), patch.object(vs.settings, "assets_dir", tmp_path):
        result = await vs._fetch_materials(script, req, tl)
    assert result == [img]

    fetcher.fetch_videos = AsyncMock(return_value=[])
    fetcher.fetch_book_images = AsyncMock(return_value=[])
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
