"""一集式流水线：搜集→核实→排序→写稿→素材→成片→质检。

产出（out_dir）：briefing_private.md / briefing_public.md / script.json /
script.md（口播）/ description.txt / cover.png / assets_manifest.json /
rank_log.json / factcheck.md / render/（mp4+srt+cover）/ status.json。
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

from .assets import build_assets, english_query_for, fetch_pexels_for_item
from .data_2026_10_03 import get_snapshot
from .factcheck import factcheck
from .scoring import rank_items
from .script_builder import (
    build_description,
    build_private_md,
    build_public_md,
    build_script_json,
    build_narration_segments,
)

PRESENTER = "躺平的老黄"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _write_json(path: Path, obj: dict | list) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def collect(date: str) -> dict:
    """搜集：v1 用策展快照（对齐金样）；结构兼容 config/news_sources.yaml 的未来 RSS。"""
    snap = get_snapshot(date)
    return snap


def run_text_only(date: str, out_dir: str | Path, weights: dict | None = None) -> dict:
    """只出文稿（--text-only）：md 私人版+公开版 + rank/factcheck，不渲染。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    snap = collect(date)
    ranked, rank_log = rank_items(snap["items"], weights)
    private = build_private_md(date, ranked, snap["video_topics"])
    public = build_public_md(date, ranked, snap["video_topics"])
    narration = build_narration_segments(date, ranked, snap["video_topics"])
    script_json = build_script_json(date, ranked, snap["video_topics"])
    passed, fc_md = factcheck(ranked, narration, snap)
    _write(out / "briefing_private.md", private)
    _write(out / "briefing_public.md", public)
    _write_json(out / "script.json", script_json)
    _write(out / "script.md", public)
    _write(out / "factcheck.md", fc_md)
    _write_json(out / "rank_log.json", {"log": rank_log, "weights": weights or {"importance": 0.5, "novelty": 0.25, "relevance": 0.25}})
    _write(out / "description.txt", build_description(date, ranked, snap["video_topics"]))
    _write_json(out / "snapshot.json", snap)
    _write_json(out / "status.json", {
        "status": "script_ready" if passed else "factcheck_fail",
        "date": date, "presenter": PRESENTER, "factcheck": "PASS" if passed else "FAIL",
        "items": len(ranked),
    })
    if not passed:
        raise ValueError(f"事实核对 FAIL，不许进渲染\n{fc_md}")
    return {"out_dir": str(out), "factcheck": "PASS", "items": len(ranked)}


async def _try_upgrade_to_pexels(date, narration, ranked, task_dir, bound, manifest, api_key) -> tuple[dict, list]:
    """有 key 才升级：每条按具体主题检索词取 Pexels 视频（≥1080p、≥70分、不重复），否则保留自绘。"""
    if not api_key:
        return bound, manifest
    cand_dir = Path(task_dir) / "candidates"
    used: set[str] = set()
    for idx, seg in enumerate(narration):
        if seg.get("kind") != "item":
            continue
        item = next((it for it in ranked if it.get("id") == seg.get("item_id")), None)
        if not item:
            continue
        try:
            query = english_query_for(item["id"], item.get("pexels_query", ""))
        except ValueError:
            continue
        try:
            files, attrs = await fetch_pexels_for_item(query, cand_dir, api_key, count=1)
        except Exception:
            continue
        if not files or not attrs:
            continue
        a = attrs[0]
        if a["file"] in used:
            continue
        used.add(a["file"])
        a["segment"] = idx
        # 替换该段绑定为 Pexels 视频（自绘卡保留在 cards/ 备查，不进主轨）
        bound[idx] = [str(files[0])]
        # 替换 manifest 中同段自绘条目
        manifest = [m for m in manifest if m.get("segment") != idx]
        manifest.append(a)
    manifest.sort(key=lambda m: m.get("segment", 0))
    files = [m["file"] for m in manifest]
    assert len(files) == len(set(files)), f"Pexels 去重失败: {files}"
    return bound, manifest


def run_full(date: str, out_dir: str | Path, pexels_api_key: str | None = None,
             voice: str | None = None, resolution: str = "2560x1440") -> dict:
    """全量：文稿 + 素材 + 1440p 成片 + 封面 + 描述 + manifest（同步，无嵌套 loop）。"""
    from ..cli_runner import run_pipeline

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    res = run_text_only(date, out)
    snap = json.loads((out / "snapshot.json").read_text(encoding="utf-8"))
    ranked = _rebuild_ranked(snap)
    narration = build_narration_segments(date, ranked, snap["video_topics"])
    script_json = json.loads((out / "script.json").read_text(encoding="utf-8"))

    # 素材（自绘保底 + 可选 Pexels 升级；升级单独跑一次 loop，绝不嵌套在 render loop 内）
    key = pexels_api_key or os.environ.get("PEXELS_API_KEY") or None
    bound, manifest = build_assets(date, narration, ranked, out, key)
    if key:
        bound, manifest = asyncio.run(_try_upgrade_to_pexels(date, narration, ranked, out, bound, manifest, key))
    _write_json(out / "assets_manifest.json", {"materials": manifest, "date": date, "presenter": PRESENTER})

    # 绑定到 script_bound.json（全段绑定 → video_service 跳过 Pexels）
    script_json["title"] = script_json.get("title", f"每日世界简报 {date}")
    for idx, seg in enumerate(script_json.get("segments", [])):
        if idx in bound:
            seg["images"] = bound[idx]
            seg["fit"] = "contain"
            first = str(bound[idx][0]).lower() if bound[idx] else ""
            seg["motion"] = "gentle" if first.endswith((".png", ".jpg", ".jpeg", ".webp")) else "none"
    bound_path = out / "script_bound.json"
    _write_json(bound_path, script_json)

    # 渲染（复用 VF 通用视频链路：TTS 默认档 + 字幕 + 1440p compose）
    from ..cover_service import generate_cover_image  # noqa: F401 (cover 由 video_service 生成，此处仅保底)
    from ...routes.videos import VideoGenerateRequest

    w, h = (int(x) for x in resolution.lower().split("x"))
    req = VideoGenerateRequest(
        type="world_briefing",
        title=script_json["title"],
        approved_script=str(bound_path),
        voice=voice or "zh-CN-YunjianNeural",
        voice_rate="+0%",
        background_source="both",
        resolution_width=w,
        resolution_height=h,
    )
    render_dir = out / "render"
    render_dir.mkdir(parents=True, exist_ok=True)
    result = run_pipeline(req, render_dir)

    # 归档成片到 out_dir 顶层（video.mp4 + cover + srt）
    import shutil

    video_src = None
    status = result.get("status") or {}
    files = status.get("files") or {}
    if files.get("video"):
        video_src = Path(files["video"])
    if video_src and video_src.is_file():
        shutil.copy2(video_src, out / "video.mp4")
    # cover / srt 尽力归档
    for name in ("cover.png", "cover_image.png"):
        p = render_dir / name
        if p.is_file():
            shutil.copy2(p, out / "cover.png")
            break
    for p in render_dir.glob("*.srt"):
        shutil.copy2(p, out / "subtitles.srt")
        break
    for p in render_dir.glob("*.ass"):
        shutil.copy2(p, out / "subtitles.ass")
        break
    # 若 cover 缺失，用首张自绘卡兜底为封面（仍 2560x1440）
    if not (out / "cover.png").is_file():
        first_card = next((Path(b[0]) for b in bound.values() if b), None)
        if first_card and Path(first_card).is_file():
            shutil.copy2(first_card, out / "cover.png")

    _write_json(out / "status.json", {
        "status": status.get("status", "completed"), "date": date, "presenter": PRESENTER,
        "factcheck": "PASS", "items": len(ranked),
        "video": str(out / "video.mp4") if (out / "video.mp4").is_file() else None,
        "cover": str(out / "cover.png") if (out / "cover.png").is_file() else None,
        "render_task_dir": str(render_dir),
        "rendered_at": datetime.now().isoformat(),
    })
    res.update({
        "video": str(out / "video.mp4") if (out / "video.mp4").is_file() else None,
        "cover": str(out / "cover.png") if (out / "cover.png").is_file() else None,
        "manifest": str(out / "assets_manifest.json"),
        "private_md": str(out / "briefing_private.md"),
        "public_md": str(out / "briefing_public.md"),
        "render_status": status.get("status"),
    })
    return res


def _rebuild_ranked(snap: dict) -> list[dict]:
    ranked, _ = rank_items(snap["items"])
    return ranked
