"""Subtitle generator for video captions."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from ..core.tts_engine import EdgeTTSEngine

logger = logging.getLogger(__name__)

# Boundary text ending with one of these reads as a finished sentence, so a
# subtitle line should break there rather than merge with the next one.
_SENTENCE_END_CHARS = "。！？!?；;…"

# Clause punctuation: a long sentence is split here first so lines break at
# natural reading pauses instead of every N characters.
_CLAUSE_SPLIT_CHARS = "，、；：,;:"
_CLAUSE_SPLIT_RE = re.compile(f"([{re.escape(_CLAUSE_SPLIT_CHARS)}])")

# Trailing punctuation is dropped from the *displayed* line (question/exclaim
# marks are kept because they carry meaning).
_DISPLAY_STRIP_CHARS = "，。、；：,.;:"

# A trailing chunk this short looks like an orphan line ("么久？"), so merge it
# into the previous line instead of flashing it alone.
_MIN_LINE_CHARS = 4


def _as_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0



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
                current_time += line_duration

        return subtitles

    def generate_for_segments(self, segments: list[dict]) -> list[Subtitle]:
        """Generate subtitles per segment with narration-relative timing.

        Each segment dict has ``text`` and ``duration`` and may carry ``offset``
        (start of the segment in narration time; default = running sum of the
        previous segment durations) and ``boundaries`` (list of
        ``{"offset", "duration", "text"}`` timing units relative to the segment
        start). Times are returned relative to narration start (t=0 = start of
        segment 0), so callers must not add the cover hold themselves.

        Unlike :meth:`generate`, no accumulating inter-line gap is added: each
        segment's lines are contiguous and the last line of a segment ends exactly
        at ``offset + duration``.
        """
        subtitles: list[Subtitle] = []
        running_offset = 0.0
        for segment in segments or []:
            duration = _as_float(segment.get("duration"))
            raw_offset = segment.get("offset")
            offset = running_offset if raw_offset is None else _as_float(raw_offset)
            running_offset = offset + duration

            boundaries = segment.get("boundaries") or []
            if boundaries:
                subtitles.extend(
                    self._subtitles_from_boundaries(boundaries, duration, offset)
                )
            else:
                subtitles.extend(
                    self._subtitles_from_text(
                        str(segment.get("text") or ""), duration, offset
                    )
                )

        for i, subtitle in enumerate(subtitles, start=1):
            subtitle.index = i
        return subtitles

    def _subtitles_from_text(self, text: str, duration: float, offset: float) -> list[Subtitle]:
        """Fallback: split text into sentence lines and share only this duration."""
        lines: list[str] = []
        for sentence in self._split_sentences(text):
            lines.extend(self._split_into_lines(sentence))
        lines = [line for line in lines if line.strip()]
        if not lines:
            return []
        total_chars = sum(len(line) for line in lines)
        if total_chars <= 0:
            return []

        result: list[Subtitle] = []
        current = offset
        for i, line in enumerate(lines):
            if i == len(lines) - 1:
                end = offset + duration
            else:
                end = current + duration * (len(line) / total_chars)
            if end < current:
                end = current
            result.append(Subtitle(index=0, start_time=current, end_time=end, text=line))
            current = end
        return result

    def _subtitles_from_boundaries(
        self, boundaries: list[dict], duration: float, offset: float
    ) -> list[Subtitle]:
        """Build lines from TTS boundaries, keeping each line's own timing."""
        raw: list[tuple[str, float, float]] = []
        current_text = ""
        current_start = 0.0
        current_end = 0.0

        def flush() -> None:
            nonlocal current_text, current_start, current_end
            if current_text:
                raw.append((current_text, current_start, current_end))
            current_text, current_start, current_end = "", 0.0, 0.0

        for boundary in boundaries:
            if not isinstance(boundary, dict):
                continue
            text = str(boundary.get("text") or "").strip()
            if not text:
                continue
            start = _as_float(boundary.get("offset"))
            boundary_duration = _as_float(boundary.get("duration"))
            end = start + boundary_duration

            if len(text) > self.max_chars_per_line:
                # Long sentence: split first at clause punctuation, greedily pack
                # clauses into lines <= max_chars_per_line, hard-wrap only a
                # clause that is itself too long, and time each piece
                # proportionally within its own window.
                flush()
                pieces = self._split_sentence_pieces(text)
                total = len(text)
                chunk_start = start
                for piece in pieces:
                    chunk_duration = boundary_duration * (len(piece) / total) if total else 0.0
                    raw.append((piece, chunk_start, chunk_start + chunk_duration))
                    chunk_start += chunk_duration
                continue

            if current_text and len(current_text) + len(text) > self.max_chars_per_line:
                flush()
            if not current_text:
                current_start = start
            current_text += text
            current_end = end
            if text[-1] in _SENTENCE_END_CHARS:
                flush()
        flush()

        result: list[Subtitle] = []
        for i, (text, start, end) in enumerate(raw):
            # Bridge a sub-0.3s gap so the following line does not flash empty.
            if i + 1 < len(raw) and raw[i + 1][1] - end < 0.3:
                end = raw[i + 1][1]
            start = max(0.0, min(start, duration))
            end = max(start, min(end, duration))
            display = self._display_text(text)
            result.append(
                Subtitle(index=0, start_time=offset + start, end_time=offset + end, text=display)
            )
        return result

    def _split_sentence_pieces(self, text: str) -> list[str]:
        """Break a long sentence into <= max_chars_per_line lines.

        Clauses (split on ``_CLAUSE_SPLIT_CHARS``) are greedily packed; only a
        clause that is itself over the limit is hard-wrapped. A final chunk
        shorter than ``_MIN_LINE_CHARS`` is merged into the previous line so no
        orphan flashes on screen. Punctuation is kept here (timing is weighted by
        the full text length); :meth:`_display_text` strips it for display.
        """
        clauses = self._split_clauses(text)
        lines: list[str] = []
        current = ""
        for clause in clauses:
            if len(clause) <= self.max_chars_per_line:
                if current and len(current) + len(clause) > self.max_chars_per_line:
                    lines.append(current)
                    current = clause
                else:
                    current += clause
                continue
            # A single clause too long to fit: flush, then hard-wrap it.
            if current:
                lines.append(current)
                current = ""
            lines.extend(self._split_into_lines(clause))
        if current:
            lines.append(current)

        # Merge a tiny trailing orphan into the previous line.
        if len(lines) >= 2 and len(lines[-1]) < _MIN_LINE_CHARS:
            lines[-2] = lines[-2] + lines[-1]
            lines.pop()

        return [line for line in lines if line.strip()]

    @staticmethod
    def _display_text(text: str) -> str:
        """Strip trailing clause punctuation from a displayed line."""
        return text.rstrip(_DISPLAY_STRIP_CHARS)

    @staticmethod
    def _split_clauses(text: str) -> list[str]:
        """Split ``text`` on clause punctuation, keeping the punctuation."""
        parts = _CLAUSE_SPLIT_RE.split(text)
        clauses: list[str] = []
        for i in range(0, len(parts), 2):
            chunk = parts[i]
            if i + 1 < len(parts):
                chunk += parts[i + 1]
            if chunk:
                clauses.append(chunk)
        return clauses

    def _split_sentences(self, text: str) -> list[str]:
        """Split text into sentences."""
        # Split on Chinese and English punctuation
        pattern = r'[。！？!?,，、；;：:]'
        sentences = re.split(pattern, text)
        return [s.strip() for s in sentences if s.strip()]

    def _split_into_lines(self, text: str) -> list[str]:
        """Hard-wrap a single (already clause-split) chunk of text."""
        if len(text) <= self.max_chars_per_line:
            return [text] if text else []

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
