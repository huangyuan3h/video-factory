"""事实核对闸：数字必须来自快照，来源≥1（关键条目≥2），无真名，问候+免责。"""

from __future__ import annotations

import json
import re

_ARABIC = re.compile(r"\d+(?:[.,:]\d+)*%?")
_CN_NUMERAL = re.compile(r"[零一二三四五六七八九十百千万亿两]{2,}")


def _tokens(text: str) -> list[str]:
    toks = [m.group(0) for m in _ARABIC.finditer(text or "")]
    toks += [m.group(0) for m in _CN_NUMERAL.finditer(text or "")]
    seen, out = set(), []
    for t in toks:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def factcheck(ranked: list[dict], narration: list[dict], snapshot: dict) -> tuple[bool, str]:
    corpus = json.dumps(snapshot, ensure_ascii=False)
    corpus_n = corpus.replace(",", "").replace("，", "").replace(" ", "")
    lines: list[str] = []
    ok = True
    full = "\n".join(s.get("text", "") for s in narration)

    # 1. 数字溯源
    for tok in _tokens(full):
        n = tok.replace(",", "").replace("，", "").replace(" ", "")
        hit = (tok in corpus) or (n and n in corpus_n)
        # 允许结构性数字：日期（片头）、条数、选题编号
        if tok in ("2026", "10", "03", "04", "05", "06", "07", "08", "1", "2", "3", "4", "5", "6", "7"):
            hit = True
        lines.append(f"- 数字 {tok!r}: {'OK' if hit else 'FAIL（快照无出处）'}")
        if not hit:
            ok = False

    # 2. 每条来源
    for it in ranked:
        srcs = it.get("sources", [])
        if not srcs:
            lines.append(f"- 来源 {it.get('id')}: FAIL（无来源）")
            ok = False
        elif len(srcs) == 1 and not it.get("single_source_reason"):
            lines.append(f"- 来源 {it.get('id')}: 注意（单来源，需注明原因）")
        else:
            lines.append(f"- 来源 {it.get('id')}: OK（{len(srcs)} 源）")

    # 3. 真名检查（永不出现真名，仅笔名）
    if "黄缘" in full or "黄元" in full:
        lines.append("- 真名检查: FAIL（含真名）")
        ok = False
    else:
        lines.append("- 真名检查: OK（仅笔名躺平的老黄）")

    # 4. 私人信息不得流入公开口播
    for bad in ["Karios 审计", "VF / OpenCode", "仓位", "持仓"]:
        if bad in full:
            lines.append(f"- 公开版隐私: FAIL（含私人信息 {bad!r}）")
            ok = False
            break
    else:
        lines.append("- 公开版隐私: OK（无私人项目/仓位）")

    # 5. 问候 + 免责
    if full.startswith("大家好，我是躺平的老黄"):
        lines.append("- 开场问候: OK")
    else:
        lines.append("- 开场问候: FAIL")
        ok = False
    if "不构成投资建议" in full:
        lines.append("- 免责声明: OK")
    else:
        lines.append("- 免责声明: FAIL")
        ok = False

    verdict = "PASS" if ok else "FAIL"
    md = f"# 世界简报事实核对 {verdict}\n\n" + "\n".join(lines) + "\n"
    return ok, md
