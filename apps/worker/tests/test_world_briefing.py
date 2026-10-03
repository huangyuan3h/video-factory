"""世界简报 v1 单测（全部离线、无重任务、无真名、无版权照片）。"""

import json


def test_rank_keeps_section_order_and_reasons():
    from src.services.world_briefing.data_2026_10_03 import ITEMS
    from src.services.world_briefing.scoring import rank_items

    ranked, log = rank_items(ITEMS)
    assert 6 <= len(ranked) <= 10
    sections = [r["section"] for r in ranked]
    # 板块顺序 AI→科技→经济与市场→地缘与冲突
    order = {"AI": 0, "科技": 1, "经济与市场": 2, "地缘与冲突": 3}
    assert [order[s] for s in sections] == sorted(order[s] for s in sections)
    assert all("score_reason" in r for r in ranked)
    assert len(log) == len(ranked)
    assert all("重要性" in e["reason"] for e in log)


def test_dedupe_merges_same_event():
    from src.services.world_briefing.scoring import dedupe_cluster

    items = [
        {"id": "a", "section": "AI", "title": "Google 发布 Gemini 4 Argon", "sources": [{"name": "官方", "url": "https://a"}], "numbers": ["1"]},
        {"id": "b", "section": "AI", "title": "Google 发布 Gemini 4 Argon", "sources": [{"name": "媒体", "url": "https://b"}], "numbers": ["2"]},
    ]
    out = dedupe_cluster(items)
    assert len(out) == 1
    assert len(out[0]["sources"]) == 2


def test_private_public_two_versions():
    from src.services.world_briefing.data_2026_10_03 import get_snapshot
    from src.services.world_briefing.scoring import rank_items
    from src.services.world_briefing.script_builder import build_private_md, build_public_md

    snap = get_snapshot("2026-10-03")
    ranked, _ = rank_items(snap["items"])
    priv = build_private_md("2026-10-03", ranked, snap["video_topics"])
    pub = build_public_md("2026-10-03", ranked, snap["video_topics"])
    assert "对你：" in priv
    assert "这意味着什么" in pub
    # 公开版不得出现私人项目细节
    for bad in ["Karios 审计", "VF / OpenCode", "仓位"]:
        assert bad not in pub, bad
    # 私人版结构：板块 + 粗体标题 + 来源链接
    for sec in ["一、AI", "二、科技", "三、经济与市场", "四、地缘与冲突"]:
        assert sec in priv
    assert "来源：" in priv and "http" in priv
    # 市场快照有约数
    assert "约" in priv
    # 结尾 2 选题
    assert "可做成视频的选题" in priv and "①" in priv and "②" in priv
    # 无真名，仅笔名在视频链路（文稿允许无笔名，但绝无真名）
    assert "黄缘" not in priv and "黄缘" not in pub


def test_market_snapshot_numbers_present():
    from src.services.world_briefing.data_2026_10_03 import get_snapshot
    from src.services.world_briefing.scoring import rank_items
    from src.services.world_briefing.script_builder import build_private_md

    snap = get_snapshot("2026-10-03")
    ranked, _ = rank_items(snap["items"])
    priv = build_private_md("2026-10-03", ranked, snap["video_topics"])
    for num in ["23972.29", "2.60%", "$99.88", "6.70", "2.9 万"]:
        assert num in priv, num


def test_factcheck_pass_and_reject_invented():
    from src.services.world_briefing.data_2026_10_03 import get_snapshot
    from src.services.world_briefing.factcheck import factcheck
    from src.services.world_briefing.scoring import rank_items
    from src.services.world_briefing.script_builder import build_narration_segments

    snap = get_snapshot("2026-10-03")
    ranked, _ = rank_items(snap["items"])
    narration = build_narration_segments("2026-10-03", ranked, snap["video_topics"])
    ok, md = factcheck(ranked, narration, snap)
    assert ok, md
    assert "PASS" in md
    # 编造数字应 FAIL
    narration[1]["text"] += "上证指数涨了百分之九十九点九，点位 99999 点。"
    ok2, md2 = factcheck(ranked, narration, snap)
    assert not ok2
    assert "FAIL" in md2


def test_factcheck_rejects_private_leak_in_public():
    from src.services.world_briefing.data_2026_10_03 import get_snapshot
    from src.services.world_briefing.factcheck import factcheck
    from src.services.world_briefing.scoring import rank_items

    snap = get_snapshot("2026-10-03")
    ranked, _ = rank_items(snap["items"])
    narration = [{"text": "大家好，我是躺平的老黄。今天 Karios 审计要赶。不构成投资建议。"}]
    ok, _ = factcheck(ranked, narration, snap)
    assert not ok


def test_pexels_query_rejects_generic_and_scores():
    import pytest

    from src.services.world_briefing.assets import english_query_for, score_pexels_item

    with pytest.raises(ValueError):
        english_query_for("x", "business")
    q = english_query_for("geo", "aircraft carrier ocean navy ships")
    assert "aircraft" in q
    meta = {"title": "aircraft carrier ocean", "photographer": "navy", "tags": [], "page_url": "https://www.pexels.com/video/x", "width": 2560, "duration": 10}
    assert score_pexels_item(meta, q) >= 70
    meta2 = {"title": "cat", "photographer": "x", "tags": [], "page_url": "https://example.com", "width": 640, "duration": 2}
    assert score_pexels_item(meta2, q) < 70


def test_cards_render_2560x1440(tmp_path):
    from PIL import Image

    from src.services.world_briefing.cards import render_item_card, render_market_chart
    from src.services.world_briefing.data_2026_10_03 import ITEMS

    p1 = render_item_card(ITEMS[0], "2026-10-03", tmp_path / "c1.png")
    img = Image.open(p1)
    assert img.size == (2560, 1440)
    mitem = next(i for i in ITEMS if i["id"] == "econ-market-snapshot")
    p2 = render_market_chart(mitem, "2026-10-03", tmp_path / "m.png")
    assert Image.open(p2).size == (2560, 1440)


def test_text_only_pipeline_writes_manuscripts(tmp_path):
    from src.services.world_briefing.pipeline import run_text_only

    res = run_text_only("2026-10-03", tmp_path / "out")
    assert res["factcheck"] == "PASS"
    for name in ("briefing_private.md", "briefing_public.md", "script.json", "script.md", "factcheck.md", "rank_log.json", "description.txt"):
        assert (tmp_path / "out" / name).is_file(), name
    data = json.loads((tmp_path / "out" / "script.json").read_text(encoding="utf-8"))
    assert len(data["segments"]) == 9  # intro + 7 items + outro
    assert data["segments"][0]["text"].startswith("大家好，我是躺平的老黄")


def test_script_json_approved_shape(tmp_path):
    from src.services.world_briefing.pipeline import run_text_only

    run_text_only("2026-10-03", tmp_path / "out")
    data = json.loads((tmp_path / "out" / "script.json").read_text(encoding="utf-8"))
    # GeneratedScript 兼容：title + segments[{text, keywords, duration_estimate, images, fit, motion}]
    assert data["title"]
    for s in data["segments"]:
        assert s["text"] and isinstance(s["keywords"], list)
        assert s["duration_estimate"] > 0
        assert s["fit"] == "contain"


def test_no_crimson_imports():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "services" / "world_briefing"
    for p in root.glob("*.py"):
        txt = p.read_text(encoding="utf-8")
        assert "crimson" not in txt.lower(), p.name
    # 真名仅允许出现在事实核对的拒绝逻辑中（与 daily_news 一致），不得出现在任何产出文稿
    from src.services.world_briefing.data_2026_10_03 import get_snapshot
    from src.services.world_briefing.pipeline import run_text_only
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        from pathlib import Path as _P

        run_text_only("2026-10-03", _P(td))
        for name in ("briefing_private.md", "briefing_public.md", "script.json"):
            assert "黄缘" not in (_P(td) / name).read_text(encoding="utf-8"), name
