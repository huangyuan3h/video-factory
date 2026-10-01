"""Img-upload fix tests (2026-09-30 ep3): retry + re-encode + topic fallback.

Pure logic only, no browser. Covers:
- resolve_topic_candidates / pick_closest_topic (A股 fallback)
- reencode_image_for_zhihu (flatten RGB, strip metadata, resize <=1920)
- sort_zhihu_queue_items (queue.json sorted by episode number)
"""

from pathlib import Path

from src.publishers.zhihu import (
    IMAGE_REENCODE_MAX_WIDTH,
    pick_closest_topic,
    reencode_image_for_zhihu,
    resolve_topic_candidates,
    sort_zhihu_queue_items,
)


def test_resolve_topic_candidates_aguhas_fallbacks():
    cands = resolve_topic_candidates("A股")
    assert cands[0] == "A股"
    assert "股票" in cands
    assert "证券市场" in cands
    assert len(cands) == len(set(cands))


def test_resolve_topic_candidates_empty_and_unknown():
    assert resolve_topic_candidates("") == []
    assert resolve_topic_candidates("  ") == []
    # Unknown topic has no fallbacks: just itself.
    assert resolve_topic_candidates("量化交易") == ["量化交易"]


def test_pick_closest_topic_exact_first():
    assert pick_closest_topic(["股票", "证券市场"], ["A股", "股票"]) == "股票"
    # Exact for first candidate wins even when later candidate also exact.
    assert pick_closest_topic(["A股", "股票"], ["A股", "股票"]) == "A股"


def test_pick_closest_topic_substring_then_top():
    # No exact: substring match wins over top result.
    assert pick_closest_topic(["A股市场观察", "基金"], ["A股"]) == "A股市场观察"
    # No substring: top suggestion is the closest available.
    assert pick_closest_topic(["基金定投", "理财"], ["A股"]) == "基金定投"
    assert pick_closest_topic([], ["A股"]) is None


def test_reencode_strips_metadata_flattens_and_resizes(tmp_path):
    try:
        from PIL import Image
    except ImportError:
        import pytest

        pytest.skip("Pillow not available")
    src = tmp_path / "04_metrics_table.png"
    # RGBA with metadata-like save (Pillow writes no tEXt by default; the
    # point is output is RGB, <=1920px, readable PNG).
    img = Image.new("RGBA", (2000, 500), (255, 0, 0, 128))
    img.save(src, format="PNG")
    out = reencode_image_for_zhihu(src, dest_dir=tmp_path, max_width=1920)
    assert out.exists()
    assert out.name.endswith(".zhihu.png")
    got = Image.open(out)
    assert got.mode == "RGB"
    assert got.size[0] <= 1920
    assert got.size[0] == 1920
    # Small image keeps size, still RGB.
    src2 = tmp_path / "07_takeaways_card.png"
    Image.new("RGBA", (1080, 1080), (0, 255, 0, 255)).save(src2, format="PNG")
    out2 = reencode_image_for_zhihu(src2, dest_dir=tmp_path)
    got2 = Image.open(out2)
    assert got2.mode == "RGB"
    assert got2.size == (1080, 1080)


def test_reencode_missing_raises(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError):
        reencode_image_for_zhihu(tmp_path / "nope.png")


def test_reencode_real_ep3_images(tmp_path):
    import shutil

    try:
        from PIL import Image
    except ImportError:
        import pytest

        pytest.skip("Pillow not available")
    ep3 = Path("/Users/huangyuan/Projects/karios-series-output/zhihu/ep3_holiday_effect/images")
    if not (ep3 / "04_metrics_table.png").exists():
        import pytest

        pytest.skip("ep3 images not present")
    for name in ("04_metrics_table.png", "07_takeaways_card.png"):
        dst = tmp_path / name
        shutil.copy(ep3 / name, dst)
        out = reencode_image_for_zhihu(dst, dest_dir=tmp_path)
        got = Image.open(out)
        assert got.mode == "RGB"
        assert got.size[0] <= IMAGE_REENCODE_MAX_WIDTH


def test_sort_queue_items_by_episode():
    items = [
        {"ep": "ep11", "payload": "p11"},
        {"ep": "ep3", "payload": "p3"},
        {"ep": "ep9", "payload": "p9"},
        {"ep": "ep2", "payload": "p2"},
    ]
    got = sort_zhihu_queue_items(items)
    assert [i["ep"] for i in got] == ["ep2", "ep3", "ep9", "ep11"]
    # Stable + unparseable last.
    items2 = [{"ep": "epx"}, {"ep": "ep4"}]
    got2 = sort_zhihu_queue_items(items2)
    assert got2[0]["ep"] == "ep4"
