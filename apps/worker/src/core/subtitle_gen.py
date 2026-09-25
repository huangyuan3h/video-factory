"""Subtitle generator for video captions."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from ..core.tts.speakable import STRIPPED_MARKS
from ..core.tts.speech_runs import snap_cues
from ..core.tts_engine import EdgeTTSEngine

logger = logging.getLogger(__name__)

# Characters that TTS normalisation drops (quote/bracket marks). Subtitle display
# text is recovered from the *original* script by walking a skeleton where these
# marks and whitespace are removed, then mapping back to original offsets.
_ALIGN_STRIP_MARKS = STRIPPED_MARKS

# Boundary text ending with one of these reads as a finished sentence, so a
# subtitle line should break there rather than merge with the next one.
_SENTENCE_END_CHARS = "。！？!?；;…"

# Clause punctuation: a long sentence is split here first so lines break at
# natural reading pauses instead of every N characters.
_CLAUSE_SPLIT_CHARS = "，、；：,;:"
_CLAUSE_SPLIT_RE = re.compile(f"[{re.escape(_CLAUSE_SPLIT_CHARS)}]")

# Trailing punctuation is dropped from the *displayed* line (question/exclaim
# marks are kept because they carry meaning).
_DISPLAY_STRIP_CHARS = "，。、；：,.;:"

# Characters that count as "CJK" for display normalization: CJK punctuation,
# kana, ideographs and full-width forms. TTS-cleaned text can lose 《》/、 to
# spaces and commas, so lines are re-normalized before being shown.
_CJK_CHARS = (
    "\u3000-\u303F"
    "\u3040-\u30FF"
    "\u3400-\u4DBF"
    "\u4E00-\u9FFF"
    "\uF900-\uFAFF"
    "\uFF00-\uFFEF"
)
_CJK_RE = re.compile(f"[{_CJK_CHARS}]")
# Whitespace sandwiched between two CJK characters/punctuation is an artefact
# of quote/ideographic-comma cleaning, so it is dropped from display.
_CJK_WS_RE = re.compile(f"(?<=[{_CJK_CHARS}])[ \t\u3000]+(?=[{_CJK_CHARS}])")
# CJK *word* characters (kana/ideographs) count as one spoken unit each; CJK
# punctuation and whitespace do not.
_SPOKEN_CJK_RE = re.compile("[\u3040-\u30FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]")
_ASCII_CLAUSE_PUNCT_RE = re.compile(r"[,;:]")
_ASCII_TO_FULLWIDTH = {",": "，", ";": "；", ":": "："}
# Runs of the same clause punctuation collapse to a single full-width mark.
_REPEATED_PUNCT_RES = (
    (re.compile(r"[，,]{2,}"), "，"),
    (re.compile(r"[；;]{2,}"), "；"),
    (re.compile(r"[：:]{2,}"), "："),
)
_DISPLAY_LEADING_STRIP_CHARS = " \t\u3000" + _DISPLAY_STRIP_CHARS
_DISPLAY_TRAILING_STRIP_CHARS = " \t\u3000" + _DISPLAY_STRIP_CHARS

# A run of ASCII letters/digits is one unbreakable wrapping unit. Decimal and
# thousand separators plus a trailing percent stay attached so "15.5",
# "1,000", "52.4%", "3:00", "CDO" and "2004" are never split mid-number.
_UNIT_RE = re.compile(r"[A-Za-z0-9]+(?:[.,:][0-9]+)*%?|.")

# A trailing chunk this short looks like an orphan line ("么久？"), so merge it
# into the previous line instead of flashing it alone.
_MIN_LINE_CHARS = 4

# TTS normalisation (see core.tts.speakable) drops a leading "+" number sign
# ("+1.7%" -> "1.7%") and speaks a digit range dash/tilde as "到"
# ("2010—2026" -> "2010到2026"). Alignment compares skeletons where those
# changes are applied to *both* the original and the boundary text, so the
# displayed span is still recovered from the untouched original characters.
_RANGE_DASH_CHARS = "\u2013\u2014~\uff5e-"
_PLUS_CHARS = "+\uff0b"


def _is_ascii_word_char(ch: str) -> bool:
    return bool(ch) and ch.isascii() and ch.isalnum()


def _is_number_sign_plus(text: str, index: int) -> bool:
    """Whether ``text[index]`` is a "+" TTS drops (a sign before a number)."""
    if text[index] not in _PLUS_CHARS:
        return False
    following = text[index + 1] if index + 1 < len(text) else ""
    if not following.isdigit():
        return False
    previous = text[index - 1] if index > 0 else ""
    return not _is_ascii_word_char(previous)


def _is_range_dash(text: str, index: int) -> bool:
    """Whether ``text[index]`` is a dash TTS speaks as "到" (a digit range)."""
    left = index - 1
    while left >= 0 and text[left].isspace():
        left -= 1
    if left < 0:
        return False
    if text[left] in "年月日":
        left -= 1
        while left >= 0 and text[left].isspace():
            left -= 1
        if left < 0:
            return False
    if not text[left].isdigit():
        return False
    right = index + 1
    while right < len(text) and text[right].isspace():
        right += 1
    return right < len(text) and text[right].isdigit()


def _alignment_chars(text: str):
    """Yield ``(comparison_char, original_index)`` pairs for alignment matching.

    Whitespace and stripped marks are dropped, a number-sign "+" is dropped,
    and a run of range dashes collapses to a single "到" pinned to the first
    dash, so a matched skeleton span maps back to the original characters.
    """
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char.isspace() or char in _ALIGN_STRIP_MARKS:
            index += 1
            continue
        if char in _PLUS_CHARS and _is_number_sign_plus(text, index):
            index += 1
            continue
        if char in _RANGE_DASH_CHARS and _is_range_dash(text, index):
            yield "到", index
            index += 1
            while index < length and (
                text[index].isspace() or text[index] in _RANGE_DASH_CHARS
            ):
                index += 1
            continue
        yield char, index
        index += 1


def _as_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _spoken_weight(text: str) -> float:
    """Estimate how long ``text`` takes to speak, in character-equivalents.

    TTS reads digits one by one, spells out ``%`` as ``百分之`` (3), ``-`` as
    ``负`` (1) and an inter-digit ``.`` as ``点`` (1); a thousands comma in a
    number costs a group (``万``/``千`` approximation). Punctuation and spaces
    cost nothing, and each CJK/ASCII word character costs one. Numbers therefore
    weigh far more than ``len()`` suggests, which keeps split-line timing honest.
    """
    total = 0.0
    previous = ""
    for index, char in enumerate(text):
        following = text[index + 1] if index + 1 < len(text) else ""
        if char.isdigit():
            total += 1
        elif char == "." and previous.isdigit() and following.isdigit():
            total += 1
        elif char == "%":
            total += 3
        elif char == "," and previous.isdigit() and following.isdigit():
            total += 1
        elif char in "-−" and following.isdigit():
            total += 1
        elif _SPOKEN_CJK_RE.match(char) or (char.isascii() and char.isalpha()):
            total += 1
        previous = char
    return total



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
                segment_subtitles = self._subtitles_from_boundaries(
                    boundaries,
                    duration,
                    offset,
                    source_text=str(segment.get("text") or ""),
                )
            else:
                segment_subtitles = self._subtitles_from_text(
                    str(segment.get("text") or ""), duration, offset
                )
            speech_runs = segment.get("speech_runs") or []
            if speech_runs and segment_subtitles:
                self._snap_segment_subtitles(segment_subtitles, speech_runs, offset, duration)
            subtitles.extend(segment_subtitles)

        for i, subtitle in enumerate(subtitles, start=1):
            subtitle.index = i
        return subtitles

    def _snap_segment_subtitles(
        self,
        subtitles: list[Subtitle],
        speech_runs: list,
        offset: float,
        duration: float,
    ) -> None:
        """Nudge one segment's cue starts onto measured speech onsets in place.

        Cues are shifted to segment-relative time, snapped, then shifted back.
        The final cue never runs past ``offset + duration``.
        """
        relative = [(sub.start_time - offset, sub.end_time - offset) for sub in subtitles]
        segment_end = offset + duration
        for sub, (start, end) in zip(subtitles, snap_cues(relative, speech_runs)):
            sub.start_time = offset + start
            sub.end_time = min(offset + end, segment_end)
            if sub.end_time < sub.start_time:
                sub.end_time = sub.start_time

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
        return self._merge_invisible(result)

    def _subtitles_from_boundaries(
        self,
        boundaries: list[dict],
        duration: float,
        offset: float,
        source_text: str = "",
    ) -> list[Subtitle]:
        """Build lines from TTS boundaries, keeping each line's own timing.

        Boundary text is the *TTS-cleaned* sentence (``《广场协议》`` -> ``广场协议``).
        When ``source_text`` (the original segment text) is available each
        boundary is re-aligned to its span in the original so the displayed line
        keeps the brackets/quotes; on any mismatch the boundary text is used
        unchanged.
        """
        raw: list[tuple[str, float, float]] = []
        current_text = ""
        current_start = 0.0
        current_end = 0.0

        source_text = str(source_text or "")
        skeleton, mapping = self._build_skeleton(source_text)
        cursor = 0

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
            text, cursor = self._align_to_source(
                text, source_text, skeleton, mapping, cursor
            )
            start = _as_float(boundary.get("offset"))
            boundary_duration = _as_float(boundary.get("duration"))
            end = start + boundary_duration

            if not self._fits(text):
                # Long sentence: split first at clause punctuation, greedily pack
                # clauses into lines <= max_chars_per_line, hard-wrap only a
                # clause that is itself too long, and time each piece
                # proportionally within its own window.
                flush()
                pieces = self._split_sentence_pieces(text)
                weights = [_spoken_weight(piece) for piece in pieces]
                total = sum(weights)
                chunk_start = start
                for piece, weight in zip(pieces, weights):
                    if total > 0:
                        chunk_duration = boundary_duration * (weight / total)
                    else:
                        chunk_duration = boundary_duration / len(pieces)
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
        return self._merge_invisible(result)

    @staticmethod
    def _build_skeleton(text: str) -> tuple[str, list[int]]:
        """Skeleton of ``text`` (marks/whitespace dropped) + index -> original.

        The skeleton also applies the TTS-speakable folds a boundary text is
        subject to (dropped "+" signs, range dashes folded to "到") so a cleaned
        boundary can still match. ``mapping[i]`` is the offset in ``text`` of the
        i-th skeleton character, so a matched skeleton span maps back to the
        original span.
        """
        chars: list[str] = []
        mapping: list[int] = []
        for char, original_index in _alignment_chars(text):
            chars.append(char)
            mapping.append(original_index)
        return "".join(chars), mapping

    @classmethod
    def _align_to_source(
        cls,
        text: str,
        source_text: str,
        skeleton: str,
        mapping: list[int],
        cursor: int,
    ) -> tuple[str, int]:
        """Map a TTS boundary ``text`` back to its span in ``source_text``.

        Returns ``(display_source, new_cursor)``. The new cursor is only advanced
        when the match succeeds; failures leave it untouched so the next
        boundary can still align.
        """
        if not text or not source_text or not skeleton:
            return text, cursor
        boundary_skeleton = "".join(char for char, _ in _alignment_chars(text))
        if not boundary_skeleton:
            return text, cursor
        position = skeleton.find(boundary_skeleton, cursor)
        if position < 0:
            return text, cursor

        start = mapping[position]
        end = mapping[position + len(boundary_skeleton) - 1] + 1
        # Re-attach adjacent stripped marks ("《" before "广场协议》"), a dropped
        # number-sign "+" ("+3.6%"), and squeeze out any surrounding whitespace.
        while start > 0:
            previous = source_text[start - 1]
            if previous.isspace() or previous in _ALIGN_STRIP_MARKS:
                start -= 1
            elif previous in _PLUS_CHARS and _is_number_sign_plus(source_text, start - 1):
                start -= 1
            else:
                break
        while end < len(source_text) and (
            source_text[end].isspace() or source_text[end] in _ALIGN_STRIP_MARKS
        ):
            end += 1
        return source_text[start:end].strip(), position + len(boundary_skeleton)

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
            # Trailing punctuation is not displayed, so it must not count
            # toward the line width (a 21-char clause incl. "，" is really 20).
            if self._fits(clause):
                if current and not self._fits(current + clause):
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

    def _fits(self, text: str) -> bool:
        """Whether ``text`` fits a line, ignoring trailing (undisplayed) punctuation."""
        return len(text.rstrip(_DISPLAY_STRIP_CHARS)) <= self.max_chars_per_line

    @staticmethod
    def _display_text(text: str) -> str:
        """Normalize a boundary line into clean display text.

        TTS sentence boundaries carry the *cleaned* text: ``《》`` become spaces
        and ``、`` becomes ``,``, which leaks artefacts like
        ``"签订了,广场协议 "``. This converts ASCII clause punctuation next to
        CJK into full-width marks, removes whitespace stranded between CJK
        characters, collapses repeated clause punctuation, and trims stray
        leading/trailing punctuation and whitespace. ASCII text such as
        ``3:00``, ``1,000``, ``52.4%`` and ``Hello, world`` is left untouched.
        """
        if not text:
            return ""

        def _fullwidth(match: re.Match) -> str:
            i = match.start()
            prev = text[i - 1] if i > 0 else ""
            nxt = text[i + 1] if i + 1 < len(text) else ""
            if prev.isdigit() and nxt.isdigit():
                return match.group()
            if _CJK_RE.fullmatch(prev) or _CJK_RE.fullmatch(nxt):
                return _ASCII_TO_FULLWIDTH[match.group()]
            return match.group()

        result = _ASCII_CLAUSE_PUNCT_RE.sub(_fullwidth, text)
        result = _CJK_WS_RE.sub("", result)
        for pattern, replacement in _REPEATED_PUNCT_RES:
            result = pattern.sub(replacement, result)
        result = result.lstrip(_DISPLAY_LEADING_STRIP_CHARS)
        return result.rstrip(_DISPLAY_TRAILING_STRIP_CHARS)

    @staticmethod
    def _has_visible_text(text: str) -> bool:
        """True when ``text`` contains anything other than punctuation/space."""
        return bool(re.sub(r"[\W_]+", "", text or ""))

    def _merge_invisible(self, subtitles: list[Subtitle]) -> list[Subtitle]:
        """Fold empty/only-punctuation lines into a neighbour's time window.

        A hard-wrapped clause can leave a line that displays as nothing (e.g. a
        lone "，"). Rather than flash a blank caption, extend the previous line's
        end time and drop the blank; a blank at the very start folds into the
        next line instead. Applies to both the boundary and text paths.
        """
        result: list[Subtitle] = []
        pending: Subtitle | None = None
        for sub in subtitles:
            if self._has_visible_text(sub.text):
                if pending is not None:
                    sub.start_time = min(sub.start_time, pending.start_time)
                    pending = None
                result.append(sub)
            elif result:
                previous = result[-1]
                previous.end_time = max(previous.end_time, sub.end_time)
                previous.text = self._display_text(previous.text + sub.text)
            elif pending is None:
                pending = sub
            else:
                pending.end_time = max(pending.end_time, sub.end_time)
        return result

    @staticmethod
    def _split_clauses(text: str) -> list[str]:
        """Split ``text`` on clause punctuation, keeping the punctuation.

        A comma or colon sitting between two digits (``1,000``, ``3:00``) is
        part of a number rather than a clause break, so it is left intact.
        """
        clauses: list[str] = []
        start = 0
        for match in _CLAUSE_SPLIT_RE.finditer(text):
            i = match.start()
            if (
                match.group() in ",:"
                and 0 < i < len(text) - 1
                and text[i - 1].isdigit()
                and text[i + 1].isdigit()
            ):
                continue
            clauses.append(text[start : i + 1])
            start = i + 1
        if start < len(text):
            clauses.append(text[start:])
        return [clause for clause in clauses if clause]

    def _split_sentences(self, text: str) -> list[str]:
        """Split text into sentences."""
        # Split on Chinese and English punctuation
        pattern = r'[。！？!?,，、；;：:]'
        sentences = re.split(pattern, text)
        return [s.strip() for s in sentences if s.strip()]

    def _split_into_lines(self, text: str) -> list[str]:
        """Hard-wrap a single (already clause-split) chunk of text.

        Wrapping treats a run of ASCII letters/digits plus decimal/thousand
        separators and a trailing percent (``CDO``, ``2004``, ``15.5``,
        ``1,000``, ``52.4%``, ``3:00``) as one unbreakable unit so a line never
        splits inside a word or number. When a line is unavoidable, the units
        are packed into roughly equal lines (``ceil(remaining / lines_needed)``)
        instead of filling each line greedily and leaving a short tail.
        """
        if not text:
            return []
        if self._fits(text):
            return [text]

        units = _UNIT_RE.findall(text)
        # A unit wider than a whole line can only be split as a last resort.
        expanded: list[str] = []
        for unit in units:
            while len(unit) > self.max_chars_per_line:
                expanded.append(unit[: self.max_chars_per_line])
                unit = unit[self.max_chars_per_line :]
            if unit:
                expanded.append(unit)
        units = expanded
        if not units:
            return []

        lines: list[str] = []
        current = ""
        index = 0
        while index < len(units):
            if not current:
                current = units[index]
                index += 1
                continue
            remaining = len(current) + sum(len(u) for u in units[index:])
            lines_needed = max(
                1, -(-remaining // self.max_chars_per_line)
            )
            target = -(-remaining // lines_needed)
            unit = units[index]
            if len(current) + len(unit) <= self.max_chars_per_line and (
                len(current) < target or lines_needed <= 1
            ):
                current += unit
                index += 1
            else:
                lines.append(current)
                current = ""
        if current:
            lines.append(current)

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
