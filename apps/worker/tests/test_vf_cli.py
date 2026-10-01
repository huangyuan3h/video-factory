"""Light tests for vf CLI skeleton + single ledger (no render/TTS/upload/publish/Whisper)."""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
VF = REPO / "scripts" / "vf"
LEDGER = REPO / "state" / "episodes.json"


def run(*argv):
    p = subprocess.run([str(VF), *argv], capture_output=True, text=True, timeout=30)
    return p


def test_ledger_exists_and_has_ep1_25():
    assert LEDGER.is_file(), "state/episodes.json missing (run scripts/migrate_ledger.py)"
    data = json.loads(LEDGER.read_text(encoding="utf-8"))
    eps = data.get("episodes", {})
    for i in list(range(1, 13)) + list(range(14, 26)):
        assert f"ep{i}" in eps, f"missing ep{i}"
    assert "ep13" in eps
    assert "ep25" in json.dumps(data, ensure_ascii=False)


def test_vf_status_help_ok():
    p = run("status", "--help")
    assert p.returncode == 0


def test_vf_qa_help_ok():
    p = run("qa", "--help")
    assert p.returncode == 0


def test_vf_new_ep_help_ok():
    p = run("new-ep", "--help")
    assert p.returncode == 0


def test_vf_status_json_has_ep25():
    p = run("status", "--json")
    assert p.returncode == 0
    last = p.stdout.strip().splitlines()[-1]
    d = json.loads(last)
    assert "ep25" in json.dumps(d, ensure_ascii=False)


def test_vf_qa_finished_ep_json_pass():
    p = run("qa", "--ep", "25", "--json")
    last = p.stdout.strip().splitlines()[-1]
    d = json.loads(last)
    assert d.get("pass") is True
    assert p.returncode == 0


def test_vf_publish_defaults_safe_dryrun():
    p = run("publish", "--ep", "25", "--to", "youtube", "--json")
    assert p.returncode == 0
    d = json.loads(p.stdout.strip().splitlines()[-1])
    assert d.get("privacy") == "unlisted"
    assert d.get("dry_run") is True
    p2 = run("publish", "--ep", "25", "--to", "toutiao", "--json")
    d2 = json.loads(p2.stdout.strip().splitlines()[-1])
    assert d2.get("draft_only") is True


def test_vf_exit_codes():
    assert run("new-ep", "--n", "26", "--json").returncode == 2
    assert run("render", "--ep", "26", "--json").returncode == 3
    assert run("publish", "--ep", "25", "--to", "youtube", "--privacy", "public", "--json").returncode == 3
    assert run("status", "--ep", "99", "--json").returncode == 1
