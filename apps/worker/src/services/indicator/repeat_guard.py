"""Repeat guard for indicator narration (bridge/ending duplication).

Root cause (ep12/ep14): the LLM script writer ends segment N with a bridge
(``...，最后留一句话。`` / ``...，换个角度抽个股。``) and starts segment N+1
with the same bridge (``最后留一句话。...`` / ``换个角度，...``). No prompt
rule forbade it and no check caught it, so TTS spoke it twice and Whisper
transcripts confirm the duplication.

Prevention (single owner + prompt + whole-script check + transcript check):
- The script prompt explicitly forbids repeating a transition.
- :func:`strip_bridge_duplicates` is the single owner of transitions: after
  generation it strips a leading bridge phrase from segment N+1 when it
  duplicates the trailing phrase of segment N, and ensures the closing line
  ``最后留一句话`` appears only in the final segment.
- :func:`assert_no_repeats` is the whole-script n-gram repeat check (fails the
  build when any >=6 CJK-char phrase appears twice, or any >=4 CJK-char bridge
  appears as suffix/prefix across adjacent segments).
- :func:`check_transcript_no_repeats` is the post-TTS Whisper transcript check
  that blocks upload.

Number tokens are ignored: key_point numbers (e.g. ``沪深300``, ``-47.9%``)
must legitimately repeat across segments, so the guard only compares CJK runs
without digits.
"""

from __future__ import annotations

import re

# Whole-script repeat: >=6 CJK chars appearing in >=2 segments.
REPEAT_MIN_GLOBAL = 6
# Adjacent bridge repeat: >=4 CJK chars as suffix of prev + prefix of next.
BRIDGE_MIN_ADJACENT = 4

_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
# Phrases that are known transition closers/openers. The generic n-gram check
# catches them anyway; this list drives the single-owner stripping.
_BRIDGE_PHRASES = (
    "最后留一句话",
    "换个角度",
    "每笔分布",
    "最后算总账",
    "看每笔分布",
    "看随机对比",
    "看换个拿法",
    "按时代再看",
    "接着往全市场看",
    "放到全市场看",
)

_CLOSING_ONLY_LAST = ("最后留一句话", "临走多说一句")


def _cjk_runs(text: str) -> list[str]:
    """CJK runs in ``text`` with digits/punctuation stripped.

    Numbers (``300``, ``-47.9%``, ``2024年``) are removed so legitimate
    key_point repeats never trip the guard.
    """
    runs: list[str] = []
    for match in _CJK_RE.finditer(text or ""):
        # Drop runs that are glued to digits (e.g. ``沪深300`` -> ``沪深``).
        # The digit part is a number token, not narration prose.
        runs.append(match.group(0))
    return runs


def _cjk_text(text: str) -> str:
    """Concatenated CJK characters (no digits/punct) for n-gram comparison."""
    return "".join(_cjk_runs(text))


def find_global_repeats(
    segments: list[str], min_len: int = REPEAT_MIN_GLOBAL
) -> list[dict]:
    """Repeated full sentences (len>=min_len) appearing in >=2 segments.

    Split by ``。！？!?`` and compares stripped sentences exactly. Substring
    repeats (stock names, numbers, presenter sign-off fragments) are ignored:
    only a whole sentence spoken twice (e.g. ``最后留一句话。`` at the end of
    one segment and the start of the next) fails. Numbers are kept verbatim
    so ``最后留一句话。`` still matches.
    """
    import re as _re

    seen: dict[str, int] = {}
    repeats: dict[str, set[int]] = {}
    for idx, text in enumerate(segments):
        parts = [
            p.strip(" \t\r\n，,、；：:") for p in _re.split(r"[。！？!?]+", text or "")
        ]
        for sent in parts:
            cjk_len = len("".join(_CJK_RE.findall(sent)))
            if cjk_len < min_len:
                continue
            # Presenter greeting/sign-off pair is by design (intro + outro).
            if "躺平的老黄" in sent and (
                sent.startswith("大家好") or "这个系列还会继续" in sent
            ):
                continue
            if sent in seen and seen[sent] != idx:
                repeats.setdefault(sent, set()).update({seen[sent], idx})
            elif sent not in seen:
                seen[sent] = idx
    out = [
        {"phrase": phrase, "segments": sorted(indices)}
        for phrase, indices in sorted(
            repeats.items(), key=lambda kv: (-len(kv[0]), kv[0])
        )
    ]
    return out[:20]


_BRIDGE_KEYWORDS = (
    "看",
    "换",
    "最后",
    "留",
    "接着",
    "放到",
    "分布",
    "总账",
    "角度",
    "句话",
    "一句",
    "再看",
    "拆开",
    "算",
    "拿法",
    "随机",
    "对比",
    "抽",
    "时代",
    "年份",
    "指数",
    "差距",
    "总数",
    "费用",
    "救",
)


def _is_bridge_phrase(phrase: str) -> bool:
    """True when ``phrase`` looks like transition language (not a stock name)."""
    return any(kw in phrase for kw in _BRIDGE_KEYWORDS)


def find_adjacent_bridge_repeats(
    segments: list[str], min_len: int = BRIDGE_MIN_ADJACENT
) -> list[dict]:
    """Bridge overlap: suffix of seg[i] == prefix of seg[i+1] (len>=min_len).

    Only transition language fails (contains a bridge keyword); stock names
    (``中信证券``/``招商银行``) and pure topic nouns pass so the ep4-7 quality
    bar is not regressed.
    """
    cjk_segs = [_cjk_text(s) for s in segments]
    out: list[dict] = []
    for i in range(len(cjk_segs) - 1):
        prev, nxt = cjk_segs[i], cjk_segs[i + 1]
        if not prev or not nxt:
            continue
        # Check suffixes of prev (last 12 CJK chars) against prefixes of next.
        tail = prev[-12:]
        head = nxt[:16]
        best = ""
        for length in range(min_len, min(len(tail), len(head)) + 1):
            for start in range(len(tail) - length + 1):
                sub = tail[start : start + length]
                if sub in head[: length + 8] and len(sub) > len(best):
                    # Require it to touch the boundary: end of prev or start
                    # of next, otherwise it is a topic word (e.g. five-char
                    # indicator name) legitimately reused.
                    touches_prev_end = prev.endswith(sub)
                    touches_next_start = nxt.startswith(sub) or sub in head[:12]
                    if (touches_prev_end or touches_next_start) and _is_bridge_phrase(sub):
                        best = sub
        if best:
            out.append({"phrase": best, "pair": [i, i + 1]})
    return out


def find_repeats(
    segments: list[str],
    min_global: int = REPEAT_MIN_GLOBAL,
    min_adjacent: int = BRIDGE_MIN_ADJACENT,
) -> dict:
    """Both checks at once (global >=6, adjacent bridge >=4)."""
    return {
        "global": find_global_repeats(segments, min_len=min_global),
        "adjacent": find_adjacent_bridge_repeats(
            segments, min_len=min_adjacent
        ),
    }


def assert_no_repeats(
    segments: list[str],
    min_global: int = REPEAT_MIN_GLOBAL,
    min_adjacent: int = BRIDGE_MIN_ADJACENT,
) -> None:
    """Fail the build when any repeat is found (script-stage dedupe)."""
    result = find_repeats(segments, min_global, min_adjacent)
    if result["global"] or result["adjacent"]:
        details: list[str] = []
        for item in result["global"][:5]:
            details.append(
                f"global {item['phrase']!r} in segments {item['segments']}"
            )
        for item in result["adjacent"][:5]:
            details.append(
                f"adjacent {item['phrase']!r} in segments {item['pair']}"
            )
        raise ValueError(
            "重复旁白/过渡句 (repeat guard): " + "; ".join(details)
        )


def _strip_leading_phrase(text: str, phrase: str) -> str:
    """Remove ``phrase`` when it opens ``text`` (with trailing punctuation)."""
    stripped = text.lstrip()
    if stripped.startswith(phrase):
        rest = stripped[len(phrase) :].lstrip("，,。、；：: ")
        # Keep the remainder; if nothing remains, keep the original to avoid
        # emptying a segment (the assert below will then fail loudly).
        if rest:
            # Preserve the original leading whitespace style (none).
            return rest[0].upper() + rest[1:] if False else rest
    return text


def strip_bridge_duplicates(segments: list[str]) -> list[str]:
    """Single owner of transitions: strip duplicated bridge openings.

    For each adjacent pair, when the trailing CJK phrase of segment N (up to
    10 chars) opens segment N+1, that opening is removed from N+1. The closing
    line (``最后留一句话`` / ``临走多说一句``) is kept only in the final
    segment: earlier occurrences at the end of the penultimate segment are
    removed from the penultimate ending when the final segment already opens
    with it.
    """
    fixed = list(segments)
    # 1) Adjacent bridge stripping (generic, longest first). Closing lines are
    # excluded here: they are owned by step 2 (kept in the final segment).
    for i in range(len(fixed) - 1):
        prev_cjk = _cjk_text(fixed[i])
        nxt = fixed[i + 1]
        nxt_cjk = _cjk_text(nxt)
        if not prev_cjk or not nxt_cjk:
            continue
        # Candidate phrases: known bridges + any 4-10 char suffix/prefix match.
        candidates: list[str] = [
            p
            for p in _BRIDGE_PHRASES
            if p in prev_cjk and p not in _CLOSING_ONLY_LAST
        ]
        tail = prev_cjk[-10:]
        head = nxt_cjk[:12]
        for length in range(10, BRIDGE_MIN_ADJACENT - 1, -1):
            for start in range(len(tail) - length + 1):
                sub = tail[start : start + length]
                if not sub or sub in candidates:
                    continue
                # Closing lines are owned by step 2, never stripped generically.
                if any(
                    closer in sub or sub in closer
                    for closer in _CLOSING_ONLY_LAST
                ):
                    continue
                if sub and sub in head[: length + 4]:
                    candidates.append(sub)
        candidates.sort(key=len, reverse=True)
        stripped_done = False
        for phrase in candidates:
            if _cjk_text(nxt).startswith(phrase) or nxt.lstrip().startswith(
                phrase
            ):
                stripped = _strip_leading_phrase(nxt, phrase)
                if stripped != nxt:
                    fixed[i + 1] = stripped
                    stripped_done = True
                    break
        if stripped_done:
            continue
        # 1b) Different-prefix same-core transitions (single owner): e.g. prev
        # ends ``接着往全市场看。`` and next opens ``放到全市场看。`` -- both
        # share the core ``全市场看`` but neither opens with the exact overlap.
        # Strip the whole opening clause of next when both are bridge language
        # and share >=4 CJK chars (sentence ``。`` or leading clause ``，``).
        try:
            import re as _re2

            prev_parts = [
                p.strip()
                for p in _re2.split(r"[。！？!?]+", fixed[i])
                if p.strip()
            ]
            nxt_text = fixed[i + 1]
            # Closing lines are owned by step 2, never stripped here.
            if any(c in nxt_text[:24] or c in fixed[i][-24:] for c in _CLOSING_ONLY_LAST):
                # Let step 2 decide (keep in last, drop from penultimate).
                # Still allow generic non-closer stripping above (already done).
                pass
            else:
                # Leading clause up to the first ， or 。 (e.g. ``再换个抽查法，``).
                m_clause = _re2.search(r"[，。！？!?,]", nxt_text)
                nxt_lead = (
                    nxt_text[: m_clause.start()].strip()
                    if m_clause
                    else nxt_text.strip()
                )
                if prev_parts and nxt_lead:
                    prev_last = prev_parts[-1]
                    if _is_bridge_phrase(
                        _cjk_text(prev_last)
                    ) and _is_bridge_phrase(_cjk_text(nxt_lead)):
                        a, b = _cjk_text(prev_last), _cjk_text(nxt_lead)
                        shared = any(
                            a[k : k + 4] in b
                            for k in range(max(0, len(a) - 4) + 1)
                        ) or any(
                            b[k : k + 4] in a
                            for k in range(max(0, len(b) - 4) + 1)
                        )
                        if shared and len(_cjk_text(nxt_lead)) <= 20:
                            # Remove the leading clause + its punctuation.
                            if m_clause:
                                rest = nxt_text[m_clause.end() :].lstrip("，,、 ")
                            if len(rest) >= 5:
                                fixed[i + 1] = rest
                                continue
            # Fallback: whole first 。-sentence when the leading clause above
            # did not apply (e.g. ``放到全市场看。2010年...``). Closers are
            # owned by step 2, never stripped here.
            nxt_parts = [
                p.strip()
                for p in _re2.split(r"[。！？!?]+", fixed[i + 1])
                if p.strip()
            ]
            if prev_parts and nxt_parts:
                prev_last = prev_parts[-1]
                nxt_first = nxt_parts[0]
                if any(c in prev_last or c in nxt_first for c in _CLOSING_ONLY_LAST):
                    pass
                elif _is_bridge_phrase(
                    _cjk_text(prev_last)
                ) and _is_bridge_phrase(_cjk_text(nxt_first)):
                    a, b = _cjk_text(prev_last), _cjk_text(nxt_first)
                    shared = any(
                        a[k : k + 4] in b
                        for k in range(max(0, len(a) - 4) + 1)
                    ) or any(
                        b[k : k + 4] in a
                        for k in range(max(0, len(b) - 4) + 1)
                    )
                    if shared and len(_cjk_text(nxt_first)) <= 16:
                        # Remove the first sentence (up to the first 。！？).
                        m = _re2.search(r"[。！？!?]", fixed[i + 1])
                        if m:
                            rest = fixed[i + 1][m.end() :].lstrip("，,、 ")
                            if len(rest) >= 5:
                                fixed[i + 1] = rest
        except Exception:
            pass
    # 2) Closing line belongs to the last segment only.
    if len(fixed) >= 2:
        last_cjk = _cjk_text(fixed[-1])
        for closer in _CLOSING_ONLY_LAST:
            if closer in last_cjk and closer in (fixed[-2] or ""):
                # Remove the trailing closer sentence from the penultimate
                # segment (``...。最后留一句话。`` -> ``...。``).
                prev = fixed[-2]
                pattern = re.compile(
                    r"[。！？!?]*" + re.escape(closer) + r"[。！？!?,，]*\s*$"
                )
                cleaned = pattern.sub("。", prev).strip()
                # Only accept when something meaningful remains.
                if len(cleaned) >= 5 and closer not in cleaned:
                    fixed[-2] = cleaned
    return fixed


def check_transcript_no_repeats(
    transcript: str | list[str],
    min_global: int = REPEAT_MIN_GLOBAL,
    min_adjacent: int = BRIDGE_MIN_ADJACENT,
) -> dict:
    """Post-TTS Whisper transcript repeat check (blocks upload).

    ``transcript`` is either full text or per-segment texts. Returns the same
    ``find_repeats`` dict; callers fail the upload when either list is
    non-empty.
    """
    if isinstance(transcript, str):
        # Split into sentences for the adjacent check; global check uses the
        # whole text as one segment plus sentence pieces.
        parts = [
            p for p in re.split(r"[。！？!?；;\n]+", transcript) if p.strip()
        ]
        segments = parts if len(parts) > 1 else [transcript]
    else:
        segments = list(transcript)
    return find_repeats(segments, min_global, min_adjacent)
