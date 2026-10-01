"""Phase 3 boost5: cover last indicator_qa branches (light)."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import indicator_qa as QA


def test_qa_except_paths(tmp_path):
    td = tmp_path / "x"
    td.mkdir()
    # bad script.json => _read_key_points returns [], _find_card_images pass
    (td / "script.json").write_text("not json", encoding="utf-8")
    assert QA._read_key_points(td) == []
    assert QA._find_card_images(td) == []
    # _parse_ass_cues bad file (unreadable? use dir as file to trigger except)
    bad = tmp_path / "baddir"
    bad.mkdir()
    # _read_transcript with bad ASS (binary that fails decode? use permission? just call with dir)
    assert QA._read_transcript(bad) == []
    # main with bad script.json => FAIL 1 (covers _read_segments except)
    assert QA.main([str(td)]) == 1


def test_qa_mp3_duration_path(tmp_path):
    td = tmp_path / "m"
    td.mkdir()
    (td / "script.json").write_text(json.dumps({"segments": [
        {"text": "接下来，开场先看结论。", "key_point": "k", "images": [], "motion": "none"},
    ]}), encoding="utf-8")
    (td / "segment_0.mp3").write_bytes(b"fake mp3")
    with patch("subprocess.run") as mr:
        mr.return_value = MagicMock(stdout="12.5")
        assert QA.main([str(td)]) == 0
    with patch("subprocess.run", side_effect=RuntimeError("ffprobe missing")):
        assert QA.main([str(td)]) == 0
