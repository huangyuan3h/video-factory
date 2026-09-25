"""Script double-check: deterministic lint, auto-fix and LLM proofread (task-S)."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.core.task_logger import TaskLogger
from src.services import script_review as sr
from src.services import video_service as vs

# --------------------------------------------------------------------------- #
# Lint rules
# --------------------------------------------------------------------------- #


def _codes(findings):
    return {f.code for f in findings}


def test_lint_catches_doubled_and_leading_punctuation():
    codes = _codes(sr.lint_segment("，你好。", "，你好。"))
    assert "leading_punctuation" in codes

    codes = _codes(sr.lint_segment("你好", "你好，，世界"))
    assert "doubled_punctuation" in codes


def test_lint_catches_ascii_punctuation_next_to_cjk():
    codes = _codes(sr.lint_segment("你好,世界", "你好,世界"))
    assert "ascii_punctuation_cjk" in codes


def test_lint_ignores_number_separators():
    codes = _codes(sr.lint_segment("1,000 和 3:00", "1,000 和 3:00"))
    assert "ascii_punctuation_cjk" not in codes


def test_lint_catches_long_unpunctuated_sentence():
    long = "这" * 61
    codes = _codes(sr.lint_segment(long, long))
    assert "long_unpunctuated" in codes


def test_lint_catches_split_numbers():
    codes = _codes(sr.lint_segment("涨了15. 5个百分点", "涨了15. 5个百分点"))
    assert "split_number" in codes
    codes = _codes(sr.lint_segment("占比52 %", "占比52 %"))
    assert "split_number" in codes


def test_lint_catches_markdown_leftover():
    codes = _codes(sr.lint_segment("**重点** 内容", "重点 内容"))
    assert "markdown_leftover" in codes


def test_lint_catches_comma_near_bracket():
    findings = sr.lint_segment("他说，《你好》。", "他说，你好。")
    assert "comma_near_bracket" in _codes(findings)


def test_lint_catches_residual_marks_in_tts_input():
    codes = _codes(sr.lint_segment("原文", "残留《括号》"))
    assert "residual_mark" in codes


# --------------------------------------------------------------------------- #
# Auto-fix
# --------------------------------------------------------------------------- #


def test_auto_fix_collapses_doubled_punctuation():
    fixed, notes = sr.auto_fix_text("你好，，世界")
    assert fixed == "你好，世界"
    assert "折叠重复标点" in notes


def test_auto_fix_removes_comma_around_bracket():
    fixed, notes = sr.auto_fix_text("他说，《你好》")
    assert fixed == "他说《你好》"
    assert any("书名号" in note for note in notes)


def test_auto_fix_converts_ascii_punctuation_next_to_cjk():
    fixed, notes = sr.auto_fix_text("你好,世界;ok")
    assert fixed == "你好，世界；ok"
    assert "半角标点转全角" in notes


def test_auto_fix_removes_comma_before_terminal():
    fixed, _ = sr.auto_fix_text("你好，。")
    assert fixed == "你好。"


# --------------------------------------------------------------------------- #
# Proofread validation
# --------------------------------------------------------------------------- #


def test_evaluate_fix_accepts_when_numbers_equal():
    result = sr.evaluate_fix("涨了15.5%", "上涨了15.5%")
    assert result["accepted"] is True
    assert result["text"] == "上涨了15.5%"


def test_evaluate_fix_rejects_number_change():
    assert sr.evaluate_fix("涨了15.5%", "涨了15%")["reason"] == "number_mismatch"


def test_evaluate_fix_rejects_chinese_number_change():
    assert sr.evaluate_fix("涨了三点五倍", "涨了三点八倍")["reason"] == "number_mismatch"


def test_evaluate_fix_rejects_large_length_change():
    original = "涨了15.5%"
    candidate = original + "，" + "补充说明" * 10
    assert sr.evaluate_fix(original, candidate)["reason"] == "length_change"


def test_evaluate_fix_rejects_empty_and_noop():
    assert sr.evaluate_fix("你好", "")["reason"] == "empty"
    assert sr.evaluate_fix("你好", "你好")["reason"] == "no_change"


# --------------------------------------------------------------------------- #
# proofread_texts with a mocked AI client
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_proofread_texts_accepts_valid_candidates():
    client = SimpleNamespace(optimize_content=AsyncMock(return_value=json.dumps(["你好世界。"])))
    results = await sr.proofread_texts(client, ["你好世界。"])
    assert results[0]["accepted"] is False  # unchanged -> no_change
    assert results[0]["text"] == "你好世界。"


@pytest.mark.asyncio
async def test_proofread_texts_accepts_fenced_json_and_change():
    original = "今天天气很好我们出去玩吧。"
    candidate = "今天天气很好，我们出去玩吧。"
    raw = "```json\n" + json.dumps([candidate]) + "\n```"
    client = SimpleNamespace(optimize_content=AsyncMock(return_value=raw))
    results = await sr.proofread_texts(client, [original])
    assert results[0]["accepted"] is True
    assert results[0]["text"] == candidate


@pytest.mark.asyncio
async def test_proofread_texts_keeps_originals_on_exception():
    client = SimpleNamespace(
        optimize_content=AsyncMock(side_effect=RuntimeError("api down"))
    )
    results = await sr.proofread_texts(client, ["第一段。", "第二段。"])
    assert [r["text"] for r in results] == ["第一段。", "第二段。"]
    assert all(r["reason"] == "llm_error" for r in results)


@pytest.mark.asyncio
async def test_proofread_texts_keeps_originals_on_length_mismatch():
    client = SimpleNamespace(optimize_content=AsyncMock(return_value=json.dumps(["only one"])))
    results = await sr.proofread_texts(client, ["一。", "二。"])
    assert all(r["reason"] == "llm_output_mismatch" for r in results)


# --------------------------------------------------------------------------- #
# review_script + writer
# --------------------------------------------------------------------------- #


def _script(*texts):
    return SimpleNamespace(segments=[SimpleNamespace(text=t) for t in texts])


@pytest.mark.asyncio
async def test_review_script_writes_files_and_mutates_script(tmp_path):
    tl = TaskLogger("review-book", tmp_path)
    script = _script("你好，，世界。", "第二段。")
    client = SimpleNamespace(optimize_content=AsyncMock(return_value=json.dumps([None, None])))

    review = await sr.review_script(client, script, tl, proofread=True)
    json_path, md_path = review.write(tmp_path, tl)

    assert script.segments[0].text == "你好，世界。"
    assert json_path.exists()
    assert md_path.exists()
    assert tl.status["files"]["script_review"].endswith("script_review.json")

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["segment_count"] == 2
    entry = data["segments"][0]
    for key in (
        "index",
        "original",
        "final",
        "tts_input",
        "lint_before",
        "lint_after",
        "auto_fixes",
        "proofread",
        "char_count",
    ):
        assert key in entry
    assert entry["original"] == "你好，，世界。"
    assert entry["final"] == "你好，世界。"
    assert "折叠重复标点" in entry["auto_fixes"]


@pytest.mark.asyncio
async def test_review_script_without_proofread_keeps_text(tmp_path):
    tl = TaskLogger("review-noproof", tmp_path)
    script = _script("第一段。")
    client = SimpleNamespace(optimize_content=AsyncMock())
    review = await sr.review_script(client, script, tl, proofread=False)
    assert script.segments[0].text == "第一段。"
    assert review.segments[0]["proofread"]["reason"] == "disabled"
    client.optimize_content.assert_not_awaited()


# --------------------------------------------------------------------------- #
# Hook: _maybe_review_script
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_maybe_review_script_runs_for_zh_book(tmp_path):
    tl = TaskLogger("hook-book", tmp_path)
    script = _script("你好，，世界。")
    client = SimpleNamespace(optimize_content=AsyncMock(return_value=json.dumps([None])))

    await vs._maybe_review_script(
        client, script, SimpleNamespace(content_type="book", language="zh"), tl
    )

    assert script.segments[0].text == "你好，世界。"
    assert (tmp_path / "script_review.json").exists()


@pytest.mark.asyncio
async def test_maybe_review_script_skips_english_and_general(tmp_path):
    client = SimpleNamespace(optimize_content=AsyncMock())
    for request in (
        SimpleNamespace(content_type="book", language="en"),
        SimpleNamespace(content_type="general", language="zh"),
    ):
        tl = TaskLogger(f"hook-skip-{request.language}-{request.content_type}", tmp_path)
        script = _script("Hello.,, world")
        await vs._maybe_review_script(client, script, request, tl)
        assert not (tmp_path / "script_review.json").exists()
    client.optimize_content.assert_not_awaited()
