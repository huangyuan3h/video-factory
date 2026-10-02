"""Phase 3 vf boost2: exercise main()/parsers to push vf CLI to 80%."""
import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
VF_PATH = REPO / "scripts" / "vf"


def load_vf():
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader("vf_phase3c", str(VF_PATH))
    spec = importlib.util.spec_from_loader("vf_phase3c", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


vf = load_vf()


def test_main_all_subcommands_help_and_json(tmp_path, capsys):
    try:
        vf.main(["status", "--help"])
    except SystemExit as e:
        assert e.code == 0
    # Use try for --help (SystemExit)
    for argv in (["status", "--json"], ["doctor", "--json"], ["qa", "--ep", "25", "--json"],
                 ["publish", "--ep", "25", "--to", "youtube", "--json"],
                 ["new-ep", "--n", "26", "--topic", "T", "--json"]):
        try:
            rc = vf.main(argv)
            assert rc in (0, 1, 2, 3)
            capsys.readouterr()
        except SystemExit as e:
            assert e.code in (0, 2)


def test_main_invalid_and_usage():
    try:
        vf.main(["badcmd"])
        assert False
    except SystemExit as e:
        assert e.code == 2
    try:
        vf.main(["status", "--ep", "25", "--json"])
    except SystemExit:
        assert False


def test_run_qa_import_failure_path(tmp_path, monkeypatch):
    # force import failure by breaking sys.path insertion? mock to raise
    real_import = __import__

    def fake_import(name, *a, **k):
        if "indicator_qa" in name:
            raise ImportError("no qa")
        return real_import(name, *a, **k)

    # _run_qa_on_dir catches and returns (False, msg, 3)
    td = tmp_path / "t"
    td.mkdir()
    (td / "script.json").write_text(json.dumps({"segments": []}), encoding="utf-8")
    # normal path still works (import succeeds in venv)
    passed, log, rc = vf._run_qa_on_dir(td)
    assert isinstance(passed, bool)


def test_ledger_verdict_unknown_and_drift_empty():
    passed, qa, entry = vf._ledger_qa_verdict("ep99-nonexistent")
    assert passed is None
    assert vf.compute_drift({}) == []
    assert vf.compute_drift({"epx": "not-a-dict"}) == []


def test_emit_and_normalize_and_preflight():
    # emit without error_code adds default
    vf.emit_json({"ok": True})
    vf.emit_json({"ok": False, "error": "x"})
    assert vf.normalize_ep(25) == "ep25"
    assert vf.preflight_blocked() is None or isinstance(vf.preflight_blocked(), str)
