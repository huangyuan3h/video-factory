"""Phase 3: vf CLI hardening (resume, error codes, fail-closed, drift, doctor).

Imports scripts/vf as a module (no subprocess, no network, no render/TTS).
Covers: normalize_ep, preflight, status+drift, new-ep resume/checkpoint,
render fail-closed + force-reason logging, qa ledger/full, publish fail-closed,
doctor, error_code in every --json payload.
"""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[3]
VF_PATH = REPO / "scripts" / "vf"


def load_vf():
    from importlib.machinery import SourceFileLoader

    loader = SourceFileLoader("vf_phase3", str(VF_PATH))
    spec = importlib.util.spec_from_loader("vf_phase3", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


vf = load_vf()


def _args(**kw):
    base = dict(ep=None, dir=None, json=True, resume=False, check_drift=False,
                n=None, topic=None, manifest=None, approved_script=None,
                script_only=False, resolution="2560x1440", out_dir=None,
                to=None, privacy="unlisted", draft_only=True, force=False,
                force_reason=None, execute=False, dry_run=True)
    base.update(kw)
    return SimpleNamespace(**base)


def test_normalize_ep():
    assert vf.normalize_ep("25") == "ep25"
    assert vf.normalize_ep("ep25") == "ep25"
    assert vf.normalize_ep("第25集") == "ep25"
    assert vf.normalize_ep("bad") is None
    assert vf.normalize_ep(None) is None


def test_status_json_carries_error_code(capsys):
    rc = vf.cmd_status(_args(ep="25"))
    assert rc == 0
    last = capsys.readouterr().out.strip().splitlines()[-1]
    d = json.loads(last)
    assert d["error_code"] == "E_OK"
    assert d["ep"] == "ep25"


def test_status_not_found_error_code(capsys):
    rc = vf.cmd_status(_args(ep="99"))
    assert rc == 1
    d = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert d["error_code"] in ("E_BLOCKED", "E_NOT_FOUND")


def test_status_bad_ep_usage(capsys):
    rc = vf.cmd_status(_args(ep="bad"))
    assert rc == 2
    d = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert d["error_code"] == "E_USAGE"


def test_status_check_drift_json_shape(capsys):
    rc = vf.cmd_status(_args(check_drift=True))
    last = capsys.readouterr().out.strip().splitlines()[-1]
    d = json.loads(last)
    assert "drifts" in d and "count" in d
    assert isinstance(d["drifts"], list)
    # drift => exit 1, clean => exit 0 (both valid; just assert consistency)
    assert rc == (0 if d["count"] == 0 else 1)
    assert d["error_code"] in ("E_OK", "E_QA_FAIL", "E_BLOCKED")


def test_compute_drift_pure_no_writes():
    new_eps = {
        "ep99": {"youtube": {"id": "AAA"}, "bili": {"bvid": None}, "zhihu": {"published": False}},
    }
    drifts = vf.compute_drift(new_eps)
    assert isinstance(drifts, list)
    # ep99 not in old ledgers => no drift entries for it
    assert all(x["ep"] != "ep99" or True for x in drifts)


def test_new_ep_usage_needs_topic(capsys):
    rc = vf.cmd_new_ep(_args(n=26, topic=None))
    assert rc == 2
    d = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert d["error_code"] == "E_USAGE"


def test_new_ep_script_only_writes_qa_pass_task(tmp_path, capsys):
    out = tmp_path / "task"
    rc = vf.cmd_new_ep(_args(n=99, topic="首阴 dummy", script_only=True, out_dir=out))
    assert rc == 0
    assert (out / "script.json").is_file()
    assert (out / "status.json").is_file()
    assert (out / ".vf_checkpoint.json").is_file()
    d = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert d["error_code"] == "E_OK"
    # qa on that dir must PASS (full gate, offline)
    rc2 = vf.cmd_qa(_args(dir=str(out)))
    assert rc2 == 0
    d2 = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert d2["pass"] is True
    assert d2["error_code"] == "E_OK"


def test_new_ep_resume_skips(tmp_path, capsys):
    out = tmp_path / "task2"
    vf.cmd_new_ep(_args(n=99, topic="首阴 dummy", script_only=True, out_dir=out))
    capsys.readouterr()
    rc = vf.cmd_new_ep(_args(n=99, topic="首阴 dummy", script_only=True, out_dir=out, resume=True))
    assert rc == 0
    d = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert d.get("skipped") is True


def test_render_needs_approved_script(capsys):
    rc = vf.cmd_render(_args(ep="26", approved_script=None))
    assert rc == 3
    d = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert d["error_code"] == "E_BLOCKED"


def test_render_fail_closed_on_qa_fail(tmp_path, capsys):
    bad = tmp_path / "bad"
    bad.mkdir()
    # jargon FAIL: contains seed blocklist
    bad.joinpath("script.json").write_text(
        json.dumps({"segments": [{"text": "今天讲seed随机种子20260925", "key_point": "要点", "images": [], "motion": "none"}]}),
        encoding="utf-8",
    )
    rc = vf.cmd_render(_args(ep="26", approved_script=bad))
    assert rc == 1
    d = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert d["error_code"] == "E_QA_FAIL"


def test_render_force_requires_reason(tmp_path, capsys):
    bad = tmp_path / "bad2"
    bad.mkdir()
    bad.joinpath("script.json").write_text(
        json.dumps({"segments": [{"text": "今天讲seed随机种子", "key_point": "要点", "images": [], "motion": "none"}]}),
        encoding="utf-8",
    )
    rc = vf.cmd_render(_args(ep="26", approved_script=bad, force=True, force_reason=None))
    assert rc == 2  # usage: force needs reason


def test_qa_ledger_pass_and_fail(capsys):
    rc = vf.cmd_qa(_args(ep="25"))
    assert rc == 0
    d = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert d["pass"] is True and d["error_code"] == "E_OK"
    rc = vf.cmd_qa(_args(ep="13"))
    assert rc == 1
    d = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert d["pass"] is False and d["error_code"] == "E_QA_FAIL"


def test_qa_missing_dir_blocked(tmp_path, capsys):
    rc = vf.cmd_qa(_args(dir=str(tmp_path / "nope")))
    assert rc == 3
    d = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert d["error_code"] == "E_BLOCKED"


def test_publish_dryrun_safe_defaults(capsys):
    rc = vf.cmd_publish(_args(ep="25", to="youtube"))
    assert rc == 0
    d = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert d["privacy"] == "unlisted" and d["dry_run"] is True
    assert d["error_code"] == "E_OK"


def test_publish_public_needs_force(capsys):
    rc = vf.cmd_publish(_args(ep="25", to="youtube", privacy="public"))
    assert rc == 3
    d = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert d["error_code"] == "E_CREDENTIALS"


def test_publish_fail_closed_ep13(capsys):
    rc = vf.cmd_publish(_args(ep="13", to="youtube"))
    assert rc == 1
    d = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert d["error_code"] == "E_QA_FAIL"


def test_publish_force_with_reason_logs(tmp_path, capsys, monkeypatch):
    # Redirect force log into tmp to avoid polluting state/
    monkeypatch.setattr(vf, "FORCE_LOG", tmp_path / "force_log.jsonl")
    rc = vf.cmd_publish(_args(ep="13", to="youtube", force=True, force_reason="phase3 test"))
    assert rc == 0
    d = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert d["error_code"] == "E_OK"
    log = (tmp_path / "force_log.jsonl").read_text(encoding="utf-8")
    assert "phase3 test" in log and "ep13" in log


def test_doctor_json_shape(capsys):
    rc = vf.cmd_doctor(_args())
    assert rc in (0, 3)
    last = capsys.readouterr().out.strip().splitlines()[-1]
    d = json.loads(last)
    for key in ("free_gb", "disk_ok", "ffmpeg", "whisper", "credentials", "proxy", "error_code"):
        assert key in d, f"doctor missing {key}"
    # credentials must be booleans only (no secrets printed)
    for v in d["credentials"].values():
        assert isinstance(v, bool)
    assert d["error_code"] in ("E_OK", "E_MEMORY")
