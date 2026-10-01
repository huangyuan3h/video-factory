"""Phase 3: cli_runner pure logic (no network, no render; run_pipeline mocked)."""
import json
from pathlib import Path
from types import SimpleNamespace

from src.services import cli_runner as CR


def test_slugify_keeps_cjk():
    assert CR.slugify("首阴战法 test!") == "首阴战法-test"
    assert CR.slugify("") == "episode"
    assert CR.slugify(None) == "episode"


def test_default_out_dir_shape(tmp_path, monkeypatch):
    from src import config as cfg
    monkeypatch.setattr(cfg.settings, "output_dir", str(tmp_path))
    p = CR.default_out_dir("indicator", "首阴")
    assert str(tmp_path) in str(p) and "indicator" in str(p)


def test_read_status_missing_and_bad(tmp_path):
    assert CR.read_status(tmp_path / "nope") == {}
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "status.json").write_text("not json", encoding="utf-8")
    assert CR.read_status(bad) == {}
    good = tmp_path / "good"
    good.mkdir()
    (good / "status.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
    assert CR.read_status(good)["status"] == "completed"


def test_result_exit_code_and_video_path():
    assert CR.result_exit_code({"status": {"status": "completed"}}) == 0
    assert CR.result_exit_code({"status": {"status": "script_ready"}}) == 0
    assert CR.result_exit_code({"status": {"status": "failed"}}) == 1
    assert CR.resolve_video_path({"status": {"status": "failed"}}) is None
    r = {"status": {"status": "completed", "files": {"video": "/tmp/x.mp4"}}, "task_id": "none"}
    assert CR.resolve_video_path(r) == str(Path("/tmp/x.mp4").resolve())
    fmt = CR.format_result({"task_dir": "/tmp/t", "status": {"status": "completed"}, "task_id": "abc"})
    assert "TASK_DIR:" in fmt and "abc" in fmt


def test_indicator_parser_requires_manifest_or_approved():
    p = CR.build_indicator_parser()
    args = p.parse_args(["--title", "T"])
    assert not args.manifest and not args.approved_script
    # indicator_main with neither => argparse error (SystemExit 2)
    try:
        CR.indicator_main(["--title", "T"])
        assert False
    except SystemExit as e:
        assert e.code == 2


def test_build_indicator_request_validation():
    p = CR.build_indicator_parser()
    args = p.parse_args(["--title", "T"])
    try:
        CR.build_indicator_request(args)
        assert False
    except ValueError:
        pass


def test_build_generic_request_series(tmp_path):
    eps = [{"index": 2, "title": "第二章", "content": "正文", "series_id": "s1"}]
    f = tmp_path / "eps.json"
    f.write_text(json.dumps(eps), encoding="utf-8")
    p = CR.build_generic_parser()
    args = p.parse_args(["--type", "book", "--series-episodes", str(f), "--episode-index", "2"])
    req, name = CR.build_generic_request(args)
    assert name == "第二章"
    assert req.content == "正文"
    # missing index raises
    args2 = p.parse_args(["--type", "book", "--series-episodes", str(f), "--episode-index", "99"])
    try:
        CR.build_generic_request(args2)
        assert False
    except ValueError:
        pass


def test_run_cli_reports_error_without_render(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("backend overloaded 503")
    monkeypatch.setattr(CR, "run_pipeline", boom)
    req = SimpleNamespace(model_dump=lambda: {}, content_type="general")
    rc = CR._run_cli(req, "/tmp/vf-test-dir", "name", "general")
    assert rc == 1
