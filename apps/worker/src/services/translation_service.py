"""English localization for the book -> video pipeline (YouTube growth).

The Chinese script remains the master (Bilibili, etc.). For ``language=en`` the
worker runs this thin layer after the dense Chinese script exists:

* :func:`translate_script` — translates each segment's narration and keywords
  into natural spoken English, keeping the segment count/order stable so the
  visual timeline is unchanged.
* :func:`generate_youtube_metadata` — builds a curiosity + topic-keyword title,
  a discovery-friendly description and tags for the YouTube upload.

Both functions degrade gracefully: any model/parse failure returns the source
script (translation) or a derived fallback (metadata) instead of breaking the
pipeline.
"""

from __future__ import annotations

import json
import logging

from ..core.ai_client import GeneratedScript, ScriptSegment

logger = logging.getLogger(__name__)


BOOK_TRANSLATE_SCRIPT_PROMPT = (
    "You are a professional English short-video scriptwriter localizing a Chinese "
    "book-explainer episode for a global audience.\n"
    "Task: translate and adapt the narration into natural, spoken English that a "
    "native narrator would say out loud — never a literal word-for-word translation.\n"
    "Rules:\n"
    "1. Keep the SAME number of segments, in the SAME order: one output segment per input segment\n"
    "2. Preserve facts, mechanisms, key turning points and numbers exactly\n"
    "3. Conversational English, short sentences, first sentence is a hook; no markdown, no headings\n"
    "4. Translate each segment's keywords into 2-3 short, concrete English visual-search phrases (lowercase)\n"
    "5. Do not add, merge or drop segments; keep the total spoken length close to the source\n\n"
    "Output JSON:\n"
    "{\n"
    '  "title": "English episode title",\n'
    '  "segments": [\n'
    '    {"text": "spoken English narration", "keywords": ["concrete english terms"], '
    '"duration_estimate": 25}\n'
    "  ],\n"
    '  "total_duration_estimate": 210\n'
    "}"
)

YOUTUBE_METADATA_PROMPT = (
    "You write YouTube packaging for a global, English-first audience with the goal "
    "of maximizing click-through rate, watch time and search discovery.\n"
    "Given a book episode (often modern Japanese / East-Asian economic history), produce:\n"
    "1. title: an English hook title of at most 90 characters that combines curiosity "
    "with searchable topic keywords (for example 'Japan's lost decades', 'Heisei bubble', "
    "'yen appreciation', 'deflation'). Honest, no clickbait lies, no emojis, no surrounding quotes.\n"
    "2. description: 2-4 sentences; the first sentence repeats the main search keywords, "
    "then a short summary, and 3-6 relevant hashtags on the final line.\n"
    "3. tags: 10-15 lowercase search tags mixing broad and specific terms.\n\n"
    'Output JSON: {"title": "...", "description": "...", "tags": ["..."]}'
)


def _coerce_segments(payload: list) -> list[dict]:
    return [item for item in (payload or []) if isinstance(item, dict)]


def _derive_tags(script: GeneratedScript | None, title: str = "") -> list[str]:
    """Fallback tags from the script's own keywords plus a couple of broad ones."""
    tags: list[str] = []
    if script is not None:
        for segment in script.segments:
            for keyword in segment.keywords:
                value = str(keyword).strip().lstrip("#").lower()
                if value and value not in tags:
                    tags.append(value)
    if not tags and title:
        tags.append(title.strip().lower()[:60])
    for broad in ("book summary", "explainer"):
        if broad not in tags:
            tags.append(broad)
    return tags[:15]


def _fallback_description(script: GeneratedScript | None, title: str) -> str:
    if script is not None and script.segments:
        first = (script.segments[0].text or "").strip()
        if first:
            return first[:400]
    return title


async def translate_script(
    ai_client,
    script: GeneratedScript,
    *,
    target_lang: str = "en",
    source_lang: str = "zh",
    task_logger=None,
) -> GeneratedScript:
    """Translate a script's narration + keywords, preserving its structure.

    Returns the original script (unchanged) when the model returns nothing usable,
    so a failed translation can never empty the pipeline.
    """
    source_segments = [
        {
            "text": seg.text,
            "keywords": list(seg.keywords),
            "duration_estimate": seg.duration_estimate,
        }
        for seg in script.segments
    ]
    user_prompt = (
        f"Source language: {source_lang}\n"
        f"Target language: {target_lang}\n"
        f"Source title: {script.title}\n\n"
        "Source segments (JSON):\n"
        f"{json.dumps(source_segments, ensure_ascii=False)}"
    )

    result = await ai_client.complete_json(BOOK_TRANSLATE_SCRIPT_PROMPT, user_prompt)
    translated = _coerce_segments(result.get("segments"))

    if not translated:
        if task_logger is not None:
            task_logger.warning("翻译未返回段落，保留原中文脚本（结构不变）")
        return script

    new_segments: list[ScriptSegment] = []
    for index, source in enumerate(script.segments):
        item = translated[index] if index < len(translated) else {}
        text = str(item.get("text") or "").strip() or source.text
        keywords = [
            str(keyword).strip()
            for keyword in (item.get("keywords") or source.keywords)
            if str(keyword).strip()
        ] or list(source.keywords)
        try:
            duration = int(item.get("duration_estimate") or source.duration_estimate)
        except (TypeError, ValueError):
            duration = source.duration_estimate
        new_segments.append(
            ScriptSegment(text=text, keywords=keywords, duration_estimate=duration)
        )

    title = str(result.get("title") or "").strip() or script.title
    try:
        total = int(result.get("total_duration_estimate") or script.total_duration_estimate)
    except (TypeError, ValueError):
        total = script.total_duration_estimate

    if task_logger is not None:
        task_logger.info(
            f"脚本翻译完成 {source_lang} -> {target_lang}（{len(new_segments)} 段，结构保持不变）"
        )
    return GeneratedScript(
        title=title, segments=new_segments, total_duration_estimate=total
    )


async def generate_youtube_metadata(
    ai_client,
    *,
    title: str,
    script: GeneratedScript | None = None,
    content: str = "",
    target_lang: str = "en",
    task_logger=None,
) -> dict:
    """Build English YouTube title / description / tags for discovery."""
    source = ""
    if script is not None:
        source = "\n".join(seg.text for seg in script.segments if seg.text)
    source = source or content
    user_prompt = (
        f"Target language: {target_lang}\n"
        f"Episode source title: {title}\n\n"
        f"Episode narration:\n{source[:6000]}"
    )

    result = await ai_client.complete_json(YOUTUBE_METADATA_PROMPT, user_prompt)
    meta_title = str(result.get("title") or "").strip()[:100] or title
    description = str(result.get("description") or "").strip()
    tags = [
        str(tag).strip().lstrip("#").lower()
        for tag in (result.get("tags") or [])
        if str(tag).strip()
    ]
    tags = list(dict.fromkeys(tags))[:15]

    if not tags:
        tags = _derive_tags(script, title)
    if not description:
        description = _fallback_description(script, title)

    if task_logger is not None:
        task_logger.info(
            f"YouTube 元数据已生成: title={meta_title!r} tags={len(tags)}"
        )
    return {"title": meta_title, "description": description, "tags": tags}
