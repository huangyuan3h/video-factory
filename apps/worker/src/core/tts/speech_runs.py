"""Detect real speech runs in a segment's audio and snap cue starts onto them.

edge-tts gives per-sentence boundaries and a long sentence is split into lines
whose timing is estimated. That estimate drifts (numbers/percentages are spoken
much longer than their character count), so this module measures *where speech
actually is* and nudges each cue start onto the nearest speech onset.

All audio work is best-effort: any decode/probe failure yields an empty run list
and the caller keeps the original timings.
"""

from __future__ import annotations

import array
import logging
import math
from pathlib import Path

from .pauses import DEFAULT_SAMPLE_RATE, _decode_to_pcm

logger = logging.getLogger(__name__)

# Silence floor for fully-silent frames; kept below any real speech frame.
_FLOOR_DB = -120.0
# A signal whose loudest frame is still this quiet is treated as silence.
_SILENCE_DB = -70.0
_PCM_FULL_SCALE = 32768.0


def _frame_dbs(pcm: bytes, frame_len: int) -> list[float]:
    """Per-frame RMS in dBFS for mono s16le ``pcm``."""
    usable = len(pcm) - (len(pcm) % 2)
    samples = array.array("h")
    samples.frombytes(pcm[:usable])
    dbs: list[float] = []
    for start in range(0, len(samples), frame_len):
        chunk = samples[start : start + frame_len]
        acc = 0
        for value in chunk:
            acc += value * value
        rms = math.sqrt(acc / len(chunk))
        dbs.append(20.0 * math.log10(rms / _PCM_FULL_SCALE) if rms > 0 else _FLOOR_DB)
    return dbs


def detect_speech_runs(
    audio_path: Path,
    *,
    frame_s: float = 0.01,
    rel_db: float = -32.0,
    min_silence_s: float = 0.06,
    min_speech_s: float = 0.05,
) -> list[tuple[float, float]]:
    """Return merged ``(start, end)`` speech runs (seconds) in ``audio_path``.

    Frames are ``frame_s`` long; a frame is speech when its RMS is within
    ``rel_db`` of the loudest frame. Speech frames separated by less than
    ``min_silence_s`` are merged, and runs shorter than ``min_speech_s`` are
    dropped. Returns ``[]`` on any failure (missing codec, unreadable audio).
    """
    try:
        frame_len = max(1, int(round(frame_s * DEFAULT_SAMPLE_RATE)))
        pcm = _decode_to_pcm(Path(audio_path), DEFAULT_SAMPLE_RATE)
        if not pcm:
            return []
        dbs = _frame_dbs(pcm, frame_len)
        if not dbs:
            return []
        max_db = max(dbs)
        if max_db <= _SILENCE_DB:
            return []
        threshold = max_db + rel_db

        runs: list[list[float]] = []
        index = 0
        total = len(dbs)
        while index < total:
            if dbs[index] < threshold:
                index += 1
                continue
            end = index
            while end < total and dbs[end] >= threshold:
                end += 1
            runs.append([index * frame_s, end * frame_s])
            index = end

        merged: list[list[float]] = []
        for start, end in runs:
            if merged and start - merged[-1][1] < min_silence_s:
                merged[-1][1] = end
            else:
                merged.append([start, end])
        return [
            (round(start, 6), round(end, 6))
            for start, end in merged
            if end - start >= min_speech_s
        ]
    except Exception as exc:  # noqa: BLE001 - best-effort, caller keeps timings
        logger.warning(f"Speech-run detection failed for {audio_path}: {exc}")
        return []


def _nearest_onset(start: float, runs: list[tuple[float, float]], window_s: float) -> float | None:
    """Onset of the run whose start is closest to ``start`` within the window."""
    best: float | None = None
    best_distance = window_s
    for run_start, _ in runs:
        distance = abs(run_start - start)
        if distance <= window_s and distance < best_distance:
            best_distance = distance
            best = run_start
    return best


def _run_end_before(boundary: float, runs: list[tuple[float, float]]) -> float | None:
    """End of the last run that begins before ``boundary`` (or ``None``)."""
    found: float | None = None
    for run_start, run_end in runs:
        if run_start < boundary:
            found = run_end
    return found


def snap_cues(
    cues: list[tuple[float, float]],
    runs: list[tuple[float, float]],
    *,
    window_s: float = 0.7,
    lead_s: float = 0.04,
    min_len_s: float = 0.3,
) -> list[tuple[float, float]]:
    """Snap each cue start to the nearest real speech onset.

    ``cues`` and ``runs`` are relative to the same segment audio. A snapped start
    may not move earlier than the previous cue start + ``min_len_s`` nor later
    than its own original end - 0.1, otherwise the original start is kept. Ends
    bridge a following cue that begins within 0.3 s; otherwise a cue is extended
    to the end of the speech that precedes the next cue (plus 0.1 s), clamped to
    ``[start + min_len_s, next start]``. Pure function.
    """
    if not cues or not runs:
        return list(cues)

    starts: list[float] = []
    previous: float | None = None
    for start, end in cues:
        onset = _nearest_onset(start, runs, window_s)
        candidate = start
        if onset is not None:
            snapped = max(0.0, onset - lead_s)
            if (previous is None or snapped >= previous + min_len_s) and snapped <= end - 0.1:
                candidate = snapped
        if previous is not None and candidate < previous + min_len_s:
            candidate = previous + min_len_s
        starts.append(candidate)
        previous = candidate

    result: list[tuple[float, float]] = []
    for index, (_, original_end) in enumerate(cues):
        start = starts[index]
        next_start = starts[index + 1] if index + 1 < len(starts) else None

        if next_start is None:
            run_end = _run_end_before(math.inf, runs)
            candidate = original_end if run_end is None else run_end + 0.1
            candidate = max(candidate, start + min_len_s)
            result.append((start, candidate))
            continue

        run_end = _run_end_before(next_start, runs)
        candidate = original_end if run_end is None else run_end + 0.1
        candidate = max(start + min_len_s, min(candidate, next_start))
        if next_start - candidate < 0.3:
            candidate = next_start
        result.append((start, candidate))
    return result
