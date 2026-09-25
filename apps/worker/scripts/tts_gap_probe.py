#!/usr/bin/env python
"""Probe the real per-sentence gap produced by the TTS + pause-alignment path.

Usage::

    cd apps/worker

    # Synthesize a clip through the real indicator path, then measure it
    uv run python scripts/tts_gap_probe.py --type indicator \
        --text "第一句。第二句。" --out /tmp/clip.mp3 [--rate +2%] [--gap 0.75]

    # Only measure an existing mp3
    uv run python scripts/tts_gap_probe.py --measure /tmp/clip.mp3

The probe resolves the preset with :func:`src.presets.get_type_preset`,
synthesizes with ``EdgeTTSEngine(voice, rate)`` capturing sentence boundaries and
then applies :func:`src.core.tts.pauses.sync_sentence_pauses` exactly like
``video_service._synthesize_audio`` — the shared helper keeps the two in sync. It
prints the voice, rate, gap setting, duration, the detected speech runs and the
measured sentence gaps (silences >= 0.45 s between speech runs) with
mean/min/max. Always exits 0.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.tts.pauses import sync_sentence_pauses  # noqa: E402
from src.core.tts.speech_runs import detect_speech_runs  # noqa: E402
from src.core.tts_engine import EdgeTTSEngine  # noqa: E402
from src.presets import get_type_preset  # noqa: E402

# A run-to-run silence at least this long counts as a sentence gap.
_GAP_MIN_S = 0.45


def _sentence_gaps(runs: list[tuple[float, float]]) -> list[float]:
    return [
        next_start - previous_end
        for (_, previous_end), (next_start, _) in zip(runs, runs[1:])
        if next_start - previous_end >= _GAP_MIN_S
    ]


def _gap_stats(gaps: list[float]) -> str:
    if not gaps:
        return "none"
    return (
        f"count={len(gaps)} mean={statistics.fmean(gaps):.3f}s "
        f"min={min(gaps):.3f}s max={max(gaps):.3f}s"
    )


def _measure_report(path: Path, duration: float | None) -> str:
    runs = detect_speech_runs(path)
    gaps = _sentence_gaps(runs)
    duration_text = "n/a" if duration is None else f"{duration:.3f}s"
    return "\n".join(
        [
            f"file: {path}",
            f"duration: {duration_text}",
            f"speech runs ({len(runs)}): {runs}",
            f"measured sentence gaps (>={_GAP_MIN_S}s): {_gap_stats(gaps)}",
        ]
    )


async def _synthesize(
    text: str,
    out_path: Path,
    preset,
    rate: str,
    gap: float,
    pause: float,
) -> str:
    engine = EdgeTTSEngine(voice=preset.voice, rate=rate)
    boundaries: list[dict] = []
    await engine.synthesize(
        text=text,
        output_path=out_path,
        voice=preset.voice,
        boundaries=boundaries,
    )
    duration = await engine.get_duration(out_path)

    aligned = None
    if (pause > 0 or gap > 0) and len(boundaries) >= 2:
        aligned = sync_sentence_pauses(
            out_path, boundaries, pause_seconds=pause, gap_seconds=gap
        )
    if aligned is not None:
        duration, _ = aligned

    header = [
        f"file: {out_path}",
        f"voice: {preset.voice}",
        f"rate: {rate}",
        f"gap setting: {gap}s (sentence_pause={pause}s)",
        f"boundaries: {len(boundaries)}",
        f"duration: {duration:.3f}s",
    ]
    return "\n".join(header) + "\n" + _measure_report(out_path, duration)


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


async def _run(args: argparse.Namespace) -> str:
    if args.measure is not None:
        return _measure_report(args.measure, _probe_duration(args.measure))

    preset = get_type_preset(args.type)
    rate = args.rate or preset.tts_rate
    gap = preset.sentence_gap_seconds if args.gap is None else args.gap
    pause = 0.0 if gap > 0 else preset.sentence_pause_seconds
    if args.text is None or args.out is None:
        raise SystemExit("--text and --out are required unless --measure is given")
    return await _synthesize(args.text, args.out, preset, rate, gap, pause)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--type", default="general", help="content type preset (default general)")
    parser.add_argument("--text", help="text to synthesize")
    parser.add_argument("--out", type=Path, help="output mp3 path")
    parser.add_argument("--rate", help="override the preset TTS rate, e.g. +2%%")
    parser.add_argument(
        "--gap",
        type=float,
        default=None,
        help="override the preset sentence_gap_seconds (0 = legacy additive mode)",
    )
    parser.add_argument("--measure", type=Path, help="only measure an existing mp3")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        print(asyncio.run(_run(args)))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - diagnostic tool always exits 0
        print(f"tts gap probe failed: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
