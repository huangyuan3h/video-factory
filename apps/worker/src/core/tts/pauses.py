"""Insert or align silence between sentences inside a single synthesized segment.

edge-tts writes one mp3 per script segment but sentences inside the segment run
together. This module cuts the decoded PCM at the midpoint of each inter-sentence
gap, splices in ``sentence_pause_seconds`` of zero samples (legacy additive mode),
re-encodes the mp3 in place, and returns the shifted boundary timings so subtitles
stay in sync.

A second mode targets the *total* silence between sentences: edge-tts already
leaves a natural gap in the audio, so the additive value above becomes "extra
silence" and the real gap is much longer than configured. With
``target_gap_seconds`` the existing silent run around each cut is measured and
only topped up (or trimmed) to the target, so the configured value is the real
gap.

The whole operation is best-effort: any codec/probe failure is logged and the
caller keeps the original audio/boundaries.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_SAMPLE_RATE = 24000
_BYTES_PER_SAMPLE = 2  # s16le mono

# Target-gap mode reuses the energy definition of ``speech_runs``: 10 ms frames,
# a frame is silent when its RMS is more than 32 dB below the loudest frame.
_GAP_FRAME_S = 0.01
_GAP_REL_DB = -32.0
_GAP_SILENCE_DB = -70.0
_GAP_NEAR_S = 0.3


def plan_cuts(boundaries: list[dict], pause_seconds: float) -> list[float]:
    """Return the cut time (seconds) between each consecutive boundary pair.

    A cut lands at the midpoint of the gap; when the next sentence already starts
    before the previous one ends (``start_{i+1} <= end_i``) it lands on that
    start. No cut is produced before the first or after the last sentence.
    """
    cuts: list[float] = []
    for previous, nxt in zip(boundaries, boundaries[1:]):
        end_previous = float(previous.get("offset", 0.0) or 0.0) + float(
            previous.get("duration", 0.0) or 0.0
        )
        start_next = float(nxt.get("offset", 0.0) or 0.0)
        if start_next <= end_previous:
            cuts.append(start_next)
        else:
            cuts.append((end_previous + start_next) / 2.0)
    return cuts


def shift_boundaries(boundaries: list[dict], pause_seconds: float) -> list[dict]:
    """Return boundaries with the k-th sentence offset advanced by k*pause."""
    return [
        {
            **boundary,
            "offset": float(boundary.get("offset", 0.0) or 0.0)
            + index * pause_seconds,
        }
        for index, boundary in enumerate(boundaries)
    ]


def _decode_to_pcm(audio_path: Path, sample_rate: int) -> bytes:
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(audio_path),
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    )
    return result.stdout


def _encode_pcm(pcm: bytes, out_path: Path, sample_rate: int) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-i",
            "pipe:0",
            "-codec:a",
            "libmp3lame",
            "-q:a",
            "4",
            str(out_path),
        ],
        input=pcm,
        capture_output=True,
        check=True,
    )


def _probe_duration(audio_path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def _silent_runs(pcm: bytes, sample_rate: int) -> list[tuple[float, float]]:
    """Contiguous silent runs ``(start, end)`` in seconds for mono s16le ``pcm``.

    Uses the same energy definition as
    :func:`src.core.tts.speech_runs.detect_speech_runs` (10 ms frames, silence =
    RMS more than 32 dB below the loudest frame).
    """
    from .speech_runs import _frame_dbs

    frame_len = max(1, int(round(_GAP_FRAME_S * sample_rate)))
    dbs = _frame_dbs(pcm, frame_len) if pcm else []
    if not dbs:
        return []
    max_db = max(dbs)
    if max_db <= _GAP_SILENCE_DB:
        return []
    threshold = max_db + _GAP_REL_DB

    runs: list[tuple[float, float]] = []
    index = 0
    total = len(dbs)
    while index < total:
        if dbs[index] >= threshold:
            index += 1
            continue
        start = index
        while index < total and dbs[index] < threshold:
            index += 1
        runs.append((start * _GAP_FRAME_S, index * _GAP_FRAME_S))
    return runs


def _silent_run_near(
    cut: float, runs: list[tuple[float, float]], window_s: float = _GAP_NEAR_S
) -> tuple[float, float] | None:
    """The silent run containing ``cut`` or the nearest one within ``window_s``."""
    best: tuple[float, float] | None = None
    best_distance = window_s
    for run in runs:
        start, end = run
        if start <= cut <= end:
            return run
        distance = start - cut if cut < start else cut - end
        if distance <= best_distance:
            best_distance = distance
            best = run
    return best


def _apply_target_gaps(
    pcm: bytes,
    boundaries: list[dict],
    cuts: list[float],
    sample_rate: int,
    target_gap_seconds: float,
) -> tuple[bytes, list[dict]]:
    """Top up/trim the silent run at each cut to ``target_gap_seconds``.

    Every cut is realigned to the target independently; boundaries are shifted by
    the cumulative delta so subtitles stay in sync. A cut with no silent run near
    it is left unchanged.
    """
    runs = _silent_runs(pcm, sample_rate)
    spliced = bytearray()
    cursor = 0
    deltas: list[float] = []
    for cut in cuts:
        run = _silent_run_near(cut, runs)
        if run is None:
            deltas.append(0.0)
            continue
        existing = run[1] - run[0]
        delta_samples = int(round((target_gap_seconds - existing) * sample_rate))

        middle = (run[0] + run[1]) / 2.0
        middle_sample = int(round(middle * sample_rate))
        middle_byte = max(cursor, min(middle_sample * _BYTES_PER_SAMPLE, len(pcm)))

        if delta_samples > 0:
            spliced += pcm[cursor:middle_byte]
            spliced += b"\x00" * (delta_samples * _BYTES_PER_SAMPLE)
            cursor = middle_byte
            deltas.append(delta_samples / sample_rate)
        elif delta_samples < 0:
            # Remove the excess centred on the middle of the run so speech on both
            # sides is never touched, even when |delta| exceeds half the run.
            remove = -delta_samples
            left = remove // 2
            run_start = int(round(run[0] * sample_rate))
            run_end = int(round(run[1] * sample_rate))
            start_sample = max(
                run_start, cursor // _BYTES_PER_SAMPLE, middle_sample - left
            )
            end_sample = min(
                run_end, len(pcm) // _BYTES_PER_SAMPLE, middle_sample + (remove - left)
            )
            end_sample = max(start_sample, end_sample)
            start_byte = start_sample * _BYTES_PER_SAMPLE
            spliced += pcm[cursor:start_byte]
            cursor = end_sample * _BYTES_PER_SAMPLE
            deltas.append(-(end_sample - start_sample) / sample_rate)
        else:
            spliced += pcm[cursor:middle_byte]
            cursor = middle_byte
            deltas.append(0.0)
    spliced += pcm[cursor:]

    shifted: list[dict] = []
    cumulative = 0.0
    for index, boundary in enumerate(boundaries):
        if index > 0:
            cumulative += deltas[index - 1]
        shifted.append(
            {
                **boundary,
                "offset": float(boundary.get("offset", 0.0) or 0.0) + cumulative,
            }
        )
    return bytes(spliced), shifted


def apply_sentence_pauses(
    audio_path: Path,
    boundaries: list[dict],
    pause_seconds: float,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    *,
    target_gap_seconds: float | None = None,
) -> tuple[float, list[dict]] | None:
    """Splice or align silence between sentences in ``audio_path``.

    With ``target_gap_seconds`` > 0 the existing silent run at each cut is
    measured and topped up/trimmed to that total (the configured pause value is
    ignored). Otherwise the legacy additive behaviour inserts ``pause_seconds`` of
    silence at every cut.

    Returns ``(new_duration, shifted_boundaries)`` or ``None`` when there is
    nothing to do or the codec step fails (the audio is left untouched).
    """
    target = float(target_gap_seconds or 0.0)
    if target <= 0 and pause_seconds <= 0:
        return None
    if len(boundaries) < 2:
        return None
    tmp_path = Path(f"{audio_path}.pauses.mp3")
    try:
        cuts = plan_cuts(boundaries, pause_seconds)
        pcm = _decode_to_pcm(audio_path, sample_rate)
        if target > 0:
            spliced, shifted = _apply_target_gaps(pcm, boundaries, cuts, sample_rate, target)
        else:
            silence = b"\x00" * (int(round(pause_seconds * sample_rate)) * _BYTES_PER_SAMPLE)
            buffer = bytearray()
            previous_byte = 0
            for cut in cuts:
                byte_index = int(round(cut * sample_rate)) * _BYTES_PER_SAMPLE
                byte_index = max(previous_byte, min(byte_index, len(pcm)))
                buffer += pcm[previous_byte:byte_index]
                buffer += silence
                previous_byte = byte_index
            buffer += pcm[previous_byte:]
            spliced = bytes(buffer)
            shifted = shift_boundaries(boundaries, pause_seconds)

        # Encode to a sibling temp file and only swap it in once the probe
        # succeeds, so a late failure never leaves half-written audio behind.
        _encode_pcm(spliced, tmp_path, sample_rate)
        new_duration = _probe_duration(tmp_path)
        os.replace(tmp_path, audio_path)
        return new_duration, shifted
    except Exception as exc:  # noqa: BLE001 - best-effort, keep original audio
        logger.warning(f"Sentence-pause insertion failed for {audio_path}: {exc}")
        return None
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def sync_sentence_pauses(
    audio_path: Path,
    boundaries: list[dict],
    *,
    pause_seconds: float = 0.0,
    gap_seconds: float = 0.0,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> tuple[float, list[dict]] | None:
    """Dispatch to target-gap mode when ``gap_seconds`` > 0, else legacy splice.

    Shared by the video service and ``scripts/tts_gap_probe.py`` so the two
    cannot drift.
    """
    if gap_seconds and gap_seconds > 0:
        return apply_sentence_pauses(
            audio_path, boundaries, 0.0, sample_rate, target_gap_seconds=gap_seconds
        )
    return apply_sentence_pauses(audio_path, boundaries, pause_seconds, sample_rate)
