"""Tests for the daily-news P0 MVP (all network mocked, no heavy work)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

SNAP = {
    "morning": {"brief": {"id": "2026-09-25-morning", "items": [
        {"title": "美国10年期国债收益率涨穿5.2%，为2007年以来首次",
         "link": "https://wallstreetcn.com/livenews/3170605", "score": 31.0,
         "publishedAt": "2026-09-24T12:12:00+00:00", "aiSummary": "10年期美债收益率升至5.2%",
         "importance": 5, "relevanceScore": 75},
        {"title": "也门胡塞武装：打击沙特首都利雅得和Yanbu的阿美设施。",
         "link": "https://wallstreetcn.com/livenews/3170586", "score": 26.2,
         "publishedAt": "2026-09-24T11:03:29+00:00", "aiSummary": "胡塞武装袭击沙特阿美设施",
         "importance": 4},
        {"title": "法国将派遣军事援助与部队保护沙特石油设施",
         "link": "https://wallstreetcn.com/livenews/3170571", "score": 26.2,
         "publishedAt": "2026-09-24T10:29:44+00:00", "aiSummary": "法国派兵保护沙特延布石油设施",
         "importance": 4},
    ]}},
    "midday": {"brief": {"id": "2026-09-25-midday", "items": []}},
}


def test_pick_finance_topic_uses_top_score():
    from src.services.daily_news.topic import pick_finance_topic

    topic = pick_finance_topic(SNAP)
    assert "5.2%" in topic["title"]
    assert topic["top_item"]["score"] == 31.0
    assert len(topic["evidence_links"]) >= 3


def test_build_script_greeting_and_disclaimer():
    from src.services.daily_news.script_builder import build_script
    from src.services.daily_news.topic import pick_finance_topic

    topic = pick_finance_topic(SNAP)
    script, md = build_script(topic, SNAP)
    assert len(script["segments"]) == 5
    assert script["segments"][0]["text"].startswith("大家好，我是躺平的老黄")
    assert "不构成投资建议" in script["segments"][-1]["text"]
    assert "黄缘" not in md
    for seg in script["segments"]:
        assert len(seg["keywords"]) >= 2


def test_factcheck_passes_for_built_script():
    from src.services.daily_news.factcheck import factcheck_script
    from src.services.daily_news.script_builder import build_script
    from src.services.daily_news.topic import pick_finance_topic

    topic = pick_finance_topic(SNAP)
    script, _ = build_script(topic, SNAP)
    passed, md = factcheck_script(script, SNAP, topic)
    assert passed, md
    assert "PASS" in md


def test_factcheck_rejects_invented_number():
    from src.services.daily_news.factcheck import factcheck_script
    from src.services.daily_news.script_builder import build_script
    from src.services.daily_news.topic import pick_finance_topic

    topic = pick_finance_topic(SNAP)
    script, _ = build_script(topic, SNAP)
    script["segments"][0]["text"] += "上证指数涨了百分之九十九点九。"
    passed, md = factcheck_script(script, SNAP, topic)
    assert not passed
    assert "FAIL" in md


def test_data_card_renders_1920x950(tmp_path):
    from PIL import Image

    from src.services.daily_news.data_card import render_data_card
    from src.services.daily_news.topic import pick_finance_topic

    topic = pick_finance_topic(SNAP)
    out = render_data_card(topic, SNAP, tmp_path / "card.png")
    img = Image.open(out)
    assert img.size == (1920, 950)
    # CJK must render as real glyphs, not tofu: card must not be ~blank.
    gray = img.convert("L")
    extrema = gray.getextrema()
    assert extrema[0] < 250  # some dark text pixels exist


def test_bind_media_sets_cover_fit_for_videos(tmp_path):
    import json

    from src.services.daily_news.pipeline import _bind_media_to_script

    (tmp_path / "candidates").mkdir()
    (tmp_path / "candidates" / "pexels_1.mp4").write_bytes(b"\x00" * 64)
    (tmp_path / "karios_card.png").write_bytes(b"\x00" * 64)
    (tmp_path / "script.json").write_text(json.dumps({
        "title": "t",
        "segments": [
            {"text": "a", "keywords": [], "duration_estimate": 10},
            {"text": "b", "keywords": [], "duration_estimate": 10},
        ],
    }), encoding="utf-8")
    (tmp_path / "material_attribution.json").write_text(json.dumps({
        "materials": [
            {"segment": 0, "file": "pexels_1.mp4"},
            {"segment": 1, "file": "karios_card.png"},
        ],
    }), encoding="utf-8")
    out = _bind_media_to_script(tmp_path)
    bound = json.loads(out.read_text(encoding="utf-8"))
    assert bound["segments"][0]["fit"] == "cover"
    assert "fit" not in bound["segments"][1]


def test_score_relevance_prefers_pexels_whitelist():
    from src.services.daily_news.materials import score_relevance

    item = {"page_url": "https://www.pexels.com/video/x-123/",
            "photographer": "bond chart finance", "width": 1920}
    assert score_relevance(item, ["债券收益率"]) >= 70


@pytest.mark.asyncio
async def test_pipeline_with_snapshot_no_render(tmp_path):
    import json

    from src.services.daily_news.pipeline import run_mvp

    snap_path = tmp_path / "snap.json"
    snap_path.write_text(json.dumps(SNAP), encoding="utf-8")
    with patch(
        "src.services.daily_news.pipeline.fetch_pexels_videos_with_attribution",
        new_callable=AsyncMock,
    ) as mock_fetch:
        mock_fetch.return_value = ([], [])
        res = await run_mvp(tmp_path / "task", snapshot_path=snap_path,
                            render=False, pexels_api_key="dummy")
    assert res["factcheck"] == "PASS"
    for name in ("topic.json", "script.json", "script.md", "factcheck.md",
                 "material_attribution.json", "karios_card.png"):
        assert (tmp_path / "task" / name).exists(), name
