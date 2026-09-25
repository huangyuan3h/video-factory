"""Presenter pen name: resolution, greeting enforcement, review + cover label."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from src.config import DEFAULT_TYPE_PRESETS, settings
from src.core.ai_client import GeneratedScript, ScriptSegment
from src.presets import resolve_presenter
from src.services import presenter as presenter_mod
from src.services import video_service as vs

NAME = "躺平的老黄"
GREETING = f"大家好，我是{NAME}。"


def _settings(**overrides):
    base = dict(presenter_enabled=True, presenter_name=NAME, type_presets=None)
    base.update(overrides)
    return SimpleNamespace(**base)


def _request(**overrides):
    base = dict(content_type="book", language="zh", presenter_name=None)
    base.update(overrides)
    return SimpleNamespace(**base)


# --------------------------------------------------------------------------- #
# resolve_presenter matrix
# --------------------------------------------------------------------------- #


def test_settings_defaults():
    assert settings.presenter_name == "躺平的老黄"
    assert settings.presenter_enabled is True
    assert DEFAULT_TYPE_PRESETS["book"]["presenter_intro"] is True
    assert DEFAULT_TYPE_PRESETS["indicator"]["presenter_intro"] is True
    assert DEFAULT_TYPE_PRESETS["news"]["presenter_intro"] is True
    assert DEFAULT_TYPE_PRESETS["general"]["presenter_intro"] is False


def test_resolve_presenter_uses_settings_name_by_default():
    assert resolve_presenter(_request(), _settings()) == NAME


def test_resolve_presenter_global_off():
    assert resolve_presenter(_request(), _settings(presenter_enabled=False)) is None


def test_resolve_presenter_general_type_off():
    assert resolve_presenter(_request(content_type="general"), _settings()) is None


def test_resolve_presenter_request_empty_disables():
    assert resolve_presenter(_request(presenter_name=""), _settings()) is None


def test_resolve_presenter_request_overrides_name():
    assert resolve_presenter(_request(presenter_name="老李"), _settings()) == "老李"


def test_resolve_presenter_non_zh_off():
    assert resolve_presenter(_request(language="en"), _settings()) is None


def test_resolve_presenter_request_without_field_falls_back():
    request = SimpleNamespace(content_type="indicator", language="zh")
    assert resolve_presenter(request, _settings()) == NAME


def test_resolve_presenter_blank_settings_name_off():
    assert resolve_presenter(_request(), _settings(presenter_name="  ")) is None


# --------------------------------------------------------------------------- #
# Greeting enforcement
# --------------------------------------------------------------------------- #


def _script(texts):
    return GeneratedScript(
        title="T",
        segments=[ScriptSegment(text=text) for text in texts],
    )


def test_greeting_added_when_missing():
    script = _script(["这一集我们来聊聊 MACD。"])
    result = presenter_mod.ensure_presenter_greeting(script, NAME)
    assert result is script
    assert script.segments[0].text == GREETING + "这一集我们来聊聊 MACD。"


def test_greeting_variant_is_replaced():
    script = _script(["大家好，我是小明。今天聊聊 MACD。"])
    presenter_mod.ensure_presenter_greeting(script, NAME)
    assert script.segments[0].text.startswith(GREETING)
    assert "小明" not in script.segments[0].text
    assert "今天聊聊 MACD。" in script.segments[0].text


def test_greeting_already_exact_is_untouched():
    script = _script([GREETING + "正文。"])
    presenter_mod.ensure_presenter_greeting(script, NAME)
    assert script.segments[0].text == GREETING + "正文。"


def test_greeting_is_idempotent():
    script = _script(["欢迎来到本节目。正文。"])
    presenter_mod.ensure_presenter_greeting(script, NAME)
    once = script.segments[0].text
    presenter_mod.ensure_presenter_greeting(script, NAME)
    assert script.segments[0].text == once
    assert once.count(GREETING) == 1


def test_greeting_empty_segments_is_noop():
    script = _script([])
    presenter_mod.ensure_presenter_greeting(script, NAME)
    assert script.segments == []


def test_greeting_empty_name_is_noop():
    script = _script(["正文。"])
    presenter_mod.ensure_presenter_greeting(script, "")
    assert script.segments[0].text == "正文。"


def test_has_presenter_greeting():
    assert presenter_mod.has_presenter_greeting(_script([GREETING + "x"]), NAME)
    assert not presenter_mod.has_presenter_greeting(_script(["x"]), NAME)
    assert not presenter_mod.has_presenter_greeting(_script([]), NAME)


# --------------------------------------------------------------------------- #
# Script review keeps the greeting
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_review_keeps_greeting_when_llm_rewrites(tmp_path):
    from src.services import script_review

    script = _script([GREETING + "这是第一段。"])
    seen: list[list[str]] = []

    async def fake_proofread(ai_client, texts):
        seen.append(list(texts))
        return [
            {"accepted": True, "reason": "", "text": "这是改写后的第一段。", "diff": ""}
        ]

    with patch.object(script_review, "proofread_texts", fake_proofread):
        review = await script_review.review_script(
            MagicMock(), script, presenter_name=NAME
        )

    # The LLM only saw the narration, never the greeting.
    assert seen and seen[0] == ["这是第一段。"]
    assert script.segments[0].text == GREETING + "这是改写后的第一段。"
    assert review.extra["presenter_greeting"] == "kept"


@pytest.mark.asyncio
async def test_review_records_missing_greeting(tmp_path):
    from src.core.task_logger import TaskLogger
    from src.services import script_review

    script = _script(["没有开场白的正文。"])
    logger = TaskLogger("no-greeting", tmp_path)
    review = await script_review.review_script(
        MagicMock(),
        script,
        logger,
        proofread=False,
        presenter_name=NAME,
    )
    assert review.extra["presenter_greeting"] == "missing"
    assert any("开场白缺失" in entry["message"] for entry in logger.logs)


@pytest.mark.asyncio
async def test_review_disabled_when_no_presenter():
    from src.services import script_review

    script = _script(["正文。"])
    review = await script_review.review_script(
        MagicMock(), script, proofread=False, presenter_name=None
    )
    assert "presenter_greeting" not in review.extra


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #


def test_book_prompts_include_greeting_only_when_active():
    from src.services import book_script

    with_name = book_script.build_book_script_prompt(presenter_name=NAME)
    without = book_script.build_book_script_prompt(presenter_name=None)
    assert GREETING in with_name
    assert GREETING not in without
    assert without == book_script.BOOK_DENSE_SCRIPT_PROMPT

    rewrite_with = book_script.build_book_rewrite_prompt(presenter_name=NAME)
    assert GREETING in rewrite_with
    assert GREETING not in book_script.build_book_rewrite_prompt(presenter_name=None)


def test_indicator_prompt_includes_greeting_only_when_active():
    from src.services.indicator import script as ind_script

    assert GREETING in ind_script._build_system_prompt(3, NAME)
    assert GREETING not in ind_script._build_system_prompt(3, None)


def test_news_prompt_includes_greeting_only_when_active():
    from src.services import news_service

    assert news_service.build_news_script_prompt(None) == news_service.NEWS_SCRIPT_PROMPT
    assert GREETING in news_service.build_news_script_prompt(NAME)


# --------------------------------------------------------------------------- #
# label_image
# --------------------------------------------------------------------------- #


def _solid(path, size, colour):
    Image.new("RGB", size, colour).save(path)
    return path


def _centre_unchanged(src, dst, size):
    with Image.open(src) as a, Image.open(dst) as b:
        w, h = size
        box = (w // 2 - 3, h // 2 - 3, w // 2 + 3, h // 2 + 3)
        return a.crop(box).tobytes() == b.crop(box).tobytes()


@pytest.mark.parametrize("colour", [(255, 255, 255), (10, 10, 10)])
def test_label_image_writes_copy_and_preserves_source(tmp_path, colour):
    src = _solid(tmp_path / "src.png", (240, 200), colour)
    before = src.read_bytes()
    dst = tmp_path / "cover_presenter.png"

    result = presenter_mod.label_image(src, dst, NAME)

    assert result == dst
    assert dst.exists()
    assert src.read_bytes() == before  # source never modified
    with Image.open(src) as a, Image.open(dst) as b:
        assert a.size == b.size == (240, 200)
    # Centre content (e.g. title card) is never covered.
    assert _centre_unchanged(src, dst, (240, 200))


def test_label_image_changes_bottom_right_region(tmp_path):
    src = _solid(tmp_path / "src.png", (240, 200), (255, 255, 255))
    dst = tmp_path / "out.png"
    presenter_mod.label_image(src, dst, NAME)

    with Image.open(src) as a, Image.open(dst) as b:
        w, h = a.size
        region = (w * 3 // 5, h * 3 // 5, w, h)
        assert a.crop(region).tobytes() != b.crop(region).tobytes()


def test_label_image_default_font_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(presenter_mod, "_font_candidates", lambda: [])
    src = _solid(tmp_path / "src.png", (120, 80), (255, 255, 255))
    dst = tmp_path / "out.png"
    presenter_mod.label_image(src, dst, NAME)
    assert dst.exists()


# --------------------------------------------------------------------------- #
# Cover: custom title card + generated cover
# --------------------------------------------------------------------------- #


def _charts_manifest(tmp_path, names):
    for name in names:
        _solid(tmp_path / name, (120, 80), (30, 30, 30))
    (tmp_path / "manifest.json").write_text(
        json.dumps([{"file": name} for name in names]), encoding="utf-8"
    )
    return tmp_path


def test_apply_presenter_cover_labels_and_rebinds_intro_segment(tmp_path):
    from src.routes.videos import VideoGenerateRequest

    charts = _charts_manifest(tmp_path, ["00_title_card.png", "01_explain.png"])
    title = charts / "00_title_card.png"
    other = charts / "01_explain.png"
    request = VideoGenerateRequest(
        type="indicator",
        custom_visuals_manifest=str(charts),
        cover_image=str(title),
    )
    script = GeneratedScript(
        title="T",
        segments=[
            ScriptSegment(text="一。", images=[str(title)]),
            ScriptSegment(text="二。", images=[str(other)]),
        ],
    )
    logger = MagicMock()

    vs._apply_presenter_cover(request, script, tmp_path, logger)

    labelled = tmp_path / "cover_presenter.png"
    assert labelled.exists()
    assert request._presenter_cover_path == str(labelled)
    # Intro segment bound to the title card now points at the labelled copy.
    assert script.segments[0].images == [str(labelled)]
    # Unrelated image is untouched.
    assert script.segments[1].images == [str(other)]
    # Source file is intact.
    with Image.open(title) as img:
        assert img.size == (120, 80)


@pytest.mark.asyncio
async def test_generate_cover_prefers_presenter_labelled_copy(tmp_path):
    from src.routes.videos import VideoGenerateRequest

    charts = _charts_manifest(tmp_path, ["00_title_card.png"])
    labelled = tmp_path / "cover_presenter.png"
    _solid(labelled, (60, 40), (20, 20, 20))
    request = VideoGenerateRequest(
        type="indicator",
        custom_visuals_manifest=str(charts),
        cover_image=str(charts / "00_title_card.png"),
    )
    request._presenter_cover_path = str(labelled)
    logger = MagicMock()
    logger.status = {}

    result = await vs._generate_cover(request, tmp_path, logger)

    assert result == labelled


def test_draw_cover_image_accepts_presenter_name(tmp_path):
    from src.core.task_logger import TaskLogger
    from src.services import cover_service

    logger = TaskLogger("cover-presenter", tmp_path / "work")
    output = cover_service._draw_cover_image(
        None, "标题", (240, 240), logger, tmp_path / "work", NAME
    )
    assert output.exists()


def test_apply_presenter_greeting_helper(tmp_path):
    request = _request()
    script = _script(["正文。"])
    logger = MagicMock()
    vs._apply_presenter_greeting(script, request, logger)
    assert script.segments[0].text.startswith(GREETING)
