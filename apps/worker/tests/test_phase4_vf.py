"""Phase 4 vf: explain / check / dry-run / funnel / list-types / next-hints (no render/TTS/upload)."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from src.services.error_codes import ALL_CODES, explain

REPO = Path(__file__).resolve().parents[3]
VF_PATH = REPO / "scripts" / "vf"


def load_vf(name="vf_phase4"):
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader(name, str(VF_PATH))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


vf = load_vf()


def _args(**kw):
    base = dict(code=None, ep=None, dir=None, json=True, resume=False, check_drift=False,
                n=None, topic=None, type="indicator", list_types=False,
                manifest=None, approved_script=None, script_only=False,
                resolution="2560x1440", out_dir=None, to=None, privacy="unlisted",
                draft_only=True, force=False, force_reason=None, execute=False,
                dry_run=False, check_funnel=False)
    base.update(kw)
    return SimpleNamespace(**base)


def _last_json(capsys):
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_explain_covers_every_code():
    for code in sorted(ALL_CODES):
        entry = explain(code)
        assert entry["code"] == code
        assert entry["cause"] and entry["fix"] and entry["next"], code
    assert explain(None)["code"] == "E_BLOCKED"
    assert explain("qa-fail")["code"] == "E_QA_FAIL"
    assert explain("CREDENTIALS")["code"] == "E_CREDENTIALS"


def test_explain_cli_known_and_unknown(capsys):
    assert vf.cmd_explain(_args(code="E_QA_FAIL")) == 0
    d = _last_json(capsys)
    assert d["code"] == "E_QA_FAIL" and "vf qa" in d["next"]
    assert vf.cmd_explain(_args(code="E_NOPE")) == 2
    assert vf.cmd_explain(_args()) == 0  # no arg lists all codes


def test_new_ep_list_types(capsys):
    assert vf.cmd_new_ep(_args(list_types=True)) == 0
    assert "indicator" in _last_json(capsys)["types"]


def test_new_ep_unknown_type_names_next(capsys):
    assert vf.cmd_new_ep(_args(n=26, topic="T", type="nope")) == 2
    assert _last_json(capsys)["hint"] == "vf new-ep --list-types"


def test_new_ep_dry_run_writes_nothing(tmp_path, capsys):
    out = tmp_path / "epdry"
    assert vf.cmd_new_ep(_args(n=91, topic="Dry run topic", script_only=True, out_dir=out, dry_run=True)) == 0
    assert _last_json(capsys)["dry_run"] is True
    assert not out.exists()


def test_render_dry_run_never_renders(tmp_path, capsys):
    task = tmp_path / "task"
    task.mkdir()
    task.joinpath("script.json").write_text(json.dumps({"segments": []}), encoding="utf-8")
    # Patch the pipeline entry: dry-run must never reach it (would raise if called).
    import src.services.cli_runner as runner
    called = []
    orig = runner.indicator_main
    runner.indicator_main = lambda argv: called.append(argv) or 0
    try:
        rc = vf.cmd_render(_args(ep="26", approved_script=task, dry_run=True))
    finally:
        runner.indicator_main = orig
    assert rc == 0
    assert called == []
    assert _last_json(capsys)["dry_run"] is True


def test_publish_check_funnel_never_publishes(capsys):
    rc = vf.cmd_publish(_args(ep="ep25", to="youtube", check_funnel=True, execute=True))
    assert rc == 2  # check + execute is contradictory usage
    rc = vf.cmd_publish(_args(ep="ep25", to="youtube", check_funnel=True))
    assert rc in (0, 1)  # 0 with tentative default funnel URL; 1 only if template regresses
    d = _last_json(capsys)
    assert "funnel_ok" in d and "missing" in d


def test_publish_unknown_platform_names_next(capsys):
    assert vf.cmd_publish(_args(ep="ep25", to="myspace")) == 2
    assert "hint" in _last_json(capsys)


def test_errors_always_carry_hint(capsys):
    vf.cmd_status(_args(ep="not-an-ep"))
    assert "hint" in _last_json(capsys)
    vf.cmd_qa(_args())
    assert "hint" in _last_json(capsys)


def test_check_all_green_and_fail_paths(capsys, monkeypatch):
    monkeypatch.setattr(vf, "_run_step", lambda cmd, cwd, timeout_s=100: (True, "ok"))
    monkeypatch.setattr(vf, "cmd_doctor", lambda args: 0)
    assert vf.cmd_check(_args()) == 0
    assert _last_json(capsys)["ok"] is True
    monkeypatch.setattr(vf, "_run_step", lambda cmd, cwd, timeout_s=100: (False, "boom"))
    assert vf.cmd_check(_args()) == 1
    assert _last_json(capsys)["ok"] is False


def test_new_ep_manifest_delegates_to_pipeline(tmp_path, capsys, monkeypatch):
    import src.services.cli_runner as runner

    seen = []
    monkeypatch.setattr(runner, "indicator_main", lambda argv: seen.append(argv) or 0)
    rc = vf.cmd_new_ep(_args(n=26, topic="Manifest ep", manifest=tmp_path, out_dir=tmp_path / "t", resume=True))
    assert rc == 0
    assert seen and "--manifest" in seen[0]
    d = _last_json(capsys)
    assert d["ep"] == "ep26" and d["exit"] == 0
    monkeypatch.setattr(runner, "indicator_main", lambda argv: 1)
    assert vf.cmd_new_ep(_args(n=26, topic="Manifest ep", manifest=tmp_path)) == 1


def test_render_full_path_delegates_after_qa(tmp_path, capsys, monkeypatch):
    import src.services.cli_runner as runner

    task = vf._write_script_only_task(tmp_path / "r26", "Render path topic", "ep26", "2560x1440")
    seen = []
    monkeypatch.setattr(runner, "indicator_main", lambda argv: seen.append(argv) or 0)
    monkeypatch.setattr(vf, "FORCE_LOG", tmp_path / "force_log.jsonl")
    rc = vf.cmd_render(_args(ep="26", approved_script=task))
    assert rc == 0
    assert seen and "--approved-script" in seen[0]
    capsys.readouterr()
    # QA-FAIL task with --force + reason still delegates and logs the reason.
    bad = tmp_path / "badforce"
    bad.mkdir()
    bad.joinpath("script.json").write_text(json.dumps({"segments": [{"text": "seed种子20260925", "key_point": "要点", "images": [], "motion": "none"}]}), encoding="utf-8")
    rc = vf.cmd_render(_args(ep="26", approved_script=bad, force=True, force_reason="test override"))
    assert rc == 0
    assert (tmp_path / "force_log.jsonl").is_file()


def test_publish_execute_path_stays_safe(capsys):
    rc = vf.cmd_publish(_args(ep="ep25", to="youtube", execute=True))
    assert rc == 0
    assert _last_json(capsys)["dry_run"] is False


def test_doctor_low_disk_exits_blocked(capsys, monkeypatch):
    from unittest.mock import MagicMock

    monkeypatch.setattr(vf.shutil, "disk_usage", lambda p: MagicMock(free=1 * 1024**3))
    assert vf.cmd_doctor(_args()) == 3
    assert _last_json(capsys)["error_code"] == "E_MEMORY"


def test_qa_exception_path_reports_fail(tmp_path, capsys, monkeypatch):
    task = tmp_path / "qaexc"
    task.mkdir()
    task.joinpath("script.json").write_text(json.dumps({"segments": []}), encoding="utf-8")
    import scripts.indicator_qa as qa_mod

    monkeypatch.setattr(qa_mod, "main", lambda argv: (_ for _ in ()).throw(RuntimeError("boom")))
    rc = vf.cmd_qa(_args(dir=str(task)))
    assert rc == 1
    assert _last_json(capsys)["error_code"] == "E_QA_FAIL"


def test_main_entry_and_failure_path(capsys, monkeypatch):
    assert vf.main(["explain", "E_OK", "--json"]) == 0
    capsys.readouterr()
    assert vf.main(["status", "--json"]) == 0
    capsys.readouterr()
    monkeypatch.setattr(vf, "cmd_status", lambda args: (_ for _ in ()).throw(RuntimeError("boom")))
    assert vf.main(["status", "--json"]) == 1


def test_venv_bootstrap_noop_when_flagged(monkeypatch):
    # _ensure_worker_venv only re-execs under __main__; in-process it must
    # return immediately when the loop-guard flag is set (never exec in tests).
    monkeypatch.setenv("VF_VENV_REEXEC", "1")
    assert vf._ensure_worker_venv() is None


def test_emit_json_default_code(capsys):
    vf.emit_json({"ok": False})
    assert _last_json(capsys)["error_code"] == "E_BLOCKED"
    vf.emit_json({"pass": True})
    assert _last_json(capsys)["error_code"] == "E_OK"


def test_preflight_tolerates_disk_error(monkeypatch):
    monkeypatch.setattr(vf.shutil, "disk_usage", lambda p: (_ for _ in ()).throw(OSError("x")))
    assert vf.preflight_blocked() is None


def test_qa_system_exit_path(tmp_path, capsys, monkeypatch):
    task = tmp_path / "qase"
    task.mkdir()
    task.joinpath("script.json").write_text(json.dumps({"segments": []}), encoding="utf-8")
    import scripts.indicator_qa as qa_mod

    monkeypatch.setattr(qa_mod, "main", lambda argv: (_ for _ in ()).throw(SystemExit(1)))
    assert vf.cmd_qa(_args(dir=str(task))) == 1


def test_list_types_human_and_qa_ledger_special_cases(tmp_path, capsys, monkeypatch):
    assert vf.cmd_new_ep(_args(list_types=True, json=False)) == 0
    capsys.readouterr()
    # Tmp ledger (no local video files) -> deterministic ledger-verdict mode.
    fake = {
        "ep12": {"title": "T12", "status": "ready", "qa": "视频PASS，上传FAIL", "video_path": None},
        "ep13": {"title": "T13", "status": "stopped", "qa": "stopped", "video_path": None},
    }
    led = tmp_path / "episodes.json"
    led.write_text(json.dumps({"meta": {}, "episodes": fake}), encoding="utf-8")
    monkeypatch.setattr(vf, "LEDGER", led)
    assert vf.cmd_qa(_args(ep="ep12", json=False)) == 0  # video PASS special case
    capsys.readouterr()
    assert vf.cmd_qa(_args(ep="ep13", json=False)) == 1
    capsys.readouterr()


def test_publish_force_without_reason_is_usage(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(vf, "FORCE_LOG", tmp_path / "force_log.jsonl")
    assert vf.cmd_publish(_args(ep="ep13", to="youtube", force=True)) == 2
    capsys.readouterr()
    assert vf.cmd_publish(_args(ep="ep13", to="youtube", force=True, force_reason="owner override test")) == 0
    assert (tmp_path / "force_log.jsonl").is_file()


def test_help_epilogs_have_examples():
    import io
    from contextlib import redirect_stdout

    parser = vf.build_parser()
    assert "vf new-ep" in parser.format_help() and "Exit codes" in parser.format_help()
    for sub in ("status", "new-ep", "render", "qa", "publish", "explain", "check", "doctor"):
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                parser.parse_args([sub, "--help"])
        except SystemExit as e:
            assert e.code == 0
        assert "EXAMPLES" in buf.getvalue(), sub
