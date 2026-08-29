"""TTS utterance chunking + silence padding (server-side speech pipeline)."""

from __future__ import annotations

import struct
from collections.abc import Iterator

CHUNK_CHARS = 60
SENTENCE_PAUSE_SECONDS = 0.22
SAMPLE_RATE = 16000

_SEPARATORS = ["。", "！", "？", "；", "\n", "！", "…", ". ", "! ", "? ", "，", "、", ",", " "]


def chunk_for_tts(text: str, max_chars: int = CHUNK_CHARS) -> list[str]:
    s = (text or "").strip()
    if not s:
        return []
    if len(s) <= max_chars:
        return [s]

    out: list[str] = []
    rest = s
    while len(rest) > max_chars:
        window = rest[: max_chars + 1]
        cut = -1
        for sep in _SEPARATORS:
            idx = window.rfind(sep)
            if idx >= max_chars // 3:
                cut = idx + len(sep)
                break
        if cut < 0:
            cut = max_chars
        out.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        out.append(rest)
    return out


def pad_silence(wav: bytes, seconds: float = SENTENCE_PAUSE_SECONDS) -> bytes:
    n = int(seconds * SAMPLE_RATE)
    out = wav + b"\x00\x00" * n
    if (
        len(wav) >= 44
        and wav[:4] == b"RIFF"
        and wav[8:12] == b"WAVE"
        and wav[36:40] == b"data"
    ):
        try:
            riff_size = int.from_bytes(wav[4:8], "little")
            data_size = int.from_bytes(wav[40:44], "little")
            if riff_size == len(wav) - 8 and data_size == len(wav) - 44:
                out = (
                    out[:4]
                    + (riff_size + n * 2).to_bytes(4, "little")
                    + out[8:40]
                    + (data_size + n * 2).to_bytes(4, "little")
                    + out[44:]
                )
        except Exception:
            pass
    return out


def iter_stream_blocks(wavs: list[bytes]) -> Iterator[bytes]:
    for i, wav in enumerate(wavs):
        block = wav if i == len(wavs) - 1 else pad_silence(wav)
        yield struct.pack(">I", len(block)) + block
    yield struct.pack(">I", 0)
