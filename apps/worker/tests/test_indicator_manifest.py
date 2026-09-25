"""Manifest loader for indicator chart episodes (task-G2)."""

import json
from pathlib import Path

import pytest
from PIL import Image

from src.services.indicator import load_manifest, required_numbers


def _png(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    Image.new("RGB", (20, 12), (10, 20, 30)).save(p)
    return p


def _write(tmp_path: Path, payload) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_loads_canonical_list_manifest(tmp_path):
    _png(tmp_path, "00_title_card.png")
    _png(tmp_path, "01_explain.png")
    payload = [
        {
            "file": "00_title_card.png",
            "section": "intro",
            "title": "封面",
            "key_point": "MACD 是趋势指标",
            "suggested_seconds": 15,
        },
        {
            "file": "01_explain.png",
            "section": "explain",
            "title": "原理",
            "key_point": "由 12 和 26 日均线算得",
            "suggested_seconds": 20,
        },
    ]
    manifest = load_manifest(_write(tmp_path, payload))

    assert len(manifest.items) == 2
    assert manifest.manifest_path == (tmp_path / "manifest.json").resolve()
    assert manifest.charts_dir == tmp_path.resolve()
    assert [item.index for item in manifest.items] == [0, 1]
    assert manifest.items[0].file == (tmp_path / "00_title_card.png").resolve()
    assert manifest.items[0].section == "intro"
    assert manifest.items[0].suggested_seconds == 15
    # Title card = intro + "title" in the filename.
    assert manifest.cover.file.name == "00_title_card.png"


def test_loads_from_directory_path(tmp_path):
    _png(tmp_path, "a.png")
    _write(tmp_path, [{"file": "a.png", "section": "intro"}])
    manifest = load_manifest(tmp_path)
    assert len(manifest.items) == 1
    assert manifest.manifest_path.name == "manifest.json"


def test_loads_dict_with_charts_and_metadata(tmp_path):
    _png(tmp_path, "a.png")
    payload = {
        "indicator_id": "macd-golden-cross",
        "title": "MACD 金叉",
        "charts": [
            {"path": "a.png", "section": "intro", "point": "要点", "seconds": "18"},
        ],
    }
    manifest = load_manifest(_write(tmp_path, payload))
    assert manifest.indicator_id == "macd-golden-cross"
    assert manifest.title == "MACD 金叉"
    assert manifest.items[0].file.name == "a.png"
    assert manifest.items[0].key_point == "要点"
    assert manifest.items[0].suggested_seconds == 18


def test_loads_dict_with_items_alias_and_image_field(tmp_path):
    _png(tmp_path, "a.png")
    payload = {
        "indicator_name": "KDJ",
        "items": [{"image": "a.png", "duration": 12, "keypoint": "超买超卖"}],
    }
    manifest = load_manifest(_write(tmp_path, payload))
    assert manifest.title == "KDJ"
    assert manifest.items[0].file.name == "a.png"
    assert manifest.items[0].suggested_seconds == 12
    assert manifest.items[0].key_point == "超买超卖"


def test_manifest_order_is_preserved(tmp_path):
    _png(tmp_path, "z.png")
    _png(tmp_path, "a.png")
    payload = [{"file": "z.png"}, {"file": "a.png"}]
    manifest = load_manifest(_write(tmp_path, payload))
    assert [item.file.name for item in manifest.items] == ["z.png", "a.png"]


def test_title_card_falls_back_to_first_item(tmp_path):
    _png(tmp_path, "explain.png")
    _png(tmp_path, "intro.png")
    payload = [
        {"file": "explain.png", "section": "explain"},
        {"file": "intro.png", "section": "intro"},
    ]
    manifest = load_manifest(_write(tmp_path, payload))
    # Second item is intro but has no "title" filename -> first item wins.
    assert manifest.cover.file.name == "explain.png"


def test_unknown_section_is_kept(tmp_path, caplog):
    _png(tmp_path, "a.png")
    payload = [{"file": "a.png", "section": "Weird"}]
    manifest = load_manifest(_write(tmp_path, payload))
    assert manifest.items[0].section == "weird"


def test_absolute_file_path_allowed(tmp_path):
    img = _png(tmp_path, "abs.png")
    payload = [{"file": str(img)}]
    manifest = load_manifest(_write(tmp_path, payload))
    assert manifest.items[0].file == img.resolve()


def test_missing_manifest_raises_value_error(tmp_path):
    with pytest.raises(ValueError) as exc:
        load_manifest(tmp_path / "nope.json")
    assert "不存在" in str(exc.value)


def test_empty_manifest_raises_value_error(tmp_path):
    with pytest.raises(ValueError) as exc:
        load_manifest(_write(tmp_path, []))
    assert "为空" in str(exc.value)


def test_invalid_json_raises_value_error(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_manifest(path)
    assert "JSON" in str(exc.value)


def test_item_missing_file_raises(tmp_path):
    with pytest.raises(ValueError) as exc:
        load_manifest(_write(tmp_path, [{"section": "intro"}]))
    assert "file" in str(exc.value)


def test_missing_chart_file_raises(tmp_path):
    with pytest.raises(ValueError) as exc:
        load_manifest(_write(tmp_path, [{"file": "gone.png"}]))
    assert "不存在" in str(exc.value)


def test_bad_extension_raises(tmp_path):
    (tmp_path / "chart.gif").write_bytes(b"x")
    with pytest.raises(ValueError) as exc:
        load_manifest(_write(tmp_path, [{"file": "chart.gif"}]))
    assert "扩展名" in str(exc.value)


def test_object_without_charts_raises(tmp_path):
    with pytest.raises(ValueError):
        load_manifest(_write(tmp_path, {"title": "x"}))


def test_required_numbers_reuses_shared_definition():
    numbers = required_numbers("涨了15.5%，约1,000点，三点五倍，再加 12 %")
    assert "15.5%" in numbers
    assert "1,000" in numbers
    assert "三点五" in numbers
    # Duplicates collapse.
    assert required_numbers("15% 与 15%") == ["15%"]
    assert required_numbers("") == []
