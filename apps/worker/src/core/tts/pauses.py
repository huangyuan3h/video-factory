"""Insert silence between sentences inside a single synthesized segment.

edge-tts writes one mp3 per script segment but sentences inside the segment run
together. This module cuts the decoded PCM at the midpoint of each inter-sentence
gap, splices in ``sentence_pause_seconds`` of zero samples, re-encodes the mp3 in
place, and returns the shifted boundary timings so subtitles stay in sync.

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


def apply_sentence_pauses(
    audio_path: Path,
    boundaries: list[dict],
    pause_seconds: float,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> tuple[float, list[dict]] | None:
    """Splice ``pause_seconds`` of silence between sentences in ``audio_path``.

    Returns ``(new_duration, shifted_boundaries)`` or ``None`` when there is
    nothing to do or the codec step fails (the audio is left untouched).
    """
    if pause_seconds <= 0 or len(boundaries) < 2:
        return None
    tmp_path = Path(f"{audio_path}.pauses.mp3")
    try:
        cuts = plan_cuts(boundaries, pause_seconds)
        pcm = _decode_to_pcm(audio_path, sample_rate)
        silence = b"\x00" * (int(round(pause_seconds * sample_rate)) * _BYTES_PER_SAMPLE)

        spliced = bytearray()
        previous_byte = 0
        for cut in cuts:
            byte_index = int(round(cut * sample_rate)) * _BYTES_PER_SAMPLE
            byte_index = max(previous_byte, min(byte_index, len(pcm)))
            spliced += pcm[previous_byte:byte_index]
            spliced += silence
            previous_byte = byte_index
        spliced += pcm[previous_byte:]

        # Encode to a sibling temp file and only swap it in once the probe
        # succeeds, so a late failure never leaves half-written audio behind.
        _encode_pcm(bytes(spliced), tmp_path, sample_rate)
        new_duration = _probe_duration(tmp_path)
        os.replace(tmp_path, audio_path)
        return new_duration, shift_boundaries(boundaries, pause_seconds)
    except Exception as exc:  # noqa: BLE001 - best-effort, keep original audio
        logger.warning(f"Sentence-pause insertion failed for {audio_path}: {exc}")
        return None
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
