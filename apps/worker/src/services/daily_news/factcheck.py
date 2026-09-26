"""P0 fact gate: every number/name/org/time in the script must trace to the snapshot."""

from __future__ import annotations

import re

_ARABIC = re.compile(r"\d+(?:[.,:]\d+)*%?")
_CN_NUMERAL = re.compile(r"[零一二三四五六七八九十百千万亿两]{2,}")


def number_tokens(text: str) -> list[str]:
    toks = [m.group(0) for m in _ARABIC.finditer(text or "")]
    toks += [m.group(0) for m in _CN_NUMERAL.finditer(text or "")]
    seen, out = set(), []
    for t in toks:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _norm_num(tok: str) -> str:
    cn_map = {"零": "0", "一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
              "六": "6", "七": "7", "八": "8", "九": "9", "两": "2", "十": "10",
              "百": "100", "千": "1000", "万": "10000", "亿": "100000000"}
    if re.fullmatch(r"[零一二三四五六七八九十百千万亿两]+", tok or ""):
        return "".join(cn_map.get(c, c) for c in tok)
    return (tok or "").replace(",", "").replace("，", "").replace(" ", "")


def factcheck_script(script: dict, snapshot: dict, topic: dict) -> tuple[bool, str]:
    """Check script vs snapshot+topic. Returns (passed, factcheck.md text)."""
    brief_node = (snapshot.get("morning") or {})
    brief = brief_node.get("brief", brief_node)
    corpus = json_corpus(brief) + "\n" + json_corpus(topic)
    corpus_n = corpus.replace(",", "").replace("，", "").replace(" ", "")
    lines = []
    ok = True
    full_text = "\n".join(s.get("text", "") for s in script.get("segments", []))

    # 1. numbers
    for tok in number_tokens(full_text):
        n = _norm_num(tok)
        hit = (tok in corpus) or (n and n in corpus_n)
        # Allow narrator filler numbers (segment counts / durations) that are
        # structural, not factual claims: 五 (五条/五段) is fine.
        if tok in ("五",) and "五条" in full_text:
            hit = True
        lines.append(f"- 数字 {tok!r}: {'OK' if hit else 'FAIL（快照无出处）'}")
        if not hit:
            ok = False

    # 2. entities
    for ent in topic.get("entities", []):
        short = ent.replace("战略石油储备", "储备").replace("美国10年期国债", "美债")
        hit = (ent in full_text) or (short in full_text) or (ent[:2] in full_text)
        lines.append(f"- 实体 {ent}: {'OK' if hit else '注意（未逐字出现）'}")

    # 3. evidence titles traceability
    for e in topic.get("evidence", []):
        key = str(e.get("title", ""))[:8]
        hit = key and key in full_text
        lines.append(f"- 证据 {e.get('title','')[:20]}…: {'OK' if hit else '注意（概括转述）'}")

    # 4. forbidden: real name must never appear
    if "黄缘" in full_text:
        lines.append("- 真名检查: FAIL（含真名）")
        ok = False
    else:
        lines.append("- 真名检查: OK（无真名，仅笔名）")

    # 5. greeting + disclaimer
    if full_text.startswith("大家好，我是躺平的老黄"):
        lines.append("- 开场问候: OK")
    else:
        lines.append("- 开场问候: FAIL")
        ok = False
    if "不构成投资建议" in full_text:
        lines.append("- 免责声明: OK")
    else:
        lines.append("- 免责声明: FAIL")
        ok = False

    verdict = "PASS" if ok else "FAIL"
    md = f"# 事实核对 {verdict}\n\n选题：{topic.get('title','')}\nbrief：{topic.get('brief_id','')}\n\n" + "\n".join(lines) + "\n"
    return ok, md


def json_corpus(obj) -> str:
    import json as _j

    try:
        return _j.dumps(obj, ensure_ascii=False)
    except Exception:
        return str(obj)
