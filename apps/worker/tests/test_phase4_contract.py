"""Phase 4 contract: state/episodes.json + vf --json shapes (stdlib only, no network)."""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
LEDGER = REPO / "state" / "episodes.json"

REQUIRED_ENTRY_KEYS = {"ep", "title", "status", "qa", "youtube", "bili", "zhihu", "toutiao"}
VALID_STATUSES = {"published", "ready", "stopped"}


def _load():
    assert LEDGER.is_file(), "state/episodes.json missing (run scripts/migrate_ledger.py)"
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def test_ledger_meta():
    data = _load()
    assert set(("meta", "episodes")) <= set(data.keys())
    assert data["meta"]["generated_at"]
    assert isinstance(data["meta"]["sources"], list) and data["meta"]["sources"]
    assert "1440" in data["meta"].get("default_resolution", "")


def test_ledger_entries_conform():
    eps = _load()["episodes"]
    assert len(eps) >= 25
    for key, e in eps.items():
        assert key == e["ep"], key
        assert REQUIRED_ENTRY_KEYS <= set(e.keys()), key
        assert e["status"] in VALID_STATUSES, key
        assert isinstance(e["qa"], str), key
        for plat in ("youtube", "bili", "zhihu", "toutiao"):
            assert isinstance(e[plat], dict), (key, plat)


def test_ledger_stopped_entries_have_no_video():
    for key, e in _load()["episodes"].items():
        if e["status"] == "stopped":
            assert e["video_path"] is None, key


def test_vf_json_outputs_carry_error_code():
    import importlib.util
    from importlib.machinery import SourceFileLoader
    from types import SimpleNamespace

    loader = SourceFileLoader("vf_phase4c", str(REPO / "scripts" / "vf"))
    spec = importlib.util.spec_from_loader("vf_phase4c", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)

    def args(**kw):
        base = dict(code=None, ep=None, dir=None, json=True, resume=False, check_drift=False,
                    n=None, topic=None, type="indicator", list_types=False, manifest=None,
                    approved_script=None, script_only=False, resolution="2560x1440", out_dir=None,
                    to=None, privacy="unlisted", draft_only=True, force=False, force_reason=None,
                    execute=False, dry_run=True, check_funnel=False)
        base.update(kw)
        return SimpleNamespace(**base)

    import io
    from contextlib import redirect_stdout

    for fn, kw in (
        (mod.cmd_status, {}),
        (mod.cmd_explain, {"code": "E_OK"}),
        (mod.cmd_new_ep, {"list_types": True}),
        (mod.cmd_publish, {"ep": "ep25", "to": "youtube"}),
    ):
        buf = io.StringIO()
        with redirect_stdout(buf):
            fn(args(**kw))
        last = json.loads(buf.getvalue().strip().splitlines()[-1])
        assert "error_code" in last, kw
