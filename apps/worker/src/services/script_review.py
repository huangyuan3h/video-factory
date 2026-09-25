"""Script double-check before TTS: deterministic lint + optional LLM proofread.

Runs for content types whose preset has ``proofread=True`` (book / indicator).
Lint inspects the *final TTS input* (``to_speakable_text(seg.text)``); safe
mechanical issues are auto-fixed in the script text.  The LLM pass only accepts a
segment rewrite when the number-token multiset is identical, the length change is
<= 15% and the result is non-empty.

``ScriptReview`` is the reusable writer (``script_review.json`` + ``.md``) and is
extensible for G2 (per-segment ``extra`` fields such as chart / key_point).
"""

from __future__ import annotations

import difflib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..core.tts.speakable import STRIPPED_MARKS, to_speakable_text

logger = logging.getLogger(__name__)

_CJK_CHARS = (
    "\u3000-\u303F"
    "\u3040-\u30FF"
    "\u3400-\u4DBF"
    "\u4E00-\u9FFF"
    "\uF900-\uFAFF"
    "\uFF00-\uFFEF"
)
_CJK_RE = re.compile(f"[{_CJK_CHARS}]")
_ASCII_TO_FULLWIDTH = {",": "，", ";": "；", ":": "："}

_DOUBLED_PUNCT = re.compile(r"[，。、；：,.;:]{2,}")
_TERMINAL_PUNCT = "。！？!?"
_DOUBLED_PUNCT_CHARS = "，。、；：,.;:"
_LEADING_PUNCT = re.compile(r"^[，。、；：,.;:]+")
_SPLIT_NUMBER = re.compile(r"\d\.\s+\d|\d\s+\.\d|\d\s+%|\d\s+\d")
_MARKDOWN_LEFTOVER = re.compile(r"[*#`|\[\]()]")
_ASCII_CLAUSE = re.compile(r"[,;:]")

# Informational only: the TTS input normaliser turns a range dash/tilde between
# numbers into "到" and drops a leading "+" before a number, so the script text
# itself is left untouched.
_RANGE_DASH = re.compile(r"(?<=\d)\s*[\u2013\u2014]\s*(?=\d)")
_PLUS_SIGN = re.compile(r"(?<![0-9A-Za-z])[+\uff0b](?=\d)")

# Comma immediately before/after a quote or bracket is a TTS pause artefact.
_BRACKET_CLASS = "《》〈〉“”‘’「」『』【】〔〕（）()" + "".join(
    ch for ch in STRIPPED_MARKS if ch not in "《》〈〉“”‘’「」『』【】〔〕（）()"
)
_COMMA_AROUND_BRACKET = re.compile(
    r"[，,](?=\s*[" + re.escape(_BRACKET_CLASS) + r"])"
    r"|(?<=[" + re.escape(_BRACKET_CLASS) + r"])[，,]"
)
_COMMA_BEFORE_TERMINAL = re.compile(r"[，,]\s*(?=[。！？；：!?;:])")
# Residual quote/bracket marks the normaliser should have stripped.
_RESIDUAL_MARK = re.compile(f"[{re.escape(_BRACKET_CLASS)}]")

# Arabic numbers (decimals / percent / thousand / time separators) and Chinese
# numeral runs of length >= 2 (三点五, 一百三十八万, 十五). The multiset of these
# must be preserved exactly.
_ARABIC_NUMBER = re.compile(r"\d+(?:[.,:]\d+)*%?")
_CN_NUMERAL = re.compile(
    r"[零〇一二三四五六七八九十百千万亿两]+(?:点[零〇一二三四五六七八九十]+)?"
)


@dataclass
class Finding:
    code: str
    message: str
    snippet: str = ""

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "snippet": self.snippet}


def _snippet(text: str, start: int, end: int, pad: int = 8) -> str:
    lo = max(0, start - pad)
    hi = min(len(text), end + pad)
    return text[lo:hi]


def _lint_tts_punctuation(tts_input: str) -> list[Finding]:
    findings: list[Finding] = []
    for match in _DOUBLED_PUNCT.finditer(tts_input):
        findings.append(
            Finding(
                "doubled_punctuation",
                "TTS 输入存在重复/混排标点",
                _snippet(tts_input, match.start(), match.end()),
            )
        )
    leading = _LEADING_PUNCT.match(tts_input)
    if leading:
        findings.append(
            Finding(
                "leading_punctuation",
                "TTS 输入以标点开头",
                _snippet(tts_input, leading.start(), leading.end()),
            )
        )
    return findings


def _lint_ascii_punct_cjk(text: str) -> list[Finding]:
    findings: list[Finding] = []
    for match in _ASCII_CLAUSE.finditer(text):
        i = match.start()
        prev = text[i - 1] if i > 0 else ""
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if prev.isdigit() and nxt.isdigit():
            continue
        if _CJK_RE.fullmatch(prev) or _CJK_RE.fullmatch(nxt):
            findings.append(
                Finding(
                    "ascii_punctuation_cjk",
                    "半角标点紧邻中文",
                    _snippet(text, match.start(), match.end()),
                )
            )
    return findings


def _lint_long_unpunctuated(tts_input: str) -> list[Finding]:
    findings: list[Finding] = []
    for run in re.split(r"[。！？!?；;，,、：:\s]+", tts_input):
        if len(run) > 60:
            findings.append(
                Finding(
                    "long_unpunctuated",
                    "超过 60 字没有标点",
                    run[:30],
                )
            )
    return findings


def _lint_split_numbers(*texts: str) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[str] = set()
    for text in texts:
        for match in _SPLIT_NUMBER.finditer(text):
            if match.group() in seen:
                continue
            seen.add(match.group())
            findings.append(
                Finding(
                    "split_number",
                    "数字/百分号被空格拆开",
                    _snippet(text, match.start(), match.end()),
                )
            )
    return findings


def _lint_range_dash(*texts: str) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[str] = set()
    for text in texts:
        for match in _RANGE_DASH.finditer(text):
            if match.group() in seen:
                continue
            seen.add(match.group())
            findings.append(
                Finding(
                    "range_dash",
                    "数字间有破折号/波浪号区间（TTS 读作“到”）",
                    _snippet(text, match.start(), match.end()),
                )
            )
    return findings


def _lint_plus_sign(*texts: str) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[str] = set()
    for text in texts:
        for match in _PLUS_SIGN.finditer(text):
            if match.group() in seen:
                continue
            seen.add(match.group())
            findings.append(
                Finding(
                    "plus_sign",
                    "数字前有正号（TTS 会忽略）",
                    _snippet(text, match.start(), match.end()),
                )
            )
    return findings


def _lint_markdown(*texts: str) -> list[Finding]:
    findings: list[Finding] = []
    for text in texts:
        match = _MARKDOWN_LEFTOVER.search(text)
        if match:
            findings.append(
                Finding(
                    "markdown_leftover",
                    "残留 Markdown 标记",
                    _snippet(text, match.start(), match.end()),
                )
            )
    return findings


def _lint_comma_near_bracket(original: str) -> list[Finding]:
    findings: list[Finding] = []
    for match in _COMMA_AROUND_BRACKET.finditer(original):
        findings.append(
            Finding(
                "comma_near_bracket",
                "书名号/引号旁有多余逗号",
                _snippet(original, match.start(), match.end()),
            )
        )
    return findings


def _is_ascii_word_char(ch: str) -> bool:
    return bool(ch) and ch.isascii() and ch.isalnum()


def _lint_residual_marks(tts_input: str) -> list[Finding]:
    findings: list[Finding] = []
    for match in _RESIDUAL_MARK.finditer(tts_input):
        i = match.start()
        prev = tts_input[i - 1] if i > 0 else ""
        nxt = tts_input[i + 1] if i + 1 < len(tts_input) else ""
        # A kept English apostrophe ("don't", "it's") is not a leftover mark.
        if match.group() in ("'", "\u2019") and _is_ascii_word_char(prev) and _is_ascii_word_char(nxt):
            continue
        findings.append(
            Finding(
                "residual_mark",
                "TTS 输入仍残留引号/括号",
                _snippet(tts_input, match.start(), match.end()),
            )
        )
    return findings


def lint_segment(original: str, tts_input: str) -> list[Finding]:
    """Lint the FINAL TTS input (plus bracket rules on the original text)."""
    findings: list[Finding] = []
    findings += _lint_tts_punctuation(tts_input)
    findings += _lint_ascii_punct_cjk(tts_input)
    findings += _lint_long_unpunctuated(tts_input)
    findings += _lint_split_numbers(original, tts_input)
    findings += _lint_range_dash(original, tts_input)
    findings += _lint_plus_sign(original, tts_input)
    findings += _lint_markdown(original, tts_input)
    findings += _lint_comma_near_bracket(original)
    findings += _lint_residual_marks(tts_input)
    return findings


def _fullwidth(match: re.Match) -> str:
    text = match.string
    i = match.start()
    prev = text[i - 1] if i > 0 else ""
    nxt = text[i + 1] if i + 1 < len(text) else ""
    if prev.isdigit() and nxt.isdigit():
        return match.group()
    if _CJK_RE.fullmatch(prev) or _CJK_RE.fullmatch(nxt):
        return _ASCII_TO_FULLWIDTH[match.group()]
    return match.group()


def _collapse_run(match: re.Match) -> str:
    run = match.group(0)
    for ch in run:
        if ch in _TERMINAL_PUNCT:
            return ch
    return run[0]


def auto_fix_text(text: str) -> tuple[str, list[str]]:
    """Apply the safe mechanical fixes and return ``(fixed_text, notes)``."""
    fixed = text
    notes: list[str] = []

    collapsed = _DOUBLED_PUNCT.sub(_collapse_run, fixed)
    if collapsed != fixed:
        notes.append("折叠重复标点")
        fixed = collapsed

    without_terminal_comma = _COMMA_BEFORE_TERMINAL.sub("", fixed)
    if without_terminal_comma != fixed:
        notes.append("删除终止标点前的逗号")
        fixed = without_terminal_comma

    without_bracket_comma = _COMMA_AROUND_BRACKET.sub("", fixed)
    if without_bracket_comma != fixed:
        notes.append("删除书名号/引号旁的逗号")
        fixed = without_bracket_comma

    fullwidth = _ASCII_CLAUSE.sub(_fullwidth, fixed)
    if fullwidth != fixed:
        notes.append("半角标点转全角")
        fixed = fullwidth

    return fixed, notes


def number_tokens(text: str) -> list[str]:
    """Arabic + Chinese numeral tokens in ``text`` (shared number definition).

    Used both by the proofread multiset comparison (:func:`evaluate_fix`) and by
    the indicator manifest's :func:`required_numbers`, so every number check in
    the worker agrees on what a "number" is: Arabic numbers with sign, decimals,
    percent and thousand/time separators, plus Chinese numeral runs of length
    >= 2. Returned sorted.
    """
    text = text or ""
    tokens = [match.group() for match in _ARABIC_NUMBER.finditer(text)]
    tokens += [
        match.group()
        for match in _CN_NUMERAL.finditer(text)
        if len(match.group()) >= 2
    ]
    return sorted(tokens)


# Backward-compatible private alias (older call sites/tests).
_number_tokens = number_tokens


def _compact_diff(original: str, candidate: str) -> str:
    matcher = difflib.SequenceMatcher(a=original, b=candidate)
    parts: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        parts.append(f"{tag}:'{original[i1:i2]}'->'{candidate[j1:j2]}'")
    return "; ".join(parts)[:200]


def evaluate_fix(original: str, candidate: object) -> dict:
    """Accept/reject one proofread candidate, returning a result dict."""
    if not isinstance(candidate, str) or not candidate.strip():
        return {"accepted": False, "reason": "empty", "text": original}
    if candidate == original:
        return {"accepted": False, "reason": "no_change", "text": original}
    if _number_tokens(original) != _number_tokens(candidate):
        return {"accepted": False, "reason": "number_mismatch", "text": original}
    length = max(1, len(original))
    if abs(len(candidate) - len(original)) / length > 0.15:
        return {"accepted": False, "reason": "length_change", "text": original}
    return {
        "accepted": True,
        "reason": "",
        "text": candidate,
        "diff": _compact_diff(original, candidate),
    }


def _parse_json_array(raw: str) -> list | None:
    text = (raw or "").strip()
    if "```" in text:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            text = match.group(1).strip()
    try:
        value = json.loads(text)
    except Exception:  # noqa: BLE001 - try to recover the outermost array
        match = re.search(r"\[[\s\S]*\]", text)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
        except Exception:
            return None
    return value if isinstance(value, list) else None


_PROOFREAD_SYSTEM_PROMPT = (
    "你是一位中文口播脚本校对。输入是一个 JSON 字符串数组，每个元素是一段口播文案。"
    "请只修复不自然的断句、生硬措辞和错别字，保持原意、事实、人名完全不变，"
    "保持每一个数字（含小数、百分号、千分位、时间）完全一致，长度大致相当，保持温和口吻。"
    "只返回一个与输入等长的 JSON 字符串数组，不要任何解释或多余文字。"
)


async def proofread_texts(ai_client, texts: list[str]) -> list[dict]:
    """Proofread ``texts`` and validate each candidate (all originals on error)."""
    results: list[dict] = [
        {"accepted": False, "reason": "llm_error", "text": text} for text in texts
    ]
    if not texts:
        return results
    user_prompt = json.dumps(list(texts), ensure_ascii=False)
    try:
        raw = await ai_client.optimize_content(
            "",
            system_prompt=_PROOFREAD_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            # Scale the token budget with the whole script so a long episode
            # cannot be starved by the default 500-char target.
            target_length=sum(len(text) for text in texts),
        )
    except Exception as exc:  # noqa: BLE001 - keep all originals on any LLM error
        logger.warning(f"Script proofread failed, keeping originals: {exc}")
        return results
    candidates = _parse_json_array(raw)
    if candidates is None or len(candidates) != len(texts):
        for result in results:
            result["reason"] = "llm_output_mismatch"
        return results
    return [evaluate_fix(original, candidate) for original, candidate in zip(texts, candidates)]


_REVIEW_MD_KNOWN_KEYS = {
    "index",
    "original",
    "final",
    "tts_input",
    "char_count",
    "lint_before",
    "lint_after",
    "auto_fixes",
    "proofread",
}


@dataclass
class ScriptReview:
    """Reusable review result + writer (extensible per-segment ``extra``)."""

    segments: list[dict] = field(default_factory=list)
    extra: dict = field(default_factory=dict)
    proofread: bool = False

    def add_segment(self, entry: dict) -> None:
        self.segments.append(entry)

    def to_dict(self) -> dict:
        return {
            "proofread": self.proofread,
            "segment_count": len(self.segments),
            "segments": self.segments,
            **self.extra,
        }

    def to_markdown(self) -> str:
        lines = ["# 脚本校对 (Script Review)", ""]
        lines.append(f"- 段落数: {len(self.segments)}")
        lines.append(f"- Proofread: {'on' if self.proofread else 'off'}")
        for key, value in self.extra.items():
            lines.append(f"- {key}: {value}")
        lines.append("")
        for entry in self.segments:
            index = entry.get("index")
            lines.append(f"## 段落 {index + 1 if isinstance(index, int) else index}")
            lines.append(f"- 原始: {entry.get('original', '')}")
            lines.append(f"- 最终: {entry.get('final', '')}")
            lines.append(f"- TTS 输入: {entry.get('tts_input', '')}")
            lines.append(f"- 字数: {entry.get('char_count', 0)}")
            before = entry.get("lint_before") or []
            after = entry.get("lint_after") or []
            lines.append(f"- Lint (修复前): {', '.join(f['code'] for f in before) or '无'}")
            lines.append(f"- Lint (修复后): {', '.join(f['code'] for f in after) or '无'}")
            fixes = entry.get("auto_fixes") or []
            lines.append(f"- 自动修复: {', '.join(fixes) or '无'}")
            for key, value in entry.items():
                if key in _REVIEW_MD_KNOWN_KEYS:
                    continue
                lines.append(f"- {key}: {value}")
            proof = entry.get("proofread") or {}
            if proof.get("accepted"):
                lines.append(f"- Proofread: 采纳（{proof.get('diff', '')}）")
            else:
                lines.append(f"- Proofread: 拒绝（{proof.get('reason', '')}）")
            lines.append("")
        return "\n".join(lines)

    def write(self, task_dir: Path, task_logger=None) -> tuple[Path, Path]:
        task_dir = Path(task_dir)
        json_path = task_dir / "script_review.json"
        md_path = task_dir / "script_review.md"
        json_path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        md_path.write_text(self.to_markdown(), encoding="utf-8")
        if task_logger is not None:
            task_logger.set_file("script_review", json_path)
            task_logger.set_file("script_review_md", md_path)
        return json_path, md_path


async def review_script(
    ai_client,
    script,
    task_logger=None,
    *,
    proofread: bool = True,
    apply_fixes: bool = True,
    segment_extras: list[dict] | None = None,
    presenter_name: str | None = None,
) -> ScriptReview:
    """Lint + auto-fix + optional proofread, mutating ``script.segments[*].text``.

    ``apply_fixes=False`` still lints and reports ``auto_fixes`` but leaves the
    script text untouched — used to review a hand-edited approved script without
    silently rewriting it. ``segment_extras`` merges per-segment metadata (e.g.
    the indicator chart / section / key_point / number check) into each entry.

    When a ``presenter_name`` is given, the exact greeting on segment 0 is
    stripped before lint/proofread (so the length/number guard runs on the
    narration alone) and re-prepended to the result, and
    ``presenter_greeting`` (``kept``/``missing``) is recorded in ``extra``.
    """
    review = ScriptReview(proofread=proofread)
    originals = [segment.text for segment in script.segments]
    greeting = (
        f"大家好，我是{presenter_name}。" if presenter_name else None
    )
    bodies = list(originals)
    prefixes = [""] * len(originals)
    presenter_greeting = "disabled"
    if greeting and originals:
        if originals[0].startswith(greeting):
            prefixes[0] = greeting
            bodies[0] = originals[0][len(greeting):]
            presenter_greeting = "kept"
        else:
            presenter_greeting = "missing"

    lint_before: list[list[dict]] = []
    auto_fixes: list[list[str]] = []
    fixed_texts: list[str] = []
    for original, body in zip(originals, bodies):
        tts_before = to_speakable_text(original)
        lint_before.append([f.to_dict() for f in lint_segment(original, tts_before)])
        fixed, notes = auto_fix_text(body)
        # Notes are always reported; the applied text only when fixes are on.
        fixed_texts.append(fixed if apply_fixes else body)
        auto_fixes.append(notes)

    if proofread:
        proof_results = await proofread_texts(ai_client, fixed_texts)
    else:
        proof_results = [
            {"accepted": False, "reason": "disabled", "text": text} for text in fixed_texts
        ]

    changed = 0
    for index, (original, body, fixed) in enumerate(zip(originals, bodies, fixed_texts)):
        proof = proof_results[index]
        final_text = prefixes[index] + (proof.get("text") or fixed)
        if final_text != original:
            changed += 1
        tts_after = to_speakable_text(final_text)
        script.segments[index].text = final_text
        entry = {
            "index": index,
            "original": original,
            "final": final_text,
            "tts_input": tts_after,
            "lint_before": lint_before[index],
            "lint_after": [f.to_dict() for f in lint_segment(final_text, tts_after)],
            "auto_fixes": auto_fixes[index],
            "proofread": proof,
            "char_count": len(final_text),
        }
        if segment_extras and index < len(segment_extras) and segment_extras[index]:
            entry.update(segment_extras[index])
        review.add_segment(entry)

    if greeting:
        review.extra["presenter_greeting"] = presenter_greeting
        if presenter_greeting == "missing" and task_logger is not None:
            task_logger.warning(
                f"主持人开场白缺失（应为 {greeting}）/ presenter greeting missing"
            )

    if task_logger is not None:
        findings_before = sum(len(entry["lint_before"]) for entry in review.segments)
        findings_after = sum(len(entry["lint_after"]) for entry in review.segments)
        task_logger.info(
            f"脚本校对完成：{len(review.segments)} 段，修改 {changed} 段，"
            f"lint {findings_before}->{findings_after}"
        )
    return review
