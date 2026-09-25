"""CLI runner + API example for indicator episodes (task-G2)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from src.services import cli_runner


def _png(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    Image.new("RGB", (24, 14), (9, 9, 9)).save(p)
    return p


def _charts(tmp_path: Path) -> Path:
    charts = tmp_path / "charts"
    charts.mkdir()
    _png(charts, "00_title_card.png")
    _png(charts, "01_explain.png")
    (charts / "manifest.json").write_text(
        json.dumps(
            [
                {"file": "00_title_card.png", "section": "intro", "key_point": "要点"},
                {"file": "01_explain.png", "section": "explain", "key_point": "要点二"},
            ]
        ),
        encoding="utf-8",
    )
    return charts


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def test_slugify_keeps_cjk_and_trims():
    assert cli_runner.slugify("MACD 金叉!!") == "macd-金叉"
    assert cli_runner.slugify("") == "episode"
    assert cli_runner.slugify(None) == "episode"


def test_default_out_dir_layout(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_runner.settings, "output_dir", tmp_path)
    out = cli_runner.default_out_dir("indicator", "MACD 金叉")
    assert out.parent.parent == tmp_path / "indicator"
    assert out.parent.name == "macd-金叉"


def test_format_result_lists_paths():
    result = {
        "task_id": "video-1",
        "task_dir": "/tmp/x",
        "status": {
            "status": "script_ready",
            "files": {"script": "/tmp/x/script.json", "script_md": "/tmp/x/script.md"},
        },
    }
    text = cli_runner.format_result(result)
    assert "TASK_DIR: /tmp/x" in text
    assert "script.json" in text
    assert "script.md" in text
    assert cli_runner.result_exit_code(result) == 0
    assert cli_runner.result_exit_code({"status": {"status": "failed"}}) == 1


# --------------------------------------------------------------------------- #
# Argument parsing + request building
# --------------------------------------------------------------------------- #


def test_indicator_parser_accepts_all_flags(tmp_path):
    charts = _charts(tmp_path)
    parser = cli_runner.build_indicator_parser()
    args = parser.parse_args(
        [
            "--manifest",
            str(charts),
            "--title",
            "MACD 金叉",
            "--context",
            str(tmp_path / "summary.md"),
            "--voice",
            "zh-CN-YunxiNeural",
            "--out-dir",
            str(tmp_path / "out"),
            "--script-only",
        ]
    )
    assert args.manifest == charts
    assert args.title == "MACD 金叉"
    assert args.script_only is True
    assert args.voice == "zh-CN-YunxiNeural"


def test_build_indicator_request_with_context(tmp_path):
    charts = _charts(tmp_path)
    context = tmp_path / "summary.md"
    context.write_text("背景：MACD 是趋势指标", encoding="utf-8")
    parser = cli_runner.build_indicator_parser()
    args = parser.parse_args(
        ["--manifest", str(charts), "--context", str(context), "--script-only"]
    )
    request, name = cli_runner.build_indicator_request(args)
    assert request.content_type == "indicator"
    assert request.script_only is True
    assert request.custom_visuals_manifest == str(charts)
    assert request.content == "背景：MACD 是趋势指标"
    assert name == charts.name


def test_build_indicator_request_requires_manifest_or_approved(tmp_path):
    parser = cli_runner.build_indicator_parser()
    args = parser.parse_args([])
    with pytest.raises(ValueError):
        cli_runner.build_indicator_request(args)


def test_build_generic_request_from_content_file(tmp_path):
    content = tmp_path / "chapter.txt"
    content.write_text("第一章正文。", encoding="utf-8")
    parser = cli_runner.build_generic_parser()
    args = parser.parse_args(
        ["--type", "book", "--title", "第一章", "--content-file", str(content), "--script-only"]
    )
    request, name = cli_runner.build_generic_request(args)
    assert request.content_type == "book"
    assert request.content == "第一章正文。"
    assert request.script_only is True
    assert name == "第一章"


def test_build_generic_request_from_series_episodes(tmp_path):
    episodes = tmp_path / "episodes.json"
    episodes.write_text(
        json.dumps(
            [
                {"title": "第一集", "content": "内容一", "series_id": "s1"},
                {"title": "第二集", "content": "内容二"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    parser = cli_runner.build_generic_parser()
    args = parser.parse_args(
        ["--type", "general", "--series-episodes", str(episodes), "--episode-index", "1"]
    )
    request, name = cli_runner.build_generic_request(args)
    assert request.title == "第二集"
    assert request.content == "内容二"
    assert name == "第二集"


def test_build_generic_request_bad_index(tmp_path):
    episodes = tmp_path / "episodes.json"
    episodes.write_text("[]", encoding="utf-8")
    parser = cli_runner.build_generic_parser()
    args = parser.parse_args(
        ["--type", "general", "--series-episodes", str(episodes), "--episode-index", "3"]
    )
    with pytest.raises(ValueError):
        cli_runner.build_generic_request(args)


def test_build_generic_request_selects_by_index_field(tmp_path):
    episodes = tmp_path / "episodes.json"
    episodes.write_text(
        json.dumps(
            [
                {"index": 1, "title": "第一章", "content": "内容一"},
                {"index": 2, "title": "第二章", "content": "内容二"},
                {"index": 5, "title": "第五章", "content": "内容五"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    parser = cli_runner.build_generic_parser()
    args = parser.parse_args(
        ["--type", "book", "--series-episodes", str(episodes), "--episode-index", "2"]
    )
    request, name = cli_runner.build_generic_request(args)
    # Selects the entry whose 1-based ``index`` field equals the argument.
    assert request.title == "第二章"
    assert request.content == "内容二"
    assert name == "第二章"


def test_build_generic_request_index_field_not_found(tmp_path):
    episodes = tmp_path / "episodes.json"
    episodes.write_text(
        json.dumps(
            [{"index": 1, "title": "第一章", "content": "内容一"}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    parser = cli_runner.build_generic_parser()
    args = parser.parse_args(
        ["--type", "book", "--series-episodes", str(episodes), "--episode-index", "9"]
    )
    with pytest.raises(ValueError) as exc:
        cli_runner.build_generic_request(args)
    assert "not found" in str(exc.value)


# --------------------------------------------------------------------------- #
# run_pipeline + main entry points (pipeline mocked, no network)
# --------------------------------------------------------------------------- #


def test_run_pipeline_in_process_with_mocked_runner(tmp_path):
    def fake_runner(task_id, request, task_dir):
        Path(task_dir).mkdir(parents=True, exist_ok=True)
        (Path(task_dir) / "status.json").write_text(
            json.dumps({"status": "script_ready", "files": {}}), encoding="utf-8"
        )

    with patch.object(cli_runner, "run_video_generation", fake_runner):
        result = cli_runner.run_pipeline(MagicMock(model_dump=lambda: {}), tmp_path / "out")

    assert result["status"]["status"] == "script_ready"
    assert result["task_id"].startswith("video-")


def test_indicator_main_script_only_exit_zero(tmp_path):
    charts = _charts(tmp_path)
    status = {
        "task_id": "video-1",
        "task_dir": str(tmp_path / "out"),
        "status": {
            "status": "script_ready",
            "files": {"script": str(tmp_path / "out" / "script.json")},
        },
    }
    with patch.object(cli_runner, "run_pipeline", MagicMock(return_value=status)) as run:
        code = cli_runner.indicator_main(
            ["--manifest", str(charts), "--script-only", "--out-dir", str(tmp_path / "out")]
        )
    assert code == 0
    request = run.call_args.args[0]
    assert request.content_type == "indicator"
    assert request.script_only is True


def test_indicator_main_failure_exit_one(tmp_path):
    charts = _charts(tmp_path)
    with patch.object(
        cli_runner, "run_pipeline", MagicMock(return_value={"status": {"status": "failed"}})
    ):
        code = cli_runner.indicator_main(
            ["--manifest", str(charts), "--out-dir", str(tmp_path / "out")]
        )
    assert code == 1


def test_indicator_main_reports_run_error(tmp_path):
    charts = _charts(tmp_path)
    with patch.object(cli_runner, "run_pipeline", MagicMock(side_effect=RuntimeError("boom"))):
        code = cli_runner.indicator_main(
            ["--manifest", str(charts), "--out-dir", str(tmp_path / "out")]
        )
    assert code == 1


def test_generic_main_script_only(tmp_path):
    content = tmp_path / "c.txt"
    content.write_text("正文。", encoding="utf-8")
    status = {"status": {"status": "script_ready"}, "task_dir": str(tmp_path / "o")}
    with patch.object(cli_runner, "run_pipeline", MagicMock(return_value=status)) as run:
        code = cli_runner.generic_main(
            [
                "--type",
                "general",
                "--title",
                "T",
                "--content-file",
                str(content),
                "--script-only",
                "--out-dir",
                str(tmp_path / "o"),
            ]
        )
    assert code == 0
    assert run.call_args.args[0].content_type == "general"


# --------------------------------------------------------------------------- #
# API example
# --------------------------------------------------------------------------- #


@pytest.fixture
def client():
    from src.routes.videos import router

    app = FastAPI()
    app.include_router(router, prefix="/api/videos")
    return TestClient(app)


def test_api_indicator_script_only(client, tmp_path):
    charts = _charts(tmp_path)
    with patch("src.routes.videos.run_video_generation"):
        response = client.post(
            "/api/videos/generate",
            json={
                "type": "indicator",
                "custom_visuals_manifest": str(charts),
                "title": "MACD 金叉",
                "script_only": True,
            },
        )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["content_type"] == "indicator"
    assert data["queued"] in (True, False)


def test_api_indicator_approved_script(client, tmp_path):
    script_json = tmp_path / "script.json"
    script_json.write_text(
        json.dumps({"title": "T", "segments": [{"text": "文本。"}]}), encoding="utf-8"
    )
    with patch("src.routes.videos.run_video_generation"):
        response = client.post(
            "/api/videos/generate",
            json={
                "type": "indicator",
                "approved_script": str(script_json),
            },
        )
    assert response.status_code == 200
    assert response.json()["data"]["content_type"] == "indicator"


def test_api_indicator_missing_manifest_rejected(client):
    response = client.post(
        "/api/videos/generate", json={"type": "indicator", "script_only": True}
    )
    assert response.status_code == 422
