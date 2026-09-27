"""Whole-script transition pass + coherence reviewer (ep12/ep14/ep18 regression).

Root cause (see ``.opencode-runs/ep_transition_report.md``):
- ``generate_indicator_script`` asks the LLM for all segments in one call, but
  each segment is written as if standalone: every segment adds its own
  "承上启下" (tail forecast + head bridge). The model never sees the previous
  segment's final wording when writing the next head, so the same bridge
  appears twice (ep12 ``最后留一句话`` x2, ep14 ``换个角度`` x2) or as a
  generic pool (``总数看完，再看指数差距`` / ``差距看完，按年份拆开看`` …).
- No step read the full script in order to fix bridges, and no reviewer scored
  continuity. ``repeat_guard`` only catches exact duplicates, not incoherent
  or near-duplicate bridges (tail sums up X, head restates X in similar words).

Fix (this module, wired into ``script.generate_indicator_script``):
- :func:`polish_transitions` — whole-script LLM pass after segment writing and
  before TTS. The LLM reads the full script in order and rewrites **only** the
  first sentence of each segment (and the last sentence where needed) so each
  opening starts with a short, natural spoken connector (from
  :data:`CONNECTOR_POOL`, >=15 entries, never repeated within the episode),
  then picks up the previous section's concrete conclusion/number, then poses
  the question the next section answers. Tone is conversational and smooth,
  not formal. v2 CORRECTION (2026-09-27 owner): natural connectors like
  「接下来」 ARE allowed and wanted; banned is only (a) same connector twice
  in one episode, (b) tail/head restating the same content, (c) repeated whole
  phrases. Facts and numbers are verified unchanged via :func:`numbers_unchanged`.
- :func:`review_boundaries` — second LLM call scores each boundary 1-5 for
  continuity; :func:`run_transition_pass` rewrites and re-checks when any
  score is < 4 (max 2 loops) and logs the result for the episode QA file.
  Reviewer rubric (v2): 5 = natural connector (rotated, unique) + concrete
  handoff + question; single natural 「接下来」 scores high, only reuse scores low.
- Near-duplicate guard (Addendum 07:25): :func:`tail_head_jaccard` flags a
  boundary when the char-bigram Jaccard between the tail sentence and the head
  sentence exceeds :data:`NEARDUP_JACCARD_THRESHOLD` (tuned on ep3-7 good vs
  ep12/ep14 bad, see below). Flagged boundaries are rewritten. The check is
  also part of the reviewer rubric and ``scripts/indicator_qa.py``.
- Connector-reuse guard (v2): :func:`find_connector_reuse` flags the same
  pool connector opening twice (ban a). Single natural use passes.

Threshold tuning (char-bigram Jaccard, full chars incl. numbers):
- ep3-7 (good, mainline): max 0.133 (ep7 7->8 ``随便买``/``随便抽``), ep3 max
  0.05, ep4 max 0.091, ep5/ep6 max 0.089. All < 0.14.
- ep12/ep14 (bad): 0.154-0.158 (``这只是1笔，全市场306,560笔…`` vs
  ``2010年以来，一共成交306,560笔…`` — tail sums X, head restates X;
  ``差距看完，按年份拆开看`` vs ``按年拆开，心更凉``), ep18: 0.182
  (``费用说完，一起算总账`` vs ``三笔账，一起算``).
- Chosen :data:`NEARDUP_JACCARD_THRESHOLD` = 0.14: separates good (<0.14)
  from the worst number-restatement bridges (>=0.15). Remaining generic /
  semantic duplicates are caught by the bridge-reuse + stock-filler checks and
  the LLM reviewer (which also judges embedding-level similarity).
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

# Flag a boundary when char-bigram Jaccard(tail, head) exceeds this.
# Tuned: ep3-7 good all <0.14, ep12/ep14/ep18 worst >=0.15 (see module docstring).
NEARDUP_JACCARD_THRESHOLD = 0.14

# Stock filler bridges: avoid unless natural and unique in the episode.
STOCK_FILLERS = ("换个角度", "最后留一句话", "接下来")

# v2 (ep_transition_v2, 2026-09-27 owner feedback): natural spoken connectors
# like 「接下来」 are ALLOWED and WANTED (soft tone polish, not abrupt).
# What is banned is only (a) the same connector twice in one episode,
# (b) a tail and head that restate the same content, and (c) repeated whole
# phrases. Each segment opening (seg1..end, seg0 greeting exempt) starts with
# a short, natural spoken connector, then links to the previous conclusion,
# then leads into this section. Keep it conversational and smooth, not formal.
# Pool has >=15 entries; never repeat within an episode.
CONNECTOR_POOL = (
    "接下来",
    "然后我们一年一年拆开看",
    "那问题来了",
    "不过",
    "说到这",
    "好，",
    "你可能会问",
    "再往下看",
    "有意思的是",
    "反过来想",
    "先别急",
    "把镜头再拉远",
    "说完这个",
    "最关键的是",
    "还有一点",
    "换个问法",
    "看到这里",
    "顺着往下想",
)

# Reviewer bar: every boundary must score >= 4/5.
REVIEW_MIN_SCORE = 4
REVIEW_MAX_LOOPS = 2

_SENT_SPLIT = re.compile(r"[。！？!?]+")
_PUNCT_STRIP = re.compile(r"[。，、；：,.!?:;「」『』【】（）()《》“”‘’\s]")


def split_sentences(text: str) -> list[str]:
    """Split Chinese narration into sentences (stripped, no empties)."""
    return [p.strip() for p in _SENT_SPLIT.split(text or "") if p.strip()]


def first_sentence(text: str) -> str:
    """First sentence of a segment (or the whole text when unsplit)."""
    parts = split_sentences(text)
    return parts[0] if parts else (text or "").strip()


def last_sentence(text: str) -> str:
    """Last sentence of a segment (or the whole text when unsplit)."""
    parts = split_sentences(text)
    return parts[-1] if parts else (text or "").strip()


def char_bigrams(text: str) -> set[str]:
    """Char bigrams of ``text`` (whitespace/punctuation stripped, numbers kept).

    Numbers are kept on purpose: a tail that sums up ``306,560笔`` and a head
    that restates ``306,560笔`` is the canonical near-duplicate (ep12/ep14
    2->3) and must score high.
    """
    cleaned = _PUNCT_STRIP.sub("", text or "")
    if not cleaned:
        return set()
    if len(cleaned) < 2:
        return {cleaned}
    return {cleaned[i : i + 2] for i in range(len(cleaned) - 1)}


def jaccard(a: str, b: str) -> float:
    """Char-bigram Jaccard between two sentences (0.0-1.0)."""
    set_a, set_b = char_bigrams(a), char_bigrams(b)
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def tail_head_jaccard(prev_text: str, next_text: str) -> float:
    """Similarity between the tail sentence of ``prev`` and head of ``next``."""
    return jaccard(last_sentence(prev_text), first_sentence(next_text))


def find_near_duplicate_boundaries(
    segments: list[str], threshold: float = NEARDUP_JACCARD_THRESHOLD
) -> list[dict]:
    """Flag boundaries where tail and head say the same thing in similar words.

    Returns ``[{pair, tail, head, score}]`` for every ``score > threshold``.
    The tail should close the point; the head must move forward, not restate.
    """
    out: list[dict] = []
    for i in range(len(segments) - 1):
        tail = last_sentence(segments[i])
        head = first_sentence(segments[i + 1])
        score = jaccard(tail, head)
        if score > threshold:
            out.append({"pair": [i, i + 1], "tail": tail, "head": head, "score": round(score, 3)})
    return out


def find_stock_filler_reuse(segments: list[str]) -> list[dict]:
    """Flag stock filler bridges (``换个角度``/``最后留一句话``/``接下来``).

    A filler is only allowed when it appears exactly once in the whole episode
    and reads naturally; any reuse (or a filler opening a non-final segment
    for ``最后留一句话``) is flagged.
    """
    out: list[dict] = []
    for filler in STOCK_FILLERS:
        hits = [i for i, s in enumerate(segments) if filler in (s or "")]
        if len(hits) > 1:
            out.append({"phrase": filler, "segments": hits})
        elif len(hits) == 1 and filler == "最后留一句话" and hits[0] != len(segments) - 1:
            # Closing line belongs to the final segment only (repeat_guard owns
            # the stripping; this flags the intent for the reviewer/runbook).
            out.append({"phrase": filler, "segments": hits, "note": "not-final"})
    return out


def find_connector_reuse(segments: list[str]) -> list[dict]:
    """Flag reuse of the same spoken connector twice in one episode (v2 ban a).

    v2 rule (CORRECTS the earlier rule): natural connectors like 「接下来」
    ARE allowed and wanted — what is banned is only (a) the same connector
    twice in one episode, (b) a tail and head that restate the same content,
    and (c) repeated whole phrases. Each opening should start with a short,
    natural spoken connector from :data:`CONNECTOR_POOL` (pool >=15, never
    repeat within the episode), then link to the previous conclusion, then
    lead into this section. Keep it conversational and smooth, not formal.

    Detection: a connector counts when it opens the segment's first sentence
    (leading position). ``好，`` also counts when it appears as the opening
    turn word. seg0 (greeting 「大家好，我是…」) is exempt.
    """

    def _opening_connector(text: str) -> str | None:
        head = first_sentence(text or "").strip()
        # Longest-first so e.g. 「然后我们一年一年拆开看」 wins over 「然后」.
        for conn in sorted(CONNECTOR_POOL, key=len, reverse=True):
            if head.startswith(conn):
                return conn
        return None

    seen: dict[str, int] = {}
    out: list[dict] = []
    for i, seg in enumerate(segments):
        if i == 0:
            continue  # intro greeting exempt
        conn = _opening_connector(seg)
        if conn is None:
            continue
        if conn in seen:
            out.append({"phrase": conn, "segments": [seen[conn], i]})
        else:
            seen[conn] = i
    return out


def find_bridge_phrase_reuse(segments: list[str]) -> list[dict]:
    """Flag any non-trivial bridge sentence reused across the episode.

    Compares first sentences (the bridge position): two heads sharing >=6
    identical chars (after punctuation strip) count as reuse. Numbers are
    ignored for this comparison so legitimate key_point repeats never trip it.
    """
    import re as _re

    _cjk = _re.compile(r"[\u4e00-\u9fff]+")

    def _norm(sent: str) -> str:
        return "".join(_cjk.findall(sent or ""))

    heads = [_norm(first_sentence(s)) for s in segments]
    out: list[dict] = []
    seen: dict[str, int] = {}
    for i, head in enumerate(heads):
        for prev_head, prev_i in list(seen.items()):
            # Longest common substring >= 6 chars counts as reuse.
            longest = 0
            for a in range(len(prev_head)):
                for b in range(len(head)):
                    k = 0
                    while (
                        a + k < len(prev_head)
                        and b + k < len(head)
                        and prev_head[a + k] == head[b + k]
                    ):
                        k += 1
                    longest = max(longest, k)
            if longest >= 6:
                out.append({"phrase": head[:12], "pair": [prev_i, i], "overlap": longest})
        seen.setdefault(head, i)
    return out


def numbers_unchanged(before: str, after: str) -> bool:
    """True when the number-token multiset is identical (facts preserved)."""
    from .manifest import required_numbers  # local import: avoid cycle
    from ..script_review import number_tokens

    return sorted(number_tokens(before or "")) == sorted(number_tokens(after or ""))


def transition_issues(
    segments: list[str], threshold: float = NEARDUP_JACCARD_THRESHOLD
) -> dict:
    """All deterministic transition checks at once (for QA gate + tests)."""
    return {
        "near_duplicates": find_near_duplicate_boundaries(segments, threshold),
        "stock_filler": find_stock_filler_reuse(segments),
        "bridge_reuse": find_bridge_phrase_reuse(segments),
        "connector_reuse": find_connector_reuse(segments),
    }


def assert_transitions_coherent(
    segments: list[str], threshold: float = NEARDUP_JACCARD_THRESHOLD
) -> None:
    """Fail the build when any deterministic transition check fires."""
    issues = transition_issues(segments, threshold)
    details: list[str] = []
    for item in issues["near_duplicates"][:5]:
        details.append(
            f"near-dup boundary {item['pair']} J={item['score']} "
            f"tail={item['tail'][:18]!r} head={item['head'][:18]!r}"
        )
    for item in issues["stock_filler"][:5]:
        details.append(f"stock filler {item['phrase']!r} in {item['segments']}")
    for item in issues["bridge_reuse"][:5]:
        details.append(f"bridge reuse {item['phrase']!r} pair={item['pair']}")
    for item in issues.get("connector_reuse", [])[:5]:
        details.append(
            f"connector reuse {item['phrase']!r} in {item['segments']}"
        )
    if details:
        raise ValueError("过渡不连贯 (transition guard): " + "; ".join(details))


# --------------------------------------------------------------------------- #
# LLM passes (whole-script polish + coherence reviewer)
# --------------------------------------------------------------------------- #


def _build_transition_system_prompt(count: int) -> str:
    pool = "、".join(f"「{c}」" for c in CONNECTOR_POOL)
    return (
        "你是中文财经视频口播的过渡编辑，语气要像朋友聊天一样口语、顺滑、不正式。"
        "输入是按顺序的全部段落（每段讲一张图）。"
        "只改每段的首句（必要时也可改上段的尾句），让每处衔接满足："
        "每段开头（第0段问候除外）先用一个短的、自然的口语连接词/语气转折词开场"
        f"（从连接词池里选，全片轮换、绝不重复：{pool}；"
        "例如「然后我们一年一年拆开看」「接下来」「那问题来了」「不过」"
        "「说到这」「好，」「你可能会问」），"
        "然后接住上一段的具体结论或数字（点名复述关键数字），"
        "再提出下一段要回答的问题；"
        "全片不重复使用同一个连接词或桥接短语；"
        "自然的连接词如「接下来」是允许且想要的，禁的只有："
        "(a) 同一个连接词在一集里用两次，(b) 上段尾和下段首复述同一内容，"
        "(c) 整句/整短语重复。"
        "尾句收束观点，首句向前推进，不许尾句总结X、首句又复述X。"
        "绝不改动任何数字（含小数、百分号、千分位）、事实、人名、股票代码。"
        f"共 {count} 段。只返回 JSON："
        '{"segments":[{"index":0,"text":"改后整段"}]}，index 与输入一一对应，'
        "未改的段也要原样返回。"
    )


def _build_transition_user_prompt(segments: list[str]) -> str:
    rows = [
        json.dumps({"index": i, "text": text}, ensure_ascii=False)
        for i, text in enumerate(segments)
    ]
    return "段落（按播出顺序）：\n" + "\n".join(rows)


def _build_reviewer_system_prompt() -> str:
    pool = "、".join(f"「{c}」" for c in CONNECTOR_POOL)
    return (
        "你是中文口播连贯性评审，标准是口语、顺滑、像人说话、不正式。"
        "输入是按顺序的全部段落。"
        "给每处边界（段i尾句 -> 段i+1首句）打1-5分："
        "5=开头有自然口语连接词（全片轮换不重复）+承接具体结论/数字并自然引出下段问题；"
        "4=连贯但偏泛，或连接词稍弱但仍顺滑；"
        "3=硬切、偏正式、或缺连接词/转折语气；"
        "2=重复同一连接词/过渡；1=尾首复述同一句话。"
        "同时判断：(a) 同一连接词是否在一集里用了两次"
        f"（连接词池：{pool}）；"
        "(b) 尾首是否近义重复（字面或语义复述同一结论）；"
        "(c) 是否有整句/整短语重复。"
        "自然连接词如「接下来」是允许且想要的，单次自然出现应给高分，"
        "只有重复才扣分。"
        "只返回 JSON：{\"scores\":[{\"pair\":[0,1],\"score\":5,"
        "\"comment\":\"…\"}]}，边界按顺序，一个不少。"
    )


async def _call_json(ai_client, system_prompt: str, user_prompt: str, max_tokens: int) -> dict:
    try:
        result = await ai_client.complete_json(
            system_prompt, user_prompt, max_tokens=max_tokens
        )
    except Exception as exc:  # noqa: BLE001 - never break generation on LLM error
        logger.warning(f"Transition LLM call failed, keeping originals: {exc}")
        return {}
    return result if isinstance(result, dict) else {}


def _map_texts(payload, count: int) -> dict[int, str]:
    mapped: dict[int, str] = {}
    for position, item in enumerate(payload or []):
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index", position))
        except (TypeError, ValueError):
            index = position
        text = str(item.get("text") or "").strip()
        if 0 <= index < count and index not in mapped and text:
            mapped[index] = text
    return mapped


async def polish_transitions(
    ai_client, segments: list[str], task_logger=None
) -> tuple[list[str], dict]:
    """One LLM polish pass: rewrite only boundary sentences, keep numbers.

    Returns ``(polished_segments, info)`` where ``info`` records which indices
    were rewritten and any number-mismatch rejections. Segments whose rewrite
    would change numbers are kept as-is.
    """
    count = len(segments)
    info: dict = {"rewrote": [], "rejected_number_change": []}
    if count < 2 or ai_client is None:
        return list(segments), info
    system_prompt = _build_transition_system_prompt(count)
    user_prompt = _build_transition_user_prompt(segments)
    expected = sum(len(s) for s in segments)
    result = await _call_json(
        ai_client, system_prompt, user_prompt, max(4000, expected * 2)
    )
    mapped = _map_texts(result.get("segments"), count)
    if not mapped:
        return list(segments), info
    polished = list(segments)
    for index, new_text in mapped.items():
        if new_text == polished[index]:
            continue
        if not numbers_unchanged(polished[index], new_text):
            info["rejected_number_change"].append(index)
            continue
        # Guardrail: only boundary sentences may change. Compare the middle
        # body (all sentences except first/last): it must be identical.
        old_parts, new_parts = split_sentences(polished[index]), split_sentences(new_text)
        if len(old_parts) > 2 and len(new_parts) > 2 and old_parts[1:-1] != new_parts[1:-1]:
            info["rejected_number_change"].append(index)
            continue
        polished[index] = new_text
        info["rewrote"].append(index)
    if task_logger is not None and info["rewrote"]:
        task_logger.info(f"过渡润色改写 {len(info['rewrote'])} 段：{info['rewrote']}")
    return polished, info


async def review_boundaries(ai_client, segments: list[str]) -> list[dict]:
    """Score each boundary 1-5 (LLM reviewer; heuristic fallback offline).

    Returns ``[{pair, score, comment}]`` for every adjacent pair. When the LLM
    is unavailable or returns unusable output, falls back to a deterministic
    heuristic (near-dup -> 2, filler/reuse -> 3, else 5) so the gate still runs.
    """
    pairs = [[i, i + 1] for i in range(len(segments) - 1)]
    if not pairs:
        return []
    if ai_client is not None:
        system_prompt = _build_reviewer_system_prompt()
        user_prompt = _build_transition_user_prompt(segments)
        result = await _call_json(ai_client, system_prompt, user_prompt, 4000)
        scores = result.get("scores") if isinstance(result, dict) else None
        parsed: list[dict] = []
        if isinstance(scores, list) and len(scores) == len(pairs):
            ok = True
            for entry, pair in zip(scores, pairs):
                try:
                    score = int(entry.get("score"))
                except (TypeError, ValueError, AttributeError):
                    ok = False
                    break
                if not 1 <= score <= 5:
                    ok = False
                    break
                parsed.append(
                    {
                        "pair": pair,
                        "score": score,
                        "comment": str(entry.get("comment") or "")[:120],
                    }
                )
            if ok:
                return parsed
    # Deterministic fallback (also used in unit tests without an LLM).
    # v2: natural connectors like 「接下来」 single use => 5 (wanted);
    # only reuse / near-dup / bridge reuse lower the score.
    near = {tuple(d["pair"]): d for d in find_near_duplicate_boundaries(segments)}
    filler_pairs: set[tuple[int, int]] = set()
    for item in find_stock_filler_reuse(segments):
        idxs = item.get("segments", [])
        for k in range(len(idxs) - 1):
            filler_pairs.add((idxs[k], idxs[k + 1]))
    reuse_pairs = {tuple(d["pair"]) for d in find_bridge_phrase_reuse(segments)}
    connector_pairs: set[tuple[int, int]] = set()
    for item in find_connector_reuse(segments):
        idxs = item.get("segments", [])
        for k in range(len(idxs) - 1):
            connector_pairs.add((idxs[k], idxs[k + 1]))
    out: list[dict] = []
    for pair in pairs:
        key = tuple(pair)
        if key in near:
            out.append(
                {
                    "pair": pair,
                    "score": 2,
                    "comment": f"尾首近义重复 J={near[key]['score']} (heuristic)",
                }
            )
        elif key in filler_pairs or key in reuse_pairs or key in connector_pairs:
            out.append({"pair": pair, "score": 3, "comment": "连接词/桥接复用 (heuristic)"})
        else:
            out.append({"pair": pair, "score": 5, "comment": "承接自然，有口语连接 (heuristic)"})
    return out


async def run_transition_pass(
    ai_client, segments: list[str], task_logger=None, max_loops: int = REVIEW_MAX_LOOPS
) -> tuple[list[str], dict]:
    """Full pass: polish -> review -> rewrite while any score < 4 (max loops).

    Returns ``(final_segments, report)`` where ``report`` holds per-loop
    ``scores``, ``rewrote`` indices and the final ``min_score``. The report is
    meant to be logged into the episode QA file (``script_review.json`` extra
    + ``task.log``). Numbers are verified unchanged after every loop.
    """
    current = list(segments)
    report: dict = {"loops": [], "min_score": 5, "final_scores": []}
    for loop in range(max_loops + 1):
        polished, info = await polish_transitions(ai_client, current, task_logger)
        current = polished
        scores = await review_boundaries(ai_client, current)
        min_score = min((s["score"] for s in scores), default=5)
        report["loops"].append(
            {"loop": loop, "rewrote": info.get("rewrote", []), "scores": scores}
        )
        report["min_score"] = min_score
        report["final_scores"] = scores
        if task_logger is not None:
            task_logger.info(
                f"过渡评审 loop{loop}：min={min_score} "
                + ",".join(f"{s['pair'][0]}->{s['pair'][1]}:{s['score']}" for s in scores[:6])
            )
        if min_score >= REVIEW_MIN_SCORE or loop >= max_loops:
            break
        # Next loop re-polishes the flagged boundaries (the LLM sees the
        # reviewer scores implicitly via the deteriorated wording; the
        # deterministic near-dup/filler guards also keep failing loudly).
    # Final safety: never return a version that changed numbers.
    for i, (old, new) in enumerate(zip(segments, current)):
        if not numbers_unchanged(old, new):
            current[i] = old
    return current, report
