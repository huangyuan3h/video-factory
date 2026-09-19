"""Dense key-point prompts for ``type=book`` episode scripts.

Book episodes are chapter excerpts: left as-is, an AI script step tends to pad
them with preface fluff and TOC-style transitions ("本章将……"), which reads as
empty narration. This module centralises two short prompt paths:

* :data:`BOOK_DENSE_REWRITE_PROMPT` — a "要点压缩" rewrite used before script
  generation, even when the caller did not set ``rewrite_content``.
* :data:`BOOK_DENSE_SCRIPT_PROMPT` — the script generator system prompt that
  keeps the final spoken lines dense and short-form friendly (3-5 hard points,
  ~45-90s) and asks for chapter-relevant keywords.

Both prompts are dependency-free constants so they are cheap to unit test.
"""

from __future__ import annotations

BOOK_DENSE_REWRITE_PROMPT = (
    "你是一位把书籍章节压缩成短视频要点的资深编辑。\n"
    "任务：把输入章节压缩为 3-5 条硬核要点，只保留事实、机制、关键转折与数字。\n"
    "要求：\n"
    "1. 删除序言套话、目录腔、作者生平、重复铺陈，以及与主线无关的旁枝\n"
    "2. 用口语化、可直接朗读的中文短句，一条要点一句话\n"
    "3. 不要 markdown、不要小标题、不要“本章将……”之类的过渡句\n"
    "4. 全文约 260-420 字，朗读约 45-90 秒\n"
    "只输出压缩后的口播稿正文，不要任何解释。"
)

BOOK_DENSE_SCRIPT_PROMPT = (
    "你是中文竖屏短视频的脚本作者，擅长把书籍章节浓缩成高信息密度的口播。\n"
    "规则：\n"
    "1. 只保留事实、机制、关键转折和数字，写成 3-5 个要点\n"
    "2. 删除序言套话、目录腔、作者生平、与主线无关的旁枝\n"
    "3. 口语化短句，第一句是钩子，不要空话和重复\n"
    "4. 全文朗读控制在 45-90 秒（约 260-420 字），内容实在时可到 120 秒\n"
    "5. 拆成 3-5 个段落，每段 2-3 个具体配图关键词\n"
    "6. 关键词要贴合章节主题（如日本经济、泡沫经济、日元升值、制造业、"
    "金融危机、出口导向），避免泛泛的 stock market / world news\n\n"
    "输出 JSON：\n"
    "{\n"
    '  "title": "短标题",\n'
    '  "segments": [\n'
    '    {"text": "要点口播", "keywords": ["japan economy", "bubble economy"], '
    '"duration_estimate": 20}\n'
    "  ],\n"
    '  "total_duration_estimate": 75\n'
    "}"
)


def book_dense_rewrite_prompt() -> str:
    """System prompt for the forced book "要点压缩" rewrite."""
    return BOOK_DENSE_REWRITE_PROMPT


def book_dense_script_prompt() -> str:
    """System prompt for dense book script generation."""
    return BOOK_DENSE_SCRIPT_PROMPT
