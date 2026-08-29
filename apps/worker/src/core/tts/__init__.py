"""TTS subpackage — providers + utilities."""

from .base import TTSProvider
from .edge_provider import EdgeTTSProvider
from .local_client import BUILTIN_LANGUAGES, BUILTIN_VOICES, LocalTTSClient, LocalTTSError
from .speakable import clip_for_local_tts, to_speakable_text
from .streaming import CHUNK_CHARS, SAMPLE_RATE, chunk_for_tts, iter_stream_blocks, pad_silence
from .wav import pcm16_mono_to_wav, wav_to_pcm16_mono

__all__ = [
    "TTSProvider",
    "EdgeTTSProvider",
    "LocalTTSClient",
    "LocalTTSError",
    "BUILTIN_VOICES",
    "BUILTIN_LANGUAGES",
    "to_speakable_text",
    "clip_for_local_tts",
    "chunk_for_tts",
    "pad_silence",
    "iter_stream_blocks",
    "CHUNK_CHARS",
    "SAMPLE_RATE",
    "pcm16_mono_to_wav",
    "wav_to_pcm16_mono",
]
