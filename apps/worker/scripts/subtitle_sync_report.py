#!/usr/bin/env python
"""Diagnose how well subtitle cue starts line up with real speech onsets.

Usage::

    cd apps/worker
    uv run python scripts/subtitle_sync_report.py TASK_DIR [--cover 3.0]

Reads ``TASK_DIR/subtitles.ass`` plus the ``segment_*.mp3`` files, detects the
real speech runs in each segment and prints, per cue, the delta between the cue
start and the nearest speech onset, the share within 0.15s, the max |delta| and
any pause >= 0.7s sitting inside a cue (a mid-phrase pause). Segment offsets are
taken from ``task.log`` ("音频片段 N: 开始=...") when present, otherwise the
segments are assumed back-to-back after the cover, separated by the indicator
segment pause (0.5s). Always exits 0.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.tts.speech_runs import detect_speech_runs  # noqa: E402

_DIALOGUE_RE = re.compile(
    r"Dialogue:\s*0,(\d+):(\d{2}):(\d{2})\.(\d{2}),(\d+):(\d{2}):(\d{2})\.(\d{2}),"
)
_START_RE = re.compile(r"音频片段\s+(\d+):\s*开始=([\d.]+)s")
_SEGMENT_PAUSE_S = 0.5
_MID_PHRASE_PAUSE_S = 0.7
_TOLERANCE_S = 0.15


def _parse_time(hours: str, minutes: str, seconds: str, centis: str) -> float:
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds) + int(centis) / 100.0


def _parse_ass(path: Path) -> list[tuple[float, float, str]]:
    cues: list[tuple[float, float, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _DIALOGUE_RE.match(line)
        if not match:
            continue
        start = _parse_time(*match.group(1, 2, 3, 4))
        end = _parse_time(*match.group(5, 6, 7, 8))
        text = line.split(",", 9)[-1].strip() if line.count(",") >= 9 else ""
        cues.append((start, end, text))
    return cues


def _probe_duration(path: Path) -> float | None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(result.stdout.strip())
    except Exception:
        return None


def _segment_files(task_dir: Path) -> list[tuple[int, Path]]:
    found: list[tuple[int, Path]] = []
    for path in task_dir.glob("segment_*.mp3"):
        match = re.fullmatch(r"segment_(\d+)", path.stem)
        if match:
            found.append((int(match.group(1)), path))
    return sorted(found)


def _logged_starts(task_dir: Path) -> dict[int, float]:
    starts: dict[int, float] = {}
    log_file = task_dir / "task.log"
    if not log_file.exists():
        return starts
    for line in log_file.read_text(encoding="utf-8", errors="replace").splitlines():
        match = _START_RE.search(line)
        if match:
            starts[int(match.group(1))] = float(match.group(2))
    return starts


def _segment_starts(
    segments: list[tuple[int, Path]], cover: float
) -> dict[int, float]:
    starts: dict[int, float] = {}
    cursor = cover
    for index, path in segments:
        starts[index] = cursor
        duration = _probe_duration(path) or 0.0
        cursor += duration + _SEGMENT_PAUSE_S
    return starts


def _nearest_onset(cue_start: float, onsets: list[float]) -> float | None:
    best: float | None = None
    best_distance = float("inf")
    for onset in onsets:
        distance = abs(onset - cue_start)
        if distance < best_distance:
            best_distance = distance
            best = onset
    return best


def _build_report(task_dir: Path, cover: float) -> str:
    ass_path = task_dir / "subtitles.ass"
    if not ass_path.exists():
        return f"subtitles.ass not found in {task_dir}"
    cues = _parse_ass(ass_path)
    segments = _segment_files(task_dir)
    starts = _logged_starts(task_dir) or _segment_starts(segments, cover)

    onsets: list[float] = []
    gaps: list[tuple[float, float]] = []
    for index, path in segments:
        segment_start = starts.get(index, cover)
        runs = detect_speech_runs(path)
        for run_start, run_end in runs:
            onsets.append(segment_start + run_start)
        for (_, previous_end), (next_start, _) in zip(runs, runs[1:]):
            gaps.append((segment_start + previous_end, segment_start + next_start))
    onsets.sort()

    lines = [
        f"cues: {len(cues)}  segments: {len(segments)}  cover: {cover:.1f}s  "
        f"detected onsets: {len(onsets)}"
    ]
    deltas: list[float] = []
    for i, (start, _end, text) in enumerate(cues, start=1):
        onset = _nearest_onset(cover + start, onsets)
        delta = float("nan") if onset is None else (cover + start) - onset
        if onset is not None:
            deltas.append(delta)
        delta_text = "n/a" if onset is None else f"{delta:+.3f}s"
        lines.append(f"cue {i:>3}  start={start:7.2f}s  nearest={delta_text}  {text}")

    if deltas:
        within = sum(1 for d in deltas if abs(d) <= _TOLERANCE_S)
        share = 100.0 * within / len(deltas)
        lines.append(
            f"within {_TOLERANCE_S:.2f}s: {within}/{len(deltas)} ({share:.0f}%)  "
            f"max |delta|: {max(abs(d) for d in deltas):.3f}s"
        )

    mid_phrase: list[str] = []
    for pause_start, pause_end in gaps:
        if pause_end - pause_start < _MID_PHRASE_PAUSE_S:
            continue
        for i, (start, end, text) in enumerate(cues, start=1):
            g_start = cover + start
            g_end = cover + end
            if pause_start >= g_start and pause_end <= g_end:
                mid_phrase.append(
                    f"  cue {i:>3} pause={pause_end - pause_start:.2f}s "
                    f"at {pause_start:.2f}s  {text}"
                )
                break
    lines.append(f"mid-phrase pauses (>={_MID_PHRASE_PAUSE_S}s): {len(mid_phrase)}")
    lines.extend(mid_phrase)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_dir", type=Path, help="task directory with subtitles.ass")
    parser.add_argument(
        "--cover", type=float, default=3.0, help="cover hold in seconds (default 3.0)"
    )
    args = parser.parse_args(argv)
    try:
        print(_build_report(args.task_dir, args.cover))
    except Exception as exc:  # noqa: BLE001 - diagnostic tool always exits 0
        print(f"subtitle sync report failed: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
