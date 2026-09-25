"""Indicator script generation from a chart manifest.

One narration segment per manifest item, in manifest order, each bound to its
chart (``images=[file]``, ``fit="contain"``, ``motion="none"``). The title card
is also narrated as the intro and is reused as the video's cover by the pipeline.

After the model returns, every number token in an item's ``key_point`` must
appear in that segment's text (compared on normalised forms, ignoring thousand
separators and spaces). If not, the function makes ONE focused retry for only
the offending segments; anything still missing gets the ``key_point`` appended
verbatim as a final sentence. A per-segment report is attached to the returned
script as ``number_report`` (also surfaced in ``script_review``).
"""

from __future__ import annotations

import json
import logging

from ...core.ai_client import GeneratedScript, ScriptSegment
from .manifest import IndicatorManifest, ManifestItem, required_numbers

logger = logging.getLogger(__name__)

_CPS = 4.2  # required Chinese characters per spoken second
_DEFAULT_TOTAL_SECONDS = 300
_TERMINAL_PUNCT = "。！？!?."


def _target_seconds(manifest: IndicatorManifest, request) -> list[int]:
    """Per-item spoken seconds: ``suggested_seconds`` or an even split fallback."""
    total = getattr(request, "target_seconds", None) or _DEFAULT_TOTAL_SECONDS
    seconds = [item.suggested_seconds for item in manifest.items]
    missing = [i for i, value in enumerate(seconds) if not value]
    if missing:
        known = sum(value for value in seconds if value)
        remaining = max(int(total) - known, len(missing) * 10)
        per = remaining / len(missing)
        for index in missing:
            seconds[index] = int(round(per))
    return [int(value) for value in seconds]


def _build_system_prompt(count: int) -> str:
    return (
        "你是一位中文财经视频脚本作者，用温和、像和朋友聊天的口吻讲解一个技术指标，"
        "听众是一个会一点交易的朋友。\n"
        "要求：\n"
        "1. 全片结构依次是：介绍指标 → 怎么理解 → 散户怎么用 → 历史表现 → "
        "为什么不赚钱 → 总结（对应清单里的 section）。\n"
        "2. 严格按清单顺序，一段只讲一张图；每段都要能独立听懂。\n"
        "3. 口语、短句，不吹嘘、不保证收益、不给任何投资建议。\n"
        "4. 只使用每张图的 key_point 里给出的事实和数字，绝不编造数据。\n"
        "5. 每个数字都必须原样出现在对应段落里（含小数、百分号、千分位），"
        "写法与 key_point 完全一致。\n"
        "6. 结尾用一句话温和提示风险。\n"
        "7. 不要 markdown、不要小标题、不要“本期/欢迎收看”之类套话。\n\n"
        "输出 JSON（不要任何解释）：\n"
        "{\n"
        '  "title": "短标题",\n'
        '  "segments": [{"index": 0, "text": "本段口播"}]\n'
        "}\n"
        f"必须正好 {count} 段，index 从 0 到 {count - 1}，与清单顺序一致。"
    )


def _build_user_prompt(
    manifest: IndicatorManifest, request, seconds: list[int]
) -> str:
    context = (getattr(request, "content", None) or "").strip()
    lines = [f"指标名称：{getattr(request, 'title', None) or manifest.title}"]
    if context:
        lines.append(f"补充背景（只可作为事实参考，不要编造）：\n{context[:6000]}")
    lines.append(f"图表清单（共 {len(manifest.items)} 项，请为每一项写一段口播）：")
    for item, secs in zip(manifest.items, seconds):
        chars = max(20, int(round(secs * _CPS)))
        lines.append(
            f"{item.index}. section={item.section or 'unknown'} | "
            f"chart={item.file.name} | title={item.title or '-'} | "
            f"key_point={item.key_point or '-'} | 目标 {secs}s（约 {chars} 字）"
        )
    lines.append(
        f"每段约 {_CPS:g} 字/秒，只用 key_point 里的事实和数字。只输出 JSON。"
    )
    return "\n".join(lines)


async def _call_ai(ai_client, system_prompt: str, user_prompt: str, max_tokens: int) -> dict:
    """Call the shared JSON path (fence stripping + token-budget retry)."""
    result = await ai_client.complete_json(system_prompt, user_prompt, max_tokens=max_tokens)
    return result if isinstance(result, dict) else {}


def _map_segments(payload, count: int) -> dict[int, str]:
    """Map ``[{"index", "text"}]`` onto 0..count-1 (positional fallback)."""
    mapped: dict[int, str] = {}
    for position, item in enumerate(payload or []):
        if not isinstance(item, dict):
            continue
        raw_index = item.get("index", position)
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            index = position
        text = str(item.get("text") or "").strip()
        if 0 <= index < count and index not in mapped:
            mapped[index] = text
    return mapped


def _normalise_number(token: str) -> str:
    return str(token).replace(",", "").replace("，", "").replace(" ", "").strip()


def missing_numbers(required: list[str], text: str) -> list[str]:
    """Required tokens absent from ``text`` (normalised comparison)."""
    have = {_normalise_number(token) for token in _numbers_in(text)}
    return [token for token in required if _normalise_number(token) not in have]


def found_numbers(required: list[str], text: str) -> list[str]:
    """Required tokens present in ``text`` (normalised comparison)."""
    have = {_normalise_number(token) for token in _numbers_in(text)}
    return [token for token in required if _normalise_number(token) in have]


# Backward-compatible private alias.
_missing_numbers = missing_numbers


def _numbers_in(text: str) -> list[str]:
    from ..script_review import number_tokens

    return number_tokens(text)


def _append_key_point(text: str, key_point: str) -> str:
    key_point = (key_point or "").strip()
    if not key_point:
        return text
    text = (text or "").strip()
    if text and text[-1] not in _TERMINAL_PUNCT:
        text += "。"
    if key_point[-1] not in _TERMINAL_PUNCT:
        key_point += "。"
    return text + key_point


async def _retry_numbers(
    ai_client,
    manifest: IndicatorManifest,
    segments: list[ScriptSegment],
    missing_by_index: dict[int, list[str]],
) -> dict[int, str]:
    system_prompt = (
        "你是中文口播文稿修订者。下面的段落遗漏了必须出现的数字。"
        "请只修订这些段落，让 must_include 里的每个数字都原样出现"
        "（写法与 key_point 完全一致），不改变含义，不新增其它数字。"
        "只返回 JSON：{\"segments\":[{\"index\":0,\"text\":\"修订后的段落\"}]}，"
        "index 与输入一一对应。"
    )
    rows = []
    for index, missing in missing_by_index.items():
        item = manifest.items[index]
        rows.append(
            json.dumps(
                {
                    "index": index,
                    "key_point": item.key_point,
                    "must_include": missing,
                    "text": segments[index].text,
                },
                ensure_ascii=False,
            )
        )
    result = await _call_ai(ai_client, system_prompt, "\n".join(rows), 4000)
    return _map_segments(result.get("segments"), len(manifest.items))


def _make_segment(item: ManifestItem, text: str, seconds: int) -> ScriptSegment:
    return ScriptSegment(
        text=text,
        keywords=[],
        duration_estimate=seconds,
        images=[str(item.file)],
        fit="contain",
        motion="none",
        hold_seconds=None,
        section=item.section or None,
        chart=item.file.name,
        key_point=item.key_point or None,
    )


async def generate_indicator_script(
    ai_client, manifest: IndicatorManifest, request, task_logger
) -> GeneratedScript:
    """Generate one chart-bound segment per manifest item, with number checks."""
    if not manifest.items:
        raise ValueError(
            "图表清单为空，无法生成脚本 / empty manifest, cannot generate script"
        )

    count = len(manifest.items)
    seconds = _target_seconds(manifest, request)
    system_prompt = _build_system_prompt(count)
    user_prompt = _build_user_prompt(manifest, request, seconds)
    expected_chars = int(sum(seconds) * _CPS)
    result = await _call_ai(
        ai_client, system_prompt, user_prompt, max(4000, expected_chars * 2)
    )
    mapped = _map_segments(result.get("segments"), count)

    segments: list[ScriptSegment] = []
    for index, item in enumerate(manifest.items):
        text = mapped.get(index) or item.key_point or item.title or ""
        segments.append(_make_segment(item, text.strip(), seconds[index]))

    required_by_index = [required_numbers(item.key_point) for item in manifest.items]
    retry_targets = {
        index: missing
        for index, required in enumerate(required_by_index)
        if (missing := _missing_numbers(required, segments[index].text))
    }
    retried_missing: dict[int, list[str]] = {}
    if retry_targets:
        if task_logger is not None:
            task_logger.info(
                f"数字校验未通过 {len(retry_targets)} 段，追加一次针对性重写"
            )
        retry_map = await _retry_numbers(ai_client, manifest, segments, retry_targets)
        for index in retry_targets:
            new_text = retry_map.get(index)
            if new_text:
                segments[index].text = new_text
            retried_missing[index] = _missing_numbers(
                required_by_index[index], segments[index].text
            )

    report: dict[int, dict] = {}
    appended_count = 0
    for index, item in enumerate(manifest.items):
        still_missing = retried_missing.get(index, [])
        appended = False
        if still_missing:
            segments[index].text = _append_key_point(
                segments[index].text, item.key_point
            )
            appended = True
            appended_count += 1
        required = required_by_index[index]
        have = {
            _normalise_number(value)
            for value in _numbers_in(segments[index].text)
        }
        report[index] = {
            "required": required,
            "found": [token for token in required if _normalise_number(token) in have],
            "missing_after_retry": list(still_missing),
            "appended": appended,
        }

    title = (
        (getattr(request, "title", None) or "").strip()
        or manifest.title
        or str(result.get("title") or "").strip()
        or "指标"
    )
    script = GeneratedScript(
        title=title,
        segments=segments,
        total_duration_estimate=int(sum(seconds)),
    )
    object.__setattr__(script, "number_report", report)

    if task_logger is not None:
        task_logger.info(
            f"指标脚本生成 {count} 段，图表全部绑定；数字缺失追加 {appended_count} 段"
        )
    return script
