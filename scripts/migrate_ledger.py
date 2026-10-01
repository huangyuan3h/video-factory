#!/usr/bin/env python3
"""Migrate scattered ledgers into single state/episodes.json (READ-ONLY sources).

Reads (never modifies):
- <main>/.opencode-runs/series_topics.md
- <main>/.opencode-runs/series_done.log
- <main>/.opencode-runs/narrative_devices.md
- <main>/.opencode-runs/ep/yt/epN.json (titles)
- ~/Projects/karios-series-output/zhihu/queue.json
- ~/Projects/karios-series-output/zhihu/published.json
- ~/Projects/karios-series-output/bili_ready.json

Writes:
- state/episodes.json (repo root, i.e. ../state/episodes.json from apps/worker
  or ./state/episodes.json from repo root)

Old ledgers stay as they are (routines still use them).
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MAIN = Path("/Users/huangyuan/Projects/video-factory")
DEFAULT_KARIOS = Path("/Users/huangyuan/Projects/karios-series-output")


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def parse_topics(main: Path) -> dict:
    """ep -> {topic, id, youtube_id} best-effort from series_topics.md."""
    out: dict[str, dict] = {}
    f = main / ".opencode-runs" / "series_topics.md"
    if not f.is_file():
        return out
    txt = _read(f)
    # Detailed lines: "- ep11 红三兵三连阳 id red_three_soldiers（svx4fGHuGY0，..."
    for m in re.finditer(
        r"ep(\d+)\s+([^\s（\(]+[^\（\(]*?)\s+id\s+([A-Za-z0-9_]+)\s*[（\(]([A-Za-z0-9_\-]{5,})?",
        txt,
    ):
        ep = f"ep{m.group(1)}"
        out.setdefault(ep, {})["topic"] = m.group(2).strip()[:80]
        out[ep]["id"] = m.group(3).strip()
        if m.group(4):
            out[ep].setdefault("youtube_id_hint", m.group(4).strip())
    # Compact ep1-10 line: "- ep1 MACD 金叉；ep2 KDJ 金叉；..."
    for m in re.finditer(r"ep(\d+)\s+([^；，,；\n]+)", txt.split("已做")[1].split("试过放弃")[0] if "已做" in txt else txt):
        ep = f"ep{m.group(1)}"
        if ep not in out or not out[ep].get("topic"):
            out.setdefault(ep, {})["topic"] = m.group(2).strip()[:80]
    # Fallback ids for ep1-10 from known queue/bili naming when missing
    fallback_ids = {
        "ep1": "ep1_macd_golden_cross",
        "ep2": "ep2_kdj_oversold",
        "ep3": "ep3_holiday_effect",
        "ep4": "ep4_pin_bar_hammer",
        "ep5": "ep5_bull_ma10_pullback",
        "ep6": "ep6_bollinger_lower",
        "ep7": "ep7_limitup_chase",
        "ep8": "ep8_gap_down_fill",
        "ep9": "ep9_ma5_20_golden_cross",
        "ep10": "ep10_breakout_20d_high",
        "ep12": "ep12_one_yang_three_lines",
        "ep13": "ep13_stopped",
        "ep14": "ep14_consecutive_yang_chase",
    }
    for ep, fid in fallback_ids.items():
        out.setdefault(ep, {}).setdefault("id", fid)
    # Ensure ep1-25 keys exist (ep13 stopped)
    for i in range(1, 26):
        out.setdefault(f"ep{i}", {}).setdefault("id", f"ep{i}")
        out[f"ep{i}"].setdefault("topic", "")
    return out


def parse_done_log(main: Path) -> dict:
    """ep -> latest {title, youtube_id, youtube_url, qa, date} (last occurrence wins)."""
    out: dict[str, dict] = {}
    f = main / ".opencode-runs" / "series_done.log"
    if not f.is_file():
        return out
    for line in _read(f).splitlines():
        line = line.strip()
        if not line.startswith("ep"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        ep = parts[0].split()[0]
        title = parts[1] if len(parts) > 1 else ""
        link = parts[2] if len(parts) > 2 else ""
        qa = parts[3] if len(parts) > 3 else ""
        date = parts[4] if len(parts) > 4 else ""
        m = re.search(r"(https?://youtu\.be/[A-Za-z0-9_\-]+)", link)
        yid = m.group(1).split("/")[-1] if m else None
        # bare ID in link field (should not happen, but be safe)
        if not yid:
            m2 = re.search(r"\b([A-Za-z0-9_\-]{11})\b", link)
            if m2:
                yid = m2.group(1)
        out[ep] = {
            "title": title,
            "youtube_id": yid,
            "youtube_url": m.group(1) if m else (None if "未上传" in link and "无链接" in link else (link if link.startswith("http") else None)),
            "qa": qa,
            "date": date,
            "raw_link": link,
        }
    return out


def parse_narrative(main: Path) -> dict:
    out: dict[str, dict] = {}
    f = main / ".opencode-runs" / "narrative_devices.md"
    if not f.is_file():
        return out
    for line in _read(f).splitlines():
        m = re.match(r"\s*-\s*(ep\d+)\s+([^：:]+)[：:]\s*(.+)", line.strip())
        if m:
            out[m.group(1)] = {"narrative_topic": m.group(2).strip(), "narrative": m.group(3).strip()[:200]}
    return out


def parse_yt_titles(main: Path) -> dict:
    out: dict[str, dict] = {}
    d = main / ".opencode-runs" / "ep" / "yt"
    if not d.is_dir():
        return out
    for p in sorted(d.glob("ep*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            ep = p.stem
            out[ep] = {"title": data.get("title", ""), "description": (data.get("description") or "")[:200], "tags": data.get("tags", [])[:5]}
        except Exception:
            continue
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Migrate ledgers to state/episodes.json (read-only sources)")
    ap.add_argument("--main", type=Path, default=DEFAULT_MAIN, help="Main checkout (read-only)")
    ap.add_argument("--karios", type=Path, default=DEFAULT_KARIOS, help="karios-series-output (read-only)")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "state" / "episodes.json", help="Output ledger")
    args = ap.parse_args(argv)

    topics = parse_topics(args.main)
    done = parse_done_log(args.main)
    narr = parse_narrative(args.main)
    titles = parse_yt_titles(args.main)

    queue: dict = {}
    published: dict = {}
    bili: dict = {}
    try:
        queue = json.loads((args.karios / "zhihu" / "queue.json").read_text(encoding="utf-8"))
    except Exception:
        queue = {}
    try:
        published = json.loads((args.karios / "zhihu" / "published.json").read_text(encoding="utf-8"))
    except Exception:
        published = {}
    try:
        bili = json.loads((args.karios / "bili_ready.json").read_text(encoding="utf-8"))
    except Exception:
        bili = {}

    q_items = {it.get("ep"): it for it in (queue.get("items") or []) if isinstance(it, dict)}
    q_pending = set(queue.get("queue") or [])
    zh_episodes = published.get("episodes") or {}
    zh_published_eps = set(published.get("published_eps") or [])

    episodes: dict[str, dict] = {}
    for i in range(1, 26):
        ep = f"ep{i}"
        t = topics.get(ep, {})
        d = done.get(ep, {})
        n = narr.get(ep, {})
        yt = titles.get(ep, {})
        qi = q_items.get(ep, {})
        yid = d.get("youtube_id") or qi.get("youtube_id") or t.get("youtube_id_hint")
        yurl = d.get("youtube_url") or (f"https://youtu.be/{yid}" if yid else None)
        b = bili.get(ep, {}) if isinstance(bili.get(ep), dict) else {}
        title = d.get("title") or yt.get("title") or qi.get("title") or t.get("topic", "")
        # qa: series_done.log PASS wins; ep13 stopped; ep12 upload FAIL but video PASS
        qa = d.get("qa") or ""
        if ep == "ep13":
            status = "stopped"
            qa = qa or "未做视频 (4候选均不满足三条)"
        elif yid or b.get("bvid") or ep in zh_published_eps:
            status = "published" if ("PASS" in qa or ep in zh_published_eps or b.get("published")) else "ready"
        elif ep in q_pending or qi:
            status = "queued"
        else:
            status = "ready" if title else "unknown"
        episodes[ep] = {
            "ep": ep,
            "id": t.get("id") or qi.get("id") or f"ep{i}",
            "topic": t.get("topic") or "",
            "title": title,
            "research_commit": None,
            "script_sha": None,
            "video_path": b.get("mp4"),
            "qa": qa,
            "status": status,
            "narrative": n.get("narrative", ""),
            "youtube": {"id": yid, "url": yurl, "status": ("unlisted-or-public" if yid else None)},
            "bili": {"bvid": b.get("bvid"), "url": b.get("url"), "status": b.get("status")},
            "zhihu": {
                "url": (zh_episodes.get(ep) or {}).get("url") if isinstance(zh_episodes.get(ep), dict) else None,
                "published": ep in zh_published_eps,
                "queued": ep in q_pending,
                "queue_title": qi.get("title"),
            },
            "toutiao": {"status": "draft-only"},
        }

    payload = {
        "meta": {
            "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "sources": [
                "karios-series-output/zhihu/queue.json",
                "karios-series-output/zhihu/published.json",
                "karios-series-output/bili_ready.json",
                ".opencode-runs/series_done.log",
                ".opencode-runs/series_topics.md",
                ".opencode-runs/narrative_devices.md",
                ".opencode-runs/ep/yt/ep*.json",
            ],
            "note": "Read-only migration snapshot. Old ledgers remain source of truth for daily routines; do not edit them. Routines still use them.",
            "default_resolution": "2560x1440 CRF17 (1440p)",
        },
        "episodes": episodes,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"WROTE {args.out} with {len(episodes)} episodes (ep1-25)")
    # Final JSON line for --json consumers
    print(json.dumps({"ok": True, "episodes": len(episodes), "out": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
