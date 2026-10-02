"""P0 MVP orchestrator: snapshot -> topic -> script -> factcheck -> render."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path

from .data_card import render_data_card
from .factcheck import factcheck_script
from .materials import fetch_pexels_videos_with_attribution
from .script_builder import build_script, write_script_files
from .snapshot import brief_id, fetch_karios_snapshot, load_snapshot
from .topic import pick_finance_topic

DATA_CARD_SEGMENT = 2  # 0-based: segment 3 (data) gets the Karios card


def _write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


async def run_mvp(
    task_dir: str | Path,
    karios_base: str = "http://127.0.0.1:4330",
    snapshot_path: str | Path | None = None,
    pexels_api_key: str | None = None,
    render: bool = True,
) -> dict:
    """Run S0-S8. Returns dict with paths + checks. Raises on factcheck FAIL."""
    task = Path(task_dir)
    task.mkdir(parents=True, exist_ok=True)

    # S0 snapshot
    if snapshot_path:
        snap = load_snapshot(snapshot_path)
        _write_json(task / "karios_snapshot.json", snap)
    else:
        fetch_karios_snapshot(karios_base, task / "karios_snapshot.json")
        snap = load_snapshot(task / "karios_snapshot.json")

    # S1 topic
    topic = pick_finance_topic(snap)
    _write_json(task / "topic.json", topic)

    # S2 script
    script, md = build_script(topic, snap)
    write_script_files(script, md, task)

    # S3 factcheck gate
    passed, fc_md = factcheck_script(script, snap, topic)
    (task / "factcheck.md").write_text(fc_md, encoding="utf-8")
    if not passed:
        raise ValueError("事实核对 FAIL，不许进渲染")

    # S4 materials (Pexels video-led; data-card segment skipped here)
    cand_dir = task / "candidates"
    search_log: list[dict] = []
    attribution: list[dict] = []
    if pexels_api_key:
        for idx, seg in enumerate(script["segments"]):
            if idx == DATA_CARD_SEGMENT:
                search_log.append({"segment": idx, "skipped": "data-card"})
                continue
            files, attrs = await fetch_pexels_videos_with_attribution(
                seg.get("keywords", []), 1, cand_dir, pexels_api_key
            )
            search_log.append({"segment": idx, "query": seg.get("keywords", []),
                               "files": [f.name for f in files]})
            for a in attrs:
                a["segment"] = idx
            # P0 gate: main-track video needs rel>=70
            kept = [a for a in attrs if float(a.get("relevance_score", 0)) >= 70]
            attribution.extend(kept)
    _write_json(task / "search_log.json", {"log": search_log})

    # S5 data card + attribution sidecar
    card_path = render_data_card(topic, snap, task / "karios_card.png")
    attribution.append({
        "segment": DATA_CARD_SEGMENT,
        "file": card_path.name,
        "source_name": "Karios",
        "source_url": f"Karios早报快照 {brief_id(snap, 'morning')}",
        "license_tier": "tier1-safe",
        "license_name": "karios-data-card(自制)",
        "author": "躺平的老黄",
        "retrieved_at": datetime.now().isoformat(),
        "relevance_score": 100.0,
    })
    _write_json(task / "material_attribution.json", {"materials": attribution})

    result: dict = {
        "task_dir": str(task),
        "topic": topic["title"],
        "factcheck": "PASS",
        "materials": len(attribution),
    }

    # S7-S8 render via the general video path (daily_news preset = video_first).
    # Bound media (S4 videos + data card) ride inside script.json segments, so
    # the renderer uses exactly the audited files and never re-downloads.
    if render:
        from ...routes.videos import VideoGenerateRequest
        from ..cli_runner import run_pipeline

        bound = _bind_media_to_script(task)
        req = VideoGenerateRequest(
            type="daily_news",
            title=script["title"],
            approved_script=str(bound),
            voice="zh-CN-YunjianNeural",
            voice_rate="+0%",
            background_source="both",
        )
        out = run_pipeline(req, task / "render")
        result["render"] = {"status": (out.get("status") or {}).get("status"),
                            "task_dir": out.get("task_dir")}
        result["render_task_id"] = out.get("task_id")
    return result


def _bind_media_to_script(task: Path) -> Path:
    """Write ``script_bound.json``: per-segment ``images`` = audited media files.

    Videos (.mp4) are played by compose; the data-card .png pins segment 2.
    """
    import json as _j

    task = Path(task)
    script = _j.loads((task / "script.json").read_text(encoding="utf-8"))
    attr = _j.loads((task / "material_attribution.json").read_text(encoding="utf-8"))
    by_seg: dict[int, list[str]] = {}
    for m in attr.get("materials", []):
        seg = int(m.get("segment", -1))
        p = task / "candidates" / m.get("file", "")
        if not p.exists() and m.get("file", "") == "karios_card.png":
            p = task / "karios_card.png"
        if p.exists():
            by_seg.setdefault(seg, []).append(str(p))
    for idx, seg in enumerate(script.get("segments", [])):
        if idx in by_seg:
            seg["images"] = by_seg[idx]
            # v2 (owner feedback #2): reuse the stock-indicator fullframe style
            # exactly — every segment uses fit=contain so footage sits above the
            # 130px white subtitle band and dark #1f2329 text stays readable.
            # Never cover-fill (dark text over full-bleed video was unreadable).
            # Photos get gentle slow zoom (pan/zoom); videos play flat.
            seg["fit"] = "contain"
            first = str(by_seg[idx][0]).lower() if by_seg[idx] else ""
            if first.endswith((".png", ".jpg", ".jpeg", ".webp")):
                seg["motion"] = "gentle"
            else:
                seg["motion"] = "none"
    out = task / "script_bound.json"
    out.write_text(_j.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def run_mvp_sync(*args, **kwargs) -> dict:
    return asyncio.run(run_mvp(*args, **kwargs))
