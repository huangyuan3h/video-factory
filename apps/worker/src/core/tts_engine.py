"""Edge-TTS based text-to-speech engine."""

import logging
import tempfile
from pathlib import Path

import edge_tts

from ..config import settings

logger = logging.getLogger(__name__)


class EdgeTTSEngine:
    """Edge-TTS engine for Chinese voice synthesis."""

    # Available Chinese voices
    VOICES = {
        "zh-CN-XiaoxiaoNeural": "Xiaoxiao (Female, Natural) - Recommended for general content",
        "zh-CN-YunxiNeural": "Yunxi (Male, Sunny) - Good for tech and lifestyle",
        "zh-CN-YunjianNeural": "Yunjian (Male, News) - Best for news and formal content",
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
    ) -> Path:
        """Synthesize speech from text.

        Args:
            text: Text to synthesize
            output_path: Output file path (defaults to temp file)
            voice: Voice to use (defaults to configured voice)

        Returns:
            Path to the generated audio file
        """
        voice = voice or self.voice

        if output_path is None:
            output_path = Path(tempfile.mktemp(suffix=".mp3"))

        try:
            communicate = edge_tts.Communicate(
                text=text,
                voice=voice,
                rate=self.rate,
            )
            await communicate.save(str(output_path))

            logger.info(f"Synthesized {len(text)} chars to {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"TTS synthesis failed: {e}")
            raise

    async def get_duration(self, audio_path: Path) -> float:
        """Get the duration of an audio file in seconds."""
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
        """List all available Chinese voices."""
        return cls.VOICES.copy()
