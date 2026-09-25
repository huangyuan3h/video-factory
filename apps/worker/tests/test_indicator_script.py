"""Indicator script generation: binding + number checks (task-G2)."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from src.core.task_logger import TaskLogger
from src.services.indicator import generate_indicator_script
from src.services.indicator.manifest import IndicatorManifest, ManifestItem


def _png(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    Image.new("RGB", (20, 12), (1, 2, 3)).save(p)
    return p


def _item(tmp_path, name, section="explain", key_point="", seconds=20, title="图"):
    return ManifestItem(
        index=0,
        file=_png(tmp_path, name),
        section=section,
        title=title,
        key_point=key_point,
        suggested_seconds=seconds,
    )


def _manifest(tmp_path, *items):
    return IndicatorManifest(
        charts_dir=tmp_path,
        items=list(items),
        title="MACD 金叉",
        indicator_id="macd",
        manifest_path=tmp_path / "manifest.json",
    )


class _FakeAI:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def complete_json(self, system_prompt, user_prompt, max_tokens=4000):
        self.calls.append(
            {"system": system_prompt, "user": user_prompt, "max_tokens": max_tokens}
        )
        return self._responses.pop(0) if self._responses else {}


def _request(**overrides):
    base = dict(title="MACD 金叉", content="", target_seconds=None)
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_generates_one_bound_segment_per_item(tmp_path):
    item = _item(
        tmp_path,
        "01_explain.png",
        section="explain",
        key_point="MACD 由 12 和 26 日均线算得",
    )
    manifest = _manifest(tmp_path, item)
    ai = _FakeAI([{"segments": [{"index": 0, "text": "MACD 一般用两条均线。"}]}])
    tl = TaskLogger("ind-script-bind", tmp_path)

    script = await generate_indicator_script(ai, manifest, _request(), tl)

    assert len(script.segments) == 1
    seg = script.segments[0]
    assert seg.images == [str(item.file)]
    assert seg.fit == "contain"
    assert seg.motion == "none"
    assert seg.hold_seconds is None
    assert seg.section == "explain"
    assert seg.chart == "01_explain.png"
    assert seg.key_point == item.key_point
    assert script.title == "MACD 金叉"


@pytest.mark.asyncio
async def test_number_present_skips_retry(tmp_path):
    item = _item(tmp_path, "a.png", key_point="GDP 增长 15.5%")
    manifest = _manifest(tmp_path, item)
    ai = _FakeAI([{"segments": [{"index": 0, "text": "GDP 增长 15.5%，表现不错。"}]}])
    tl = TaskLogger("ind-script-numok", tmp_path)

    script = await generate_indicator_script(ai, manifest, _request(), tl)

    assert len(ai.calls) == 1
    report = script.number_report[0]
    assert report["required"] == ["15.5%"]
    assert report["found"] == ["15.5%"]
    assert report["missing_after_retry"] == []
    assert report["appended"] is False


@pytest.mark.asyncio
async def test_retry_recovers_missing_number(tmp_path):
    item = _item(tmp_path, "a.png", key_point="GDP 增长 15.5%")
    manifest = _manifest(tmp_path, item)
    ai = _FakeAI(
        [
            {"segments": [{"index": 0, "text": "GDP 增长很快。"}]},
            {"segments": [{"index": 0, "text": "GDP 增长了 15.5%。"}]},
        ]
    )
    tl = TaskLogger("ind-script-retry", tmp_path)

    script = await generate_indicator_script(ai, manifest, _request(), tl)

    assert len(ai.calls) == 2
    report = script.number_report[0]
    assert "15.5%" in script.segments[0].text
    assert report["missing_after_retry"] == []
    assert report["appended"] is False


@pytest.mark.asyncio
async def test_appends_key_point_after_failed_retry(tmp_path):
    item = _item(tmp_path, "a.png", key_point="GDP 增长 15.5%")
    manifest = _manifest(tmp_path, item)
    ai = _FakeAI(
        [
            {"segments": [{"index": 0, "text": "GDP 增长很快。"}]},
            {"segments": [{"index": 0, "text": "还是没说数字。"}]},
        ]
    )
    tl = TaskLogger("ind-script-append", tmp_path)

    script = await generate_indicator_script(ai, manifest, _request(), tl)

    text = script.segments[0].text
    assert "15.5%" in text
    assert text.endswith("。")
    assert "GDP 增长 15.5%" in text
    report = script.number_report[0]
    assert report["appended"] is True
    assert "15.5%" in report["missing_after_retry"]


@pytest.mark.asyncio
async def test_wrong_count_maps_by_index_and_fills_missing(tmp_path):
    item0 = _item(tmp_path, "a.png", section="intro", key_point="要点零")
    item1 = _item(tmp_path, "b.png", section="summary", key_point="要点一")
    manifest = _manifest(tmp_path, item0, item1)
    ai = _FakeAI(
        [
            {
                "segments": [
                    {"index": 1, "text": "第二张图的讲解。"},
                    {"index": 5, "text": "越界的段落。"},
                ]
            }
        ]
    )
    tl = TaskLogger("ind-script-count", tmp_path)

    script = await generate_indicator_script(ai, manifest, _request(), tl)

    assert len(script.segments) == 2
    assert script.segments[0].text == "要点零"
    assert script.segments[1].text == "第二张图的讲解。"
    assert script.segments[0].images == [str(item0.file)]
    assert script.segments[1].images == [str(item1.file)]


@pytest.mark.asyncio
async def test_title_uses_request_then_manifest(tmp_path):
    item = _item(tmp_path, "a.png", key_point="x")
    manifest = _manifest(tmp_path, item)
    ai = _FakeAI([{"title": "模型标题", "segments": [{"index": 0, "text": "文本。"}]}])

    script = await generate_indicator_script(
        ai, manifest, _request(title="请求标题"), TaskLogger("t1", tmp_path)
    )
    assert script.title == "请求标题"

    ai2 = _FakeAI([{"title": "模型标题", "segments": [{"index": 0, "text": "文本。"}]}])
    script2 = await generate_indicator_script(
        ai2, manifest, _request(title=None), TaskLogger("t2", tmp_path)
    )
    assert script2.title == "MACD 金叉"


@pytest.mark.asyncio
async def test_target_seconds_split_when_missing(tmp_path):
    manifest = _manifest(
        tmp_path,
        _item(tmp_path, "a.png", seconds=None),
        _item(tmp_path, "b.png", seconds=None),
        _item(tmp_path, "c.png", seconds=None),
    )
    ai = _FakeAI(
        [{"segments": [{"index": 0, "text": "一。"}, {"index": 1, "text": "二。"}, {"index": 2, "text": "三。"}]}]
    )
    script = await generate_indicator_script(
        ai, manifest, _request(target_seconds=300), TaskLogger("t3", tmp_path)
    )
    assert [seg.duration_estimate for seg in script.segments] == [100, 100, 100]
    assert script.total_duration_estimate == 300


@pytest.mark.asyncio
async def test_empty_manifest_raises(tmp_path):
    manifest = IndicatorManifest(
        charts_dir=tmp_path, items=[], title="t", indicator_id="t"
    )
    with pytest.raises(ValueError):
        await generate_indicator_script(_FakeAI([]), manifest, _request(), TaskLogger("t4", tmp_path))
