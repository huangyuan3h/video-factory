"""Phase 3: uniform --resume / checkpoint helper. No network, no render."""
import json

from src.services import checkpoint as cp


def test_hash_inputs_stable_and_short(tmp_path):
    h1 = cp.hash_inputs("ep26", "topic", "2560x1440")
    h2 = cp.hash_inputs("ep26", "topic", "2560x1440")
    assert h1 == h2
    assert len(h1) == 12
    assert cp.hash_inputs("ep26", "other") != h1


def test_hash_file_roundtrip(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello", encoding="utf-8")
    h = cp.hash_file(f)
    assert h and len(h) == 12
    assert cp.hash_file(tmp_path / "missing.txt") is None


def test_save_load_should_skip(tmp_path):
    td = tmp_path / "task"
    assert cp.should_skip(td, "new-ep", "abc") is False
    cp.save_checkpoint(td, "new-ep", "abc")
    assert cp.should_skip(td, "new-ep", "abc") is True
    assert cp.should_skip(td, "new-ep", "other") is False
    assert cp.should_skip(td, "render", "abc") is False
    data = cp.load_checkpoint(td)
    assert data["new-ep"]["inputs_hash"] == "abc"


def test_status_is_done(tmp_path):
    td = tmp_path / "task2"
    td.mkdir()
    done, _ = cp.status_is_done(td)
    assert done is False
    (td / "status.json").write_text(json.dumps({"status": "script_ready"}), encoding="utf-8")
    done, data = cp.status_is_done(td)
    assert done is True
    (td / "status.json").write_text(json.dumps({"status": "failed"}), encoding="utf-8")
    done, _ = cp.status_is_done(td)
    assert done is False
    (td / "status.json").write_text("not json", encoding="utf-8")
    done, _ = cp.status_is_done(td)
    assert done is False


def test_check_resume_matrix(tmp_path):
    assert cp.check_resume(None, "new-ep", "x")["skip"] is False
    td = tmp_path / "task3"
    td.mkdir()
    assert cp.check_resume(td, "new-ep", "x") == {"skip": False, "reason": "not-done"}
    cp.save_checkpoint(td, "new-ep", "x")
    assert cp.check_resume(td, "new-ep", "x")["skip"] is True
    # status.json done always skips (conservative idempotency)
    (td / "status.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
    assert cp.check_resume(td, "new-ep", "different-hash")["skip"] is True
