"""Gentle, friendly prompts for ``type=book`` episode scripts.

Book episodes are chapter retellings, not clickbait shorts. Left as-is, an AI
script step tends to pad them with preface fluff and TOC-style transitions
("本章将……") and to rush through stacked facts and numbers. This module
centralises two prompt paths with a warm "explaining a book to a friend" voice:

* :data:`BOOK_DENSE_REWRITE_PROMPT` — a "讲书" rewrite used before script
  generation, even when the caller did not set ``rewrite_content``.
* :data:`BOOK_DENSE_SCRIPT_PROMPT` — the script generator system prompt that
  keeps the final spoken lines calm and full-length (a few ideas, ~800-1000
 汉字 / ~180-240s) and asks for book-agnostic, shootable keywords.

The "dense" names are kept for backward compatibility; the clearer aliases are
:data:`BOOK_FRIENDLY_REWRITE_PROMPT` / :data:`BOOK_FRIENDLY_SCRIPT_PROMPT`.

Pacing is **parameterised** so a future longer "podcast" mode can reuse the
same prompts: :func:`build_book_rewrite_prompt` and
:func:`build_book_script_prompt` accept ``target_seconds`` or
``target_minutes`` and derive the char range / idea count / segment count from
the target duration and :mod:`src.config`. The podcast mode itself is not
implemented here; the default-built strings are module constants so they stay
cheap to unit test.
"""

from __future__ import annotations

import math

from ..config import settings

# The spoken window is the target duration +/- this many seconds; the prompt
# always states the resulting range (default 210s -> 180-240s).
_PACE_SPREAD_SECONDS = 30

# Rough spoken seconds per idea / per segment used to scale the counts for
# longer targets. For the default 210s target these yield 5-8 ideas and 8-12
# segments (each segment ~15-25s).
_SECONDS_PER_IDEA_HIGH = 42.0
_SECONDS_PER_IDEA_LOW = 26.0
_SECONDS_PER_SEGMENT_HIGH = 26.0
_SECONDS_PER_SEGMENT_LOW = 17.5


def _resolve_target_seconds(
    target_seconds: int | None = None, target_minutes: float | None = None
) -> int:
    """Pick the narration target in seconds (minutes win when both are given)."""
    if target_minutes is not None:
        return max(1, int(round(float(target_minutes) * 60)))
    if target_seconds is not None:
        return max(1, int(target_seconds))
    return int(getattr(settings, "book_target_seconds", 210) or 210)


def book_char_range(
    target_seconds: int | None = None, target_minutes: float | None = None
) -> tuple[int, int]:
    """Derive the ``(low, high)`` 汉字 target from the target duration.

    The spoken window is the target +/-30 s and the effective narration rate is
    ``settings.book_chars_per_second`` (default 4.0 chars/s, already accounting
    for the slower book TTS rate and the pauses between segments). Each bound is
    rounded **up** to the next 100 characters, which maps the default 210 s
    target to a clean 800-1000 字::

        180 s * 4.0 = 720  -> 800
        240 s * 4.0 = 960  -> 1000
    """
    seconds = _resolve_target_seconds(target_seconds, target_minutes)
    cps = float(getattr(settings, "book_chars_per_second", 4.0) or 4.0)
    low_seconds = max(1, seconds - _PACE_SPREAD_SECONDS)
    high_seconds = seconds + _PACE_SPREAD_SECONDS
    low = int(math.ceil(low_seconds * cps / 100.0) * 100)
    high = int(math.ceil(high_seconds * cps / 100.0) * 100)
    return max(1, low), max(1, high)


def book_segment_range(
    target_seconds: int | None = None, target_minutes: float | None = None
) -> tuple[int, int]:
    """Derive the ``(low, high)`` segment count from the target duration.

    Exposed for the script length guard in :mod:`src.services.video_service`,
    which tells the model how many segments the shorter rewrite should use.
    """
    return _segment_range(_resolve_target_seconds(target_seconds, target_minutes))


def _idea_range(seconds: int) -> tuple[int, int]:
    low = max(5, int(round(seconds / _SECONDS_PER_IDEA_HIGH)))
    high = max(low, int(round(seconds / _SECONDS_PER_IDEA_LOW)))
    return low, high


def _segment_range(seconds: int) -> tuple[int, int]:
    low = max(8, int(round(seconds / _SECONDS_PER_SEGMENT_HIGH)))
    high = max(low, int(round(seconds / _SECONDS_PER_SEGMENT_LOW)))
    return low, high


def build_book_rewrite_prompt(
    target_seconds: int | None = None, target_minutes: float | None = None
) -> str:
    """Build the friendly "讲书" rewrite prompt for the given target length."""
    low, high = book_char_range(target_seconds, target_minutes)
    seconds = _resolve_target_seconds(target_seconds, target_minutes)
    low_seconds = max(1, seconds - _PACE_SPREAD_SECONDS)
    high_seconds = seconds + _PACE_SPREAD_SECONDS
    idea_low, idea_high = _idea_range(seconds)

    return (
        "你是一位擅长把一本书讲给朋友听的讲书人。\n"
        "任务：把输入章节改写成温和、口语化的讲述稿，像和朋友聊一本书。\n"
        "要求：\n"
        "1. 你是第三人称讲书人：提到书的作者时就说“作者”，绝不用第一人称冒充作者"
        "（不要出现“我住在加州”“我在第四章说过”这类作者口吻的话）；也不要提及其他章节"
        "（如“第四章说过”），每一集都要能独立听懂\n"
        "2. 开头先用一句话温和地介绍这一集讲什么（比如“这一集我们来聊聊……”），"
        "不要用悬念或标题党开场\n"
        "3. 用短句，一句话只讲一个意思；大约每两三段的开头用一句自然的口语过渡"
        "（比如“我们先来看……”“你可能会想……”“说到这里……”“接下来……”“简单来说……”），"
        "每次换一个，别连着用同一句\n"
        "4. 不要堆砌事实和数字，每段最多两个数字；只有数字不好懂时才用大白话解释它的意思，"
        "换着说法，全文“这意味着”最多出现两次；不要自己编类比、推算或结论\n"
        "5. 每段都要能独立听懂：开场不要用“这相当于/这意味着/这说明”去指上一段；"
        "若为控制数字而删掉数字，就改写或删掉整句，不要留下没有着落的指代；"
        "宁可保留一个具体细节，也不要“非常多”“极高”这类空泛说法\n"
        "6. 结尾温和中性：用一两句话总结这一集讲的内容（比如“小结一下……”），"
        "不评判、不煽情，不用“愚蠢”“离谱”“疯狂”这类词，也不要提到别的集数\n"
        "7. 删除序言套话、目录腔、作者生平、重复铺陈和与主线无关的旁枝\n"
        "8. 不要标题党、不要夸张（如“震惊”“必看”），忠于原章节，不编造事实\n"
        "9. 不要 markdown、不要小标题、不要“本章将……”之类的过渡句\n"
        f"10. 全文约 {low}-{high} 字，朗读约 {low_seconds}-{high_seconds} 秒，"
        f"约 {idea_low}-{idea_high} 个要点，每段约 50-90 字\n"
        "只输出改写后的口播稿正文，不要任何解释。"
    )


def build_book_script_prompt(
    target_seconds: int | None = None, target_minutes: float | None = None
) -> str:
    """Build the friendly book script system prompt for the given target length."""
    low, high = book_char_range(target_seconds, target_minutes)
    seconds = _resolve_target_seconds(target_seconds, target_minutes)
    low_seconds = max(1, seconds - _PACE_SPREAD_SECONDS)
    high_seconds = seconds + _PACE_SPREAD_SECONDS
    idea_low, idea_high = _idea_range(seconds)
    seg_low, seg_high = _segment_range(seconds)

    return (
        "你是一位讲书视频的脚本作者，用温和、像和朋友聊一本书的口吻讲解书籍章节。\n"
        "规则：\n"
        "1. 你是第三人称讲书人：提到书的作者时就说“作者”，绝不用第一人称冒充作者"
        "（不要出现“我住在加州”“我在第四章说过”这类作者口吻的话）；也不要提及其他章节"
        "（如“第四章说过”），每一集都要能独立听懂\n"
        "2. 开头用一句话温和地介绍这一集讲什么（比如“这一集我们来聊聊……”），"
        "不要用悬念或标题党开场\n"
        "3. 用短句，一段只讲一个意思；大约每两段的开头用一句自然的口语过渡"
        "（比如“我们先来看……”“你可能会想……”“说到这里……”“接下来……”“简单来说……”），"
        "每次换一个，别连着用同一句\n"
        "4. 不要堆砌事实和数字，每段最多两个数字；只有数字不好懂时才用大白话解释它的意思，"
        "换着说法，全文“这意味着”最多出现两次；不要自己编类比、推算或结论\n"
        "5. 每段都要能独立听懂：开场不要用“这相当于/这意味着/这说明”去指上一段；"
        "若为控制数字而删掉数字，就改写或删掉整句，不要留下没有着落的指代；"
        "宁可保留一个具体细节，也不要“非常多”“极高”这类空泛说法\n"
        "6. 结尾温和中性：用一两句话总结这一集讲的内容（比如“小结一下……”），"
        "不评判、不煽情，不用“愚蠢”“离谱”“疯狂”这类词，也不要提到别的集数\n"
        "7. 输入若已是温和的口语讲述稿，尽量保留它的句子和具体细节，只做分段和写关键词；"
        "只在超长时才精简，不要整篇重写\n"
        "8. 不要标题党、不要夸张（如“震惊”“必看”），忠于章节，不编造事实\n"
        "9. 不要 markdown、不要小标题、不要“本章将……”之类的过渡句\n"
        f"10. 全文朗读约 {low_seconds}-{high_seconds} 秒（约 {low}-{high} 字），"
        f"共约 {idea_low}-{idea_high} 个要点\n"
        f"11. 拆成 {seg_low}-{seg_high} 段，每段约 50-90 字、只讲一个意思\n"
        "12. 每段给 2-3 个具体、可拍摄的英文配图关键词，贴合本章主题中的具体"
        "事物/场景/人物，避免 stock market / world news 这类泛词\n\n"
        "输出 JSON：\n"
        "{\n"
        '  "title": "短标题",\n'
        '  "segments": [\n'
        '    {"text": "本段口播", "keywords": ["old library", "reading lamp"], '
        '"duration_estimate": 20}\n'
        "  ],\n"
        f'  "total_duration_estimate": {seconds}\n'
        "}"
    )


# Default-built prompts (config defaults). Kept under the historical "dense"
# names for backward compatibility.
BOOK_DENSE_REWRITE_PROMPT = build_book_rewrite_prompt()
BOOK_DENSE_SCRIPT_PROMPT = build_book_script_prompt()

# Clearer aliases for new code / docs.
BOOK_FRIENDLY_REWRITE_PROMPT = BOOK_DENSE_REWRITE_PROMPT
BOOK_FRIENDLY_SCRIPT_PROMPT = BOOK_DENSE_SCRIPT_PROMPT


def book_dense_rewrite_prompt() -> str:
    """System prompt for the forced book "讲书" rewrite (default pacing)."""
    return BOOK_DENSE_REWRITE_PROMPT


def book_dense_script_prompt() -> str:
    """System prompt for friendly book script generation (default pacing)."""
    return BOOK_DENSE_SCRIPT_PROMPT
