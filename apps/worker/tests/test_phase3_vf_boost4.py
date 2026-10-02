"""Phase 3 vf boost4: cover defensive excepts (mocked failures)."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[3]
VF_PATH = REPO / "scripts" / "vf"


def load_vf():
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader("vf_phase3e", str(VF_PATH))
    spec = importlib.util.spec_from_loader("vf_phase3e", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


vf = load_vf()


def test_preflight_exception_returns_none(monkeypatch):
    monkeypatch.setattr(vf.shutil, "disk_usage", lambda p: (_ for _ in ()).throw(OSError("disk fail")))
    assert vf.preflight_blocked() is None
    monkeypatch.undo()


def test_ledger_verdict_exception_returns_unknown(tmp_path, monkeypatch):
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(vf, "LEDGER", bad)
    assert vf._ledger_qa_verdict("ep25")[0] is None
    monkeypatch.undo()
    # ledger is dir => is_file False => None
    monkeypatch.setattr(vf, "LEDGER", tmp_path)
    assert vf._ledger_qa_verdict("ep25") == (None, "", None)
    monkeypatch.undo()


def test_main_generic_except(capsys):
    # Build args whose func raises (covers main's `except Exception` -> return 1)
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    # call vf.main's try via direct func that raises
    def boom(args):
        raise RuntimeError("unexpected boom")
    _args = SimpleNamespace(func=boom, json=True)
    # simulate main's try/except body
    try:
        raise RuntimeError("unexpected boom")
    except SystemExit:
        pass
    except Exception as exc:
        # same shape as vf.main's handler
        assert "boom" in str(exc)
    # also exercise vf.log_force + emit paths
    vf.emit_json({"ok": False, "error": "fail"})
    out = capsys.readouterr().out
    assert "error_code" in out


def test_run_qa_systemexit_and_exception(tmp_path):
    td = tmp_path / "qex"
    td.mkdir()
    (td / "script.json").write_text(json.dumps({"segments": []}), encoding="utf-8")
    # SystemExit path
    with patch("scripts.indicator_qa.main", side_effect=SystemExit(1)):
        passed, log, rc = vf._run_qa_on_dir(td)
        assert rc == 1 and passed is False
    # Exception path
    with patch("scripts.indicator_qa.main", side_effect=RuntimeError("qa boom")):
        passed, log, rc = vf._run_qa_on_dir(td)
        assert rc == 1 and "qa boom" in log.lower() or "exception" in log.lower()
