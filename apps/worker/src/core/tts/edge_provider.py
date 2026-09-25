"""Edge-TTS provider — retains original behavior with speakable cleaning."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import edge_tts

from ...config import settings
from .speakable import to_speakable_text

logger = logging.getLogger(__name__)

# edge-tts reports boundary offset/duration in 100-nanosecond ticks.
_TICKS_PER_SECOND = 1e7


def _ticks_to_seconds(value: object) -> float:
    try:
        return float(value) / _TICKS_PER_SECOND
    except (TypeError, ValueError):
        return 0.0



class EdgeTTSProvider:
    """Edge-TTS provider for Chinese voice synthesis."""

    VOICES = {
        "zh-CN-XiaoxiaoNeural": "Xiaoxiao (Female, Natural) - Alternative general-purpose voice",
        "zh-CN-YunxiNeural": "Yunxi (Male, Sunny) - Good for tech and lifestyle",
        "zh-CN-YunjianNeural": "Yunjian (Male, Steady) - Recommended default for all content types",
        "zh-CN-XiaoyiNeural": "Xiaoyi (Female, Gentle) - Good for emotional content",
        "zh-CN-YunjiaNeural": "Yunjia (Male, Storytelling) - Good for narratives",
        "zh-CN-XiaochenNeural": "Xiaochen (Female, Professional)",
        "zh-CN-XiaohanNeural": "Xiaohan (Female, Warm)",
        "zh-CN-XiaomengNeural": "Xiaomeng (Female, Cute) - Good for entertainment",
        "zh-CN-XiaomoNeural": "Xiaomo (Female, Adult)",
        "zh-CN-XiaoruiNeural": "Xiaorui (Female, Child)",
        "zh-CN-XiaoshuangNeural": "Xiaoshuang (Female, Child)",
        "zh-CN-XiaoxuanNeural": "Xiaoxuan (Female, Gentle)",
        "zh-CN-XiaoyanNeural": "Xiaoyan (Female, Friendly)",
        "zh-CN-XiaoyouNeural": "Xiaoyou (Female, Child)",
        "zh-CN-YunfengNeural": "Yunfeng (Male, Mature)",
        "zh-CN-YunhaoNeural": "Yunhao (Male, Documentary)",
        "zh-CN-YunxiangNeural": "Yunxiang (Male, Young)",
        "zh-CN-YunxiaNeural": "Yunxia (Male, Child)",
        "zh-CN-YunyeNeural": "Yunye (Male, Emotional)",
    }

    def __init__(
        self,
        voice: str | None = None,
        rate: str | None = None,
    ):
        self.voice = voice or settings.tts_voice
        self.rate = rate or settings.tts_rate

    async def synthesize(
        self,
        text: str,
        output_path: Path | None = None,
        voice: str | None = None,
        boundaries: list | None = None,
    ) -> Path:
        """Synthesize ``text`` to ``output_path``.

        When ``boundaries`` is a list, per-sentence (``SentenceBoundary``)
        timings are appended to it as ``{"offset", "duration", "text"}`` dicts
        with times in seconds. On capture failure the audio is still written and
        the list is left empty. Existing callers that omit ``boundaries`` keep
        the original save-only behaviour.
        """
        voice = voice or self.voice
        # Clean text so markdown/emoji are not spoken aloud
        cleaned = to_speakable_text(text) or text

        if output_path is None:
            output_path = Path(tempfile.mktemp(suffix=".mp3"))

        if boundaries is not None:
            captured = await self._stream_with_boundaries(cleaned, output_path, voice)
            boundaries.extend(captured)
            return output_path

        try:
            communicate = edge_tts.Communicate(
                text=cleaned,
                voice=voice,
                rate=self.rate,
            )
            await communicate.save(str(output_path))

            logger.info(f"Synthesized {len(cleaned)} chars to {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"TTS synthesis failed: {e}")
            raise

    async def synthesize_with_boundaries(
        self,
        text: str,
        output_path: Path | None = None,
        voice: str | None = None,
    ) -> tuple[Path, list[dict]]:
        """Synthesize audio and return ``(path, boundaries)`` (seconds)."""
        boundaries: list[dict] = []
        path = await self.synthesize(
            text, output_path=output_path, voice=voice, boundaries=boundaries
        )
        return path, boundaries

    async def _stream_with_boundaries(
        self, cleaned: str, output_path: Path, voice: str
    ) -> list[dict]:
        """Stream synthesis, writing audio and collecting boundary timings."""
        boundaries: list[dict] = []
        try:
            communicate = edge_tts.Communicate(
                text=cleaned,
                voice=voice,
                rate=self.rate,
                boundary="SentenceBoundary",
            )
            audio = bytearray()
            async for chunk in communicate.stream():
                if not isinstance(chunk, dict):
                    continue
                chunk_type = chunk.get("type")
                if chunk_type == "audio":
                    audio.extend(chunk.get("data") or b"")
                elif chunk_type in ("SentenceBoundary", "WordBoundary"):
                    boundaries.append(
                        {
                            "offset": _ticks_to_seconds(chunk.get("offset")),
                            "duration": _ticks_to_seconds(chunk.get("duration")),
                            "text": str(chunk.get("text") or ""),
                        }
                    )
            output_path.write_bytes(bytes(audio))
            logger.info(
                f"Synthesized {len(cleaned)} chars to {output_path} "
                f"({len(boundaries)} boundaries)"
            )
            return boundaries
        except Exception as e:
            logger.error(f"Boundary capture failed, falling back to plain synthesis: {e}")
            fallback = edge_tts.Communicate(text=cleaned, voice=voice, rate=self.rate)
            await fallback.save(str(output_path))
            return []

    async def get_duration(self, audio_path: Path) -> float:
        import subprocess

        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(audio_path),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            return float(result.stdout.strip())
        except Exception as e:
            logger.error(f"Failed to get audio duration: {e}")
            raise

    @classmethod
    def list_voices(cls) -> dict[str, str]:
        return cls.VOICES.copy()
