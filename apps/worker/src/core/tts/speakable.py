"""Strip thinking / markdown / emoji so TTS does not read markup aloud.

Ported from Fae-v2/backend/src/fae/tts/speakable.py
"""

from __future__ import annotations

import re

_THINK_TAG = re.compile(
    r"<think(?:ing)?\b[^>]*>[\s\S]*?</think(?:ing)?>",
    re.IGNORECASE,
)
_THINK_FENCE = re.compile(
    r"```(?:thinking|reasoning|thought)\s*\n[\s\S]*?```",
    re.IGNORECASE,
)
_CODE_FENCE = re.compile(r"```[\w+-]*\n?[\s\S]*?```")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_BLOCKQUOTE = re.compile(r"^>\s?", re.MULTILINE)
_HR = re.compile(r"^[-*_]{3,}\s*$", re.MULTILINE)
_BOLD = re.compile(r"\*\*\*([^*]+)\*\*\*|\*\*([^*]+)\*\*|__([^_]+)__")
_ITALIC = re.compile(r"\*([^*\n]+)\*|_([^_\n]+)_")
_STRIKE = re.compile(r"~~([^~]+)~~")
_LIST = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_NUM_LIST = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)
_MD_NOISE = re.compile(r"[*_~`#]")
_PIPE_TABLE = re.compile(r"(?:^|\n)(?:\|[^\n]*\|(?:\n|$))+")
_TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)

_EMOJI_RANGES = (
    "\U0001F1E0-\U0001F1FF"
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U0001FB00-\U0001FBFF"
    "\u2600-\u26FF"
    "\u2700-\u27BF"
    "\u2300-\u23FF"
    "\u2B00-\u2BFF"
    "\u2900-\u297F"
    "\uFE00-\uFE0F"
    "\U0001F3FB-\U0001F3FF"
)
_EMOJI_RUN = re.compile(
    f"[\u200d{_EMOJI_RANGES}]+(?:\u200d[\u200d{_EMOJI_RANGES}]+)*",
    re.UNICODE,
)

_INVISIBLE = re.compile(
    "[\u200B-\u200F\u202A-\u202E\u2060-\u206F\uFEFF"
    "\U000E0020-\U000E007F"
    "\u00AD]"
)
_LONE_SURROGATE = re.compile(
    "[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]"
)
_ASCII_KAOMOJI = re.compile(
    r"(?:"
    r"[:;=8][\-o*']?[\)\]\(\[dDpP/\\{}|><*^@_~]+"
    r"|"
    r"[\(\[]+[\-_o*^~]?[_\-^～~\.\\]*[\\^▽°´☆\*][\-_o*^~]?[\)\]]+"
    r"|"
    r"[\)\]\(\[dDpP/\\{}|><*^@]+[\-o*']?[:;=]"
    r")"
)
_FILLERS = re.compile(
    r"\b(?:"
    r"lmao+|lol+|rofl+|haha+|hehe+|hihi+|x[dD]|"
    r"omg|wtf|btw|idk|smh|fml|yolo|nvm|imo|imho|tbh"
    r")+\b[~～]?",
    re.IGNORECASE,
)
_PUNCT_RUN = re.compile(r"([。！？!?~～.,，、；：])\1{1,}")
# A comma directly before terminal punctuation is an artefact of em-dash /
# ellipsis normalisation ("你好，。"); drop the comma and keep the terminal mark.
_MIXED_COMMA = re.compile(r"[，,](?=[。！？；：!?;:])")
_WAVY = re.compile(r"\s*[~～]+\s*")

# Quote / bracket marks are removed rather than spoken. A mark between two CJK
# neighbours disappears cleanly ("《广场协议》" -> "广场协议"); between two ASCII
# word characters it becomes a single space so English words do not glue
# ("Adam's(2020)" -> "Adam's 2020"). Apostrophes inside English words are kept.
_QUOTE_BRACKET_CHARS = (
    "\u201c\u201d\u2018\u2019"
    "\u300c\u300d\u300e\u300f"
    "\u300a\u300b\u3008\u3009"
    "\u3010\u3011\u3014\u3015"
    "\uff08\uff09"
    "()"
    "\"'\u0027"
)
_QUOTE_BRACKET = re.compile(f"[{re.escape(_QUOTE_BRACKET_CHARS)}]")
# Public: the exact set of marks normalisation removes, so subtitle alignment can
# compare on a "skeleton" of the original text (see core.subtitle_gen).
STRIPPED_MARKS = frozenset(_QUOTE_BRACKET_CHARS)
_APOSTROPHES = ("'", "\u2019")
_EM_DASH = re.compile(r"\u2014{1,}")
_ELLIPSIS = re.compile(r"\u2026{1,}")


def _is_ascii_word_char(ch: str) -> bool:
    return bool(ch) and ch.isascii() and ch.isalnum()


def _remove_quote_bracket(match: re.Match) -> str:
    text = match.string
    i = match.start()
    prev = text[i - 1] if i > 0 else ""
    nxt = text[i + 1] if i + 1 < len(text) else ""
    if match.group() in _APOSTROPHES and _is_ascii_word_char(prev) and _is_ascii_word_char(nxt):
        return match.group()
    if _is_ascii_word_char(prev) and _is_ascii_word_char(nxt):
        return " "
    return ""


def _drop_emoji(text: str) -> str:
    return _EMOJI_RUN.sub(" ", text)


def _normalize_punct(text: str) -> str:
    text = _PUNCT_RUN.sub(r"\1", text)
    text = _MIXED_COMMA.sub("", text)
    text = text.replace("　", " ").replace("‍", "")
    return text


def _collapse(text: str) -> str:
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def to_speakable_text(text: str) -> str:
    if not text:
        return ""
    s = _THINK_TAG.sub("", text)
    s = _THINK_FENCE.sub("", s)
    s = s.replace("||", "|\n|")
    s = _CODE_FENCE.sub("\n", s)
    s = _PIPE_TABLE.sub("\n", s)
    s = _TABLE_LINE.sub("", s)
    s = _INLINE_CODE.sub(r"\1", s)
    s = _IMAGE.sub(r"\1", s)
    s = _LINK.sub(r"\1", s)
    s = _HEADING.sub("", s)
    s = _BLOCKQUOTE.sub("", s)
    s = _HR.sub("", s)
    s = _BOLD.sub(
        lambda m: next(g for g in m.groups() if g is not None),
        s,
    )
    s = _ITALIC.sub(
        lambda m: next(g for g in m.groups() if g is not None),
        s,
    )
    s = _STRIKE.sub(r"\1", s)
    s = _LIST.sub("", s)
    s = _NUM_LIST.sub("", s)
    s = s.replace("|", " ")
    s = _MD_NOISE.sub("", s)

    s = _LONE_SURROGATE.sub("", s)
    s = _drop_emoji(s)
    s = _INVISIBLE.sub(" ", s)
    s = _ASCII_KAOMOJI.sub(" ", s)
    s = _FILLERS.sub(" ", s)
    s = _WAVY.sub(" ", s)
    s = _QUOTE_BRACKET.sub(_remove_quote_bracket, s)
    # Em dashes and ellipses are real spoken pauses. The adjacent terminator is
    # kept so "……。" collapses to "。" (never "，。").
    s = _EM_DASH.sub("，", s)
    s = _ELLIPSIS.sub("，", s)
    s = _normalize_punct(s)
    s = _collapse(s)
    return s


def clip_for_local_tts(text: str, max_chars: int = 240) -> str:
    s = (text or "").strip()
    if len(s) <= max_chars:
        return s
    window = s[: max_chars + 1]
    for sep in ("。", "！", "？", "；", "\n", ". ", "! ", "? "):
        idx = window.rfind(sep)
        if idx >= max_chars // 3:
            return window[: idx + len(sep)].strip()
    return window[:max_chars].rstrip() + "…"
