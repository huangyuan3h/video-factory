"""Phase 3: ledger/migration pure logic (read-only sources). No network."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))

import migrate_ledger as ml


def test_parse_topics_compact_and_fallback(tmp_path):
    main = tmp_path / "main"
    (main / ".opencode-runs").mkdir(parents=True)
    (main / ".opencode-runs" / "series_topics.md").write_text(
        "已做：\n- ep1 MACD 金叉；ep2 KDJ 金叉\n试过放弃：无\n",
        encoding="utf-8",
    )
    out = ml.parse_topics(main)
    assert out["ep1"]["topic"] and out["ep2"]["topic"]
    # fallback ids + ep1-25 keys exist
    for i in range(1, 26):
        assert f"ep{i}" in out and out[f"ep{i}"]["id"]


def test_parse_topics_detailed_line(tmp_path):
    main = tmp_path / "main2"
    (main / ".opencode-runs").mkdir(parents=True)
    (main / ".opencode-runs" / "series_topics.md").write_text(
        "- ep11 红三兵三连阳 id red_three_soldiers（svx4fGHuGY0，ok\n",
        encoding="utf-8",
    )
    out = ml.parse_topics(main)
    assert out["ep11"]["id"] == "red_three_soldiers"
    assert "红三兵" in out["ep11"]["topic"]


def test_parse_done_log_last_wins_and_yid(tmp_path):
    main = tmp_path / "main3"
    (main / ".opencode-runs").mkdir(parents=True)
    (main / ".opencode-runs" / "series_done.log").write_text(
        "ep11 | 旧标题 | https://youtu.be/AAA111AAA11 | PASS | 2026-09-01\n"
        "ep11 | 新标题 | https://youtu.be/BBB222BBB22 | PASS | 2026-10-01\n",
        encoding="utf-8",
    )
    out = ml.parse_done_log(main)
    assert out["ep11"]["youtube_id"] == "BBB222BBB22"
    assert out["ep11"]["title"] == "新标题"


def test_parse_narrative_and_yt_titles(tmp_path):
    main = tmp_path / "main4"
    (main / ".opencode-runs").mkdir(parents=True)
    (main / ".opencode-runs" / "narrative_devices.md").write_text(
        "- ep24 猴子对赌：和猴子打赌\n", encoding="utf-8"
    )
    (main / ".opencode-runs" / "ep" / "yt").mkdir(parents=True)
    (main / ".opencode-runs" / "ep" / "yt" / "ep24.json").write_text(
        json.dumps({"title": "T", "description": "D", "tags": ["a"]}), encoding="utf-8"
    )
    assert ml.parse_narrative(main)["ep24"]["narrative_topic"] == "猴子对赌"
    assert ml.parse_yt_titles(main)["ep24"]["title"] == "T"


def test_migrate_end_to_end_tmp(tmp_path):
    main = tmp_path / "main5"
    (main / ".opencode-runs").mkdir(parents=True)
    (main / ".opencode-runs" / "series_topics.md").write_text("已做：\n- ep1 MACD 金叉\n", encoding="utf-8")
    (main / ".opencode-runs" / "series_done.log").write_text(
        "ep1 | 标题一 | https://youtu.be/AAA111AAA11 | PASS | 2026-09-01\n", encoding="utf-8"
    )
    (main / ".opencode-runs" / "narrative_devices.md").write_text("- ep1 直讲：plain\n", encoding="utf-8")
    karios = tmp_path / "karios"
    (karios / "zhihu").mkdir(parents=True)
    (karios / "zhihu" / "queue.json").write_text(json.dumps({"queue": [], "items": []}), encoding="utf-8")
    (karios / "zhihu" / "published.json").write_text(
        json.dumps({"episodes": {}, "published_eps": []}), encoding="utf-8"
    )
    (karios / "bili_ready.json").write_text(json.dumps({}), encoding="utf-8")
    out = tmp_path / "episodes.json"
    rc = ml.main(["--main", str(main), "--karios", str(karios), "--out", str(out)])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["episodes"]) == 25
    assert data["episodes"]["ep1"]["youtube"]["id"] == "AAA111AAA11"
    assert data["meta"]["default_resolution"].startswith("2560x1440")


def test_migrate_never_writes_old_ledgers(tmp_path):
    main = tmp_path / "main6"
    (main / ".opencode-runs").mkdir(parents=True)
    topics = main / ".opencode-runs" / "series_topics.md"
    topics.write_text("已做：\n- ep1 MACD 金叉\n", encoding="utf-8")
    before = topics.read_text(encoding="utf-8")
    karios = tmp_path / "k6"
    (karios / "zhihu").mkdir(parents=True)
    for p, content in [
        (karios / "zhihu" / "queue.json", "{}"),
        (karios / "zhihu" / "published.json", "{}"),
        (karios / "bili_ready.json", "{}"),
    ]:
        p.write_text(content, encoding="utf-8")
    befores = {str(p): p.read_text(encoding="utf-8") for p in [karios / "zhihu" / "queue.json"]}
    ml.main(["--main", str(main), "--karios", str(karios), "--out", str(tmp_path / "o.json")])
    assert topics.read_text(encoding="utf-8") == before
    for k, v in befores.items():
        assert Path(k).read_text(encoding="utf-8") == v
