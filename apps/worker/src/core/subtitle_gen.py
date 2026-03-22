"""Subtitle generator for video captions."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from ..core.tts_engine import EdgeTTSEngine

logger = logging.getLogger(__name__)


@dataclass
class Subtitle:
    """A single subtitle entry."""

    index: int
    start_time: float  # seconds
    end_time: float  # seconds
    text: str

    def to_srt(self) -> str:
        """Convert to SRT format."""
        start = self._format_time(self.start_time)
        end = self._format_time(self.end_time)
        return f"{self.index}\n{start} --> {end}\n{self.text}\n"

    def to_ass(self, style: str = "Default") -> str:
        """Convert to ASS format dialogue line."""
        start = self._format_ass_time(self.start_time)
        end = self._format_ass_time(self.end_time)
        return f"Dialogue: 0,{start},{end},{style},,0,0,0,,{self.text}\n"

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Format time for SRT (HH:MM:SS,mmm)."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    @staticmethod
    def _format_ass_time(seconds: float) -> str:
        """Format time for ASS (H:MM:SS.cc)."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours}:{minutes:02d}:{secs:05.2f}"


class SubtitleGenerator:
    """Generate subtitles for video content."""

    def __init__(
        self,
        chars_per_second: float = 4.0,
        max_chars_per_line: int = 20,
    ):
        self.chars_per_second = chars_per_second
        self.max_chars_per_line = max_chars_per_line

    async def generate(
        self,
        text: str,
        audio_path: Path | None = None,
        audio_duration: float | None = None,
    ) -> list[Subtitle]:
        """Generate subtitles from text.

        Args:
            text: The text content
            audio_path: Path to audio file (for duration)
            audio_duration: Audio duration in seconds

        Returns:
            List of Subtitle objects
        """
        # Get audio duration if not provided
        if audio_duration is None and audio_path:
            tts = EdgeTTSEngine()
            audio_duration = await tts.get_duration(audio_path)

        if audio_duration is None:
            # Estimate based on text length
            audio_duration = len(text) / self.chars_per_second

        # Split text into sentences
        sentences = self._split_sentences(text)

        # Calculate timing
        total_chars = sum(len(s) for s in sentences)
        subtitles = []
        current_time = 0.0

        for i, sentence in enumerate(sentences):
            if not sentence.strip():
                continue

            # Calculate duration for this sentence
            char_ratio = len(sentence) / total_chars
            duration = audio_duration * char_ratio

            # Split into lines if needed
            lines = self._split_into_lines(sentence)

            for line in lines:
                line_duration = duration * (len(line) / len(sentence))

                subtitle = Subtitle(
                    index=len(subtitles) + 1,
                    start_time=current_time,
                    end_time=current_time + line_duration,
                    text=line,
                )
                subtitles.append(subtitle)
                current_time += line_duration + 0.1  # Small gap

        return subtitles

    def _split_sentences(self, text: str) -> list[str]:
        """Split text into sentences."""
        # Split on Chinese and English punctuation
        pattern = r'[。！？!?,，、；;：:]'
        sentences = re.split(pattern, text)
        return [s.strip() for s in sentences if s.strip()]

    def _split_into_lines(self, text: str) -> list[str]:
        """Split long text into multiple lines."""
        if len(text) <= self.max_chars_per_line:
            return [text]

        lines = []
        current_line = ""

        for char in text:
            current_line += char
            if len(current_line) >= self.max_chars_per_line:
                lines.append(current_line)
                current_line = ""

        if current_line:
            lines.append(current_line)

        return lines

    def generate_srt(self, subtitles: list[Subtitle]) -> str:
        """Generate SRT format subtitle file content."""
        return "".join(sub.to_srt() for sub in subtitles)

    def generate_ass(
        self,
        subtitles: list[Subtitle],
        font_name: str = "Microsoft YaHei",
        font_size: int = 48,
        primary_color: str = "&H00FFFFFF",
        outline_color: str = "&H00000000",
    ) -> str:
        """Generate ASS format subtitle file content."""
        ass_header = f"""[Script Info]
Title: Video Factory Subtitles
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{primary_color},&H000000FF,{outline_color},&H00000000,0,0,0,0,100,100,0,0,1,3,0,2,10,10,50,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        dialogue = "".join(sub.to_ass() for sub in subtitles)
        return ass_header + dialogue

    async def save_srt(self, subtitles: list[Subtitle], output_path: Path) -> Path:
        """Save subtitles to SRT file."""
        content = self.generate_srt(subtitles)
        output_path.write_text(content, encoding="utf-8")
        logger.info(f"Saved SRT to {output_path}")
        return output_path

    async def save_ass(
        self,
        subtitles: list[Subtitle],
        output_path: Path,
        font_name: str = "Microsoft YaHei",
        font_size: int = 48,
        primary_color: str = "&H00FFFFFF",
        outline_color: str = "&H00000000",
    ) -> Path:
        """Save subtitles to ASS file."""
        content = self.generate_ass(
            subtitles,
            font_name=font_name,
            font_size=font_size,
            primary_color=primary_color,
            outline_color=outline_color,
        )
        output_path.write_text(content, encoding="utf-8")
        logger.info(f"Saved ASS to {output_path}")
        return output_path
