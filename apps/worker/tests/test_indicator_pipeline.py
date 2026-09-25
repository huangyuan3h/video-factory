"""Indicator pipeline wiring: script-only, approved script, script files (task-G2)."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from src.core.ai_client import GeneratedScript, ScriptSegment
from src.routes.videos import VideoGenerateRequest
from src.services import video_service as vs


def _png(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    Image.new("RGB", (32, 18), (5, 6, 7)).save(p)
    return p


def _charts(tmp_path: Path):
    charts = tmp_path / "charts"
    charts.mkdir()
    title = _png(charts, "00_title_card.png")
    explain = _png(charts, "01_explain.png")
    (charts / "manifest.json").write_text(
        json.dumps(
            [
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
                    "suggested_seconds": 25,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return charts, title, explain


def _read_status(task_dir: Path) -> dict:
    return json.loads((task_dir / "status.json").read_text(encoding="utf-8"))


def test_indicator_script_only_writes_files_and_stops(tmp_path):
    charts, title, explain = _charts(tmp_path)
    request = VideoGenerateRequest(
        type="indicator",
        custom_visuals_manifest=str(charts),
        script_only=True,
    )
    task_id = "ind-script-only"
    task_dir = tmp_path / "out"
    vs.video_tasks[task_id] = {}

    script = GeneratedScript(
        title="MACD",
        segments=[
            ScriptSegment(
                text="第一段。",
                images=[str(title)],
                section="intro",
                chart=title.name,
                key_point="MACD 是趋势指标",
            ),
            ScriptSegment(
                text="第二段。",
                images=[str(explain)],
                section="explain",
                chart=explain.name,
                key_point="由 12 和 26 日均线算得",
            ),
        ],
        total_duration_estimate=40,
    )
    ai = MagicMock()
    ai.optimize_content = AsyncMock(return_value=json.dumps([None, None]))
    tts = AsyncMock()

    with patch.object(vs, "_get_ai_client", AsyncMock(return_value=ai)), patch.object(
        vs, "generate_indicator_script", AsyncMock(return_value=script)
    ), patch.object(vs, "_synthesize_audio", tts):
        vs.run_video_generation(task_id, request, task_dir)

    status = _read_status(task_dir)
    assert status["status"] == "script_ready"
    assert status["message"] == "脚本已生成，等待审核"
    assert (task_dir / "script.json").exists()
    assert (task_dir / "script.md").exists()
    assert (task_dir / "script_review.json").exists()
    tts.assert_not_awaited()

    data = json.loads((task_dir / "script.json").read_text(encoding="utf-8"))
    assert data["content_type"] == "indicator"
    assert data["manifest"] == str(charts / "manifest.json")
    assert data["segments"][0]["chart"] == "00_title_card.png"
    # Request cover defaulted to the manifest title card.
    assert request.cover_image == str(title.resolve())

    review = json.loads((task_dir / "script_review.json").read_text(encoding="utf-8"))
    entry = review["segments"][0]
    assert entry["chart"] == "00_title_card.png"
    assert entry["section"] == "intro"
    assert "key_point" in entry


def test_approved_script_skips_generation_and_tts_reads_script(tmp_path):
    _, title, explain = _charts(tmp_path)
    script_json = tmp_path / "script.json"
    script_json.write_text(
        json.dumps(
            {
                "title": "已审核",
                "segments": [
                    {
                        "text": "审核后的文本。",
                        "images": [str(title)],
                        "fit": "contain",
                        "motion": "none",
                        "section": "intro",
                        "chart": title.name,
                        "key_point": "MACD 是趋势指标",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    request = VideoGenerateRequest(type="indicator", approved_script=str(script_json))
    task_id = "ind-approved"
    task_dir = tmp_path / "out-approved"
    vs.video_tasks[task_id] = {}

    captured: list[str] = []

    class _Provider:
        def __init__(self, **kwargs):
            pass

        async def synthesize(self, text, output_path=None, voice=None, boundaries=None):
            captured.append(text)
            Path(output_path).write_bytes(b"x")
            return output_path

        async def get_duration(self, audio_path):
            return 4.0

    generate = AsyncMock(side_effect=AssertionError("must not generate"))
    out_video = task_dir / "video.mp4"

    with patch.object(
        vs, "_get_ai_client", AsyncMock(side_effect=AssertionError("AI not needed"))
    ), patch.object(
        vs, "generate_indicator_script", generate
    ), patch.object(vs, "EdgeTTSEngine", MagicMock(return_value=_Provider())), patch.object(
        vs, "_fetch_materials", AsyncMock(return_value=[])
    ), patch.object(vs, "_generate_subtitles", AsyncMock(return_value=[])), patch.object(
        vs, "_generate_cover", AsyncMock(return_value=None)
    ), patch.object(
        vs, "_compose_final_video", AsyncMock(return_value=out_video)
    ), patch.object(vs, "_auto_publish_if_requested", AsyncMock()):
        vs.run_video_generation(task_id, request, task_dir)

    generate.assert_not_awaited()
    assert captured == ["审核后的文本。"]
    status = _read_status(task_dir)
    assert status["status"] == "completed"
    assert request.cover_image == str(title)
    assert (task_dir / "script_review.json").exists()


@pytest.mark.asyncio
async def test_approved_script_lint_does_not_autofix(tmp_path):
    from src.core.task_logger import TaskLogger

    original = "你好，，世界。"
    script = GeneratedScript(
        title="T", segments=[ScriptSegment(text=original)], total_duration_estimate=5
    )
    logger = TaskLogger("approved-nofix", tmp_path)

    await vs._review_approved_script(script, None, logger, None)

    assert script.segments[0].text == original
    review = json.loads((tmp_path / "script_review.json").read_text(encoding="utf-8"))
    assert review["segments"][0]["final"] == original
    assert review["proofread"] is False


def test_approved_script_missing_chart_fails(tmp_path):
    _, title, _ = _charts(tmp_path)
    script_json = tmp_path / "script.json"
    script_json.write_text(
        json.dumps(
            {
                "title": "T",
                "segments": [{"text": "文本。", "images": [str(tmp_path / "gone.png")]}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    request = VideoGenerateRequest(type="indicator", approved_script=str(script_json))
    task_id = "ind-approved-bad"
    task_dir = tmp_path / "out-bad"
    vs.video_tasks[task_id] = {}

    with patch.object(vs, "_get_ai_client", AsyncMock(return_value=MagicMock())):
        vs.run_video_generation(task_id, request, task_dir)

    status = _read_status(task_dir)
    assert status["status"] == "failed"
    assert "图表" in status["error"]


def test_approved_script_works_for_news_without_title_content(tmp_path):
    script_json = tmp_path / "script.json"
    script_json.write_text(
        json.dumps(
            {"title": "新闻", "segments": [{"text": "新闻正文。"}]}, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    request = VideoGenerateRequest(type="news", approved_script=str(script_json))
    assert request.content is None
    assert request.title is None

    task_id = "news-approved"
    task_dir = tmp_path / "out-news"
    vs.video_tasks[task_id] = {}

    class _Provider:
        def __init__(self, **kwargs):
            pass

        async def synthesize(self, text, output_path=None, voice=None, boundaries=None):
            Path(output_path).write_bytes(b"x")
            return output_path

        async def get_duration(self, audio_path):
            return 2.0

    with patch.object(
        vs, "_get_ai_client", AsyncMock(side_effect=AssertionError("AI not needed"))
    ), patch.object(vs, "EdgeTTSEngine", MagicMock(return_value=_Provider())), patch.object(
        vs, "_fetch_materials", AsyncMock(return_value=[])
    ), patch.object(vs, "_generate_subtitles", AsyncMock(return_value=[])), patch.object(
        vs, "_generate_cover", AsyncMock(return_value=None)
    ), patch.object(
        vs, "_compose_final_video", AsyncMock(return_value=task_dir / "v.mp4")
    ), patch.object(vs, "_auto_publish_if_requested", AsyncMock()):
        vs.run_video_generation(task_id, request, task_dir)

    assert _read_status(task_dir)["status"] == "completed"


def test_general_script_only_writes_files_and_stops(tmp_path):
    request = VideoGenerateRequest(
        title="普通标题", content="普通正文内容。", script_only=True
    )
    task_id = "general-script-only"
    task_dir = tmp_path / "out-general"
    vs.video_tasks[task_id] = {}

    script = GeneratedScript(
        title="普通标题",
        segments=[ScriptSegment(text="一段正文。", keywords=["k"])],
        total_duration_estimate=10,
    )
    ai = MagicMock()
    ai.generate_script = AsyncMock(return_value=script)
    tts = AsyncMock()

    with patch.object(vs, "_get_ai_client", AsyncMock(return_value=ai)), patch.object(
        vs, "_synthesize_audio", tts
    ):
        vs.run_video_generation(task_id, request, task_dir)

    status = _read_status(task_dir)
    assert status["status"] == "script_ready"
    assert (task_dir / "script.json").exists()
    assert (task_dir / "script.md").exists()
    # script_only always reviews (lint-only for the general preset).
    assert (task_dir / "script_review.json").exists()
    tts.assert_not_awaited()
    data = json.loads((task_dir / "script.json").read_text(encoding="utf-8"))
    assert data["content_type"] == "general"


def test_indicator_request_defaults_landscape_and_validates_manifest(tmp_path):
    charts, _, _ = _charts(tmp_path)
    request = VideoGenerateRequest(
        type="indicator", custom_visuals_manifest=str(charts), script_only=True
    )
    assert request.is_indicator() is True
    assert request.resolved_resolution() == (1920, 1080)
    assert request.content is None
    assert request.title is None


def test_indicator_requires_manifest_without_approved_script():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        VideoGenerateRequest(type="indicator", script_only=True)


def test_indicator_missing_manifest_path_rejected(tmp_path):
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        VideoGenerateRequest(
            type="indicator", custom_visuals_manifest=str(tmp_path / "nope")
        )


def test_approved_script_missing_path_rejected(tmp_path):
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        VideoGenerateRequest(type="indicator", approved_script=str(tmp_path / "nope.json"))


def test_run_video_generation_fills_resolution_for_compose(tmp_path):
    script_json = tmp_path / "script.json"
    script_json.write_text(
        json.dumps({"title": "T", "segments": [{"text": "文本。"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    request = VideoGenerateRequest(type="book", approved_script=str(script_json))
    # Simulate an older/cli caller that never canonicalized the pixel dims.
    object.__setattr__(request, "resolution_width", None)
    object.__setattr__(request, "resolution_height", None)
    task_id = "res-fill"
    task_dir = tmp_path / "out-res"
    vs.video_tasks[task_id] = {}

    captured: dict = {}

    async def fake_compose(**kwargs):
        captured.update(kwargs)
        out = task_dir / "video.mp4"
        out.write_bytes(b"x")
        return out

    with patch.object(
        vs, "_synthesize_audio", AsyncMock(return_value=([{}], 4.0))
    ), patch.object(vs, "_fetch_materials", AsyncMock(return_value=[])), patch.object(
        vs, "_generate_subtitles", AsyncMock(return_value=[])
    ), patch.object(vs, "_generate_cover", AsyncMock(return_value=None)), patch.object(
        vs, "compose_video", AsyncMock(side_effect=fake_compose)
    ), patch.object(vs, "_auto_publish_if_requested", AsyncMock()):
        vs.run_video_generation(task_id, request, task_dir)

    # The compose step received a concrete (width, height), never None.
    assert captured["resolution"] == request.resolved_resolution()
    assert all(value is not None and isinstance(value, int) for value in captured["resolution"])
    assert _read_status(task_dir)["status"] == "completed"


def test_script_files_markdown_lists_chart_and_seconds(tmp_path):
    from src.core.task_logger import TaskLogger

    logger = TaskLogger("md", tmp_path)
    script = GeneratedScript(
        title="MD",
        segments=[
            ScriptSegment(
                text="文本。",
                images=["/tmp/a.png"],
                section="intro",
                chart="a.png",
                key_point="要点",
                duration_estimate=12,
            )
        ],
        total_duration_estimate=12,
    )
    vs._write_script_files(script, VideoGenerateRequest(title="t", content="c"), logger)
    md = (tmp_path / "script.md").read_text(encoding="utf-8")
    assert "a.png" in md
    assert "intro" in md
    assert "12" in md
