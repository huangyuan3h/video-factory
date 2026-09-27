"""Zhihu (知乎) 专栏文章 publisher (Playwright, semi-auto).

Research: ``docs/zhihu-publishing-research.md`` §1.3 — there is no usable
official content-write API, so the only realistic path is browser automation.
This module mirrors the existing Douyin/Xiaohongshu publishers
(Playwright + persistent profile + human pacing) but drives the 专栏 editor
at https://zhuanlan.zhihu.com/write instead of a video upload page.

Pure Markdown parsing (``parse_inline`` / ``parse_zhihu_markdown``) is kept
free of Playwright so it can be unit tested. Everything browser-related has
explicit timeouts and never blocks forever.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .base import BasePublisher, PublishResult

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

DEFAULT_PROFILE_DIR = Path.home() / ".video-factory" / "zhihu-profile"
LOGIN_URL = "https://www.zhihu.com/signin"
WRITE_URL = "https://zhuanlan.zhihu.com/write"
HOME_URL = "https://www.zhihu.com/"
CREATOR_URL = "https://www.zhihu.com/creator"
SETTINGS_URL = "https://www.zhihu.com/settings/account"
NEED_LOGIN_FILE = Path.home() / "Projects" / "karios-series-output" / "zhihu" / "NEED_LOGIN"
DEFAULT_SMOKE_DIR = Path.home() / "Projects" / "karios-series-output" / "zhihu" / "smoke"
PUBLISHED_FILENAME = "published.json"

LOGIN_POLL_SECONDS = 20 * 60  # 20 minutes max
LOGIN_RENOTIFY_SECONDS = 5 * 60  # re-notify every 5 minutes
CAPTCHA_WAIT_SECONDS = 20 * 60

NOTIFY_TITLE = "Video Factory 知乎发布"
NOTIFY_LOGIN_MSG = "请在弹出的浏览器里扫码登录知乎"
NOTIFY_CAPTCHA_MSG = "知乎出现验证码/安全验证，请在浏览器里手动完成"

# Selectors are best-effort: Zhihu changes markup often, so every lookup tries
# several candidates and raises a clear error naming the element sought.
TITLE_SELECTORS = [
    'textarea[placeholder*="标题"]',
    'input[placeholder*="标题"]',
    '[data-testid="title"] textarea',
    '.Write-titleInput textarea',
    '.Write-titleInput input',
    '.TitleInput textarea',
    '.PostEditor-title textarea',
    '.PostEditor-title input',
]
EDITOR_SELECTORS = [
    ".ProseMirror",
    '[role="textbox"]',
    ".DraftEditor-root",
    '[contenteditable="true"]',
    ".Write-editor [contenteditable]",
    ".PostEditor-editor [contenteditable]",
    ".Editable",
]
SAVE_DRAFT_SELECTORS = [
    'button:has-text("保存草稿")',
    'button:has-text("存草稿")',
    'button:has-text("保存")',
]
PUBLISH_SELECTORS = [
    'button:has-text("发布")',
    'button:has-text("发表")',
    'button:has-text("更新")',
]
CONFIRM_PUBLISH_SELECTORS = [
    'button:has-text("确认发布")',
    'button:has-text("确定")',
    'button:has-text("发布")',
]
IMAGE_INPUT_SELECTORS = [
    'input[type="file"][accept*="image"]',
    'input[type="file"]',
]
# Real publish-panel DOM (verified 2026-09-27 headless, screenshots in smoke/):
# - Cover: right panel "发布设置 > 添加封面", hidden input.UploadPicture-input
#   (accept=".jpeg, .jpg, .png"); preview img[alt="封面图"] when set.
# - Topics: right panel "文章话题", button "添加话题" reveals
#   input[aria-label="搜索话题"]; suggestions button.css-gfrh4c;
#   selected chips .css-nut0iz .css-1d3pntc (Zhihu limit 5).
# - Declaration: right panel "创作声明", button[role=combobox] showing
#   无声明 / 包含 AI 辅助创作 ...; dropdown buttons include
#   "包含 AI 辅助创作 作者对内容负责".
# - Column: no 专栏 UI on write page; column must exist already (profile 专栏0
#   means missing). Never auto-create.
COVER_INPUT_SELECTOR = "input.UploadPicture-input"
COVER_PREVIEW_SELECTOR = 'img[alt="封面图"]'
TOPIC_ADD_BUTTON_NAME = "添加话题"
TOPIC_SEARCH_INPUT_SELECTOR = 'input[aria-label="搜索话题"]'
TOPIC_SUGGESTION_SELECTOR = "button.css-gfrh4c"
TOPIC_CHIP_SELECTOR = ".css-nut0iz .css-1d3pntc"
# Verified 2026-09-27: with 3 chips the 添加话题 button disappears (0 nodes);
# with 2 chips it exists. Zhihu's article topic limit is 3.
TOPIC_LIMIT = 3
DECL_AI_OPTION_TEXT = "包含 AI 辅助创作"
DECL_NONE_TEXT = "无声明"
COVER_BUTTON_TEXTS = ["设置封面", "添加封面", "上传封面", "更换封面", "封面"]
TOPIC_BUTTON_TEXTS = ["添加话题", "添加标签", "选择话题", "+ 话题"]
AI_DECL_TEXTS = ["AI", "创作声明", "AI 辅助", "AI辅助", "AI 生成", "声明"]
CAPTCHA_TEXTS = ["验证码", "安全验证", "滑动", "点击图中", "请完成验证", "拖动滑块"]
CAPTCHA_SELECTORS = [
    '[id*="captcha" i]',
    '[class*="captcha" i]',
    '[class*="Captcha"]',
    '[class*="yidun"]',
    '[class*="NECaptcha"]',
    '[class*="verify" i][class*="slide" i]',
    'iframe[src*="captcha" i]',
    'iframe[src*="verify" i]',
]
LOGGED_IN_SELECTORS = [
    'img.Avatar',
    '.Avatar',
    'button:has-text("提问")',
    'a[href*="/people/"]',
    '[data-testid="AppHeader-profile"]',
    ".AppHeader-profile",
]
LOGGED_OUT_SELECTORS = [
    'a[href*="/signin"]',
    'button:has-text("登录")',
    ".SignFlow",
]


# --------------------------------------------------------------------------- #
# Pure Markdown parsing (unit-testable, no browser)
# --------------------------------------------------------------------------- #

BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def parse_inline(text: str) -> list[dict]:
    """Split ``text`` into ``[{text, bold}]`` segments on ``**bold**``.

    Unmatched ``**`` is kept verbatim so nothing is silently dropped.
    """
    spans: list[dict] = []
    pos = 0
    for m in BOLD_RE.finditer(text):
        if m.start() > pos:
            spans.append({"text": text[pos : m.start()], "bold": False})
        spans.append({"text": m.group(1), "bold": True})
        pos = m.end()
    if pos < len(text):
        spans.append({"text": text[pos:], "bold": False})
    if not spans:
        spans.append({"text": "", "bold": False})
    return spans


def _strip_asterisk_caption(line: str) -> str | None:
    s = line.strip()
    if len(s) >= 2 and s.startswith("*") and s.endswith("*") and not s.startswith("**"):
        return s.strip("*").strip()
    return None


def parse_zhihu_markdown(md_text: str) -> dict:
    """Parse Zhihu article Markdown into ``{title, blocks}``.

    Block kinds: ``heading`` {level, text, spans}, ``paragraph`` {spans},
    ``quote`` {text, spans}, ``image`` {src, alt, caption}, ``divider`` {}.
    The first ``# `` line becomes the title. Image captions are ``*...*``
    lines immediately following an ``![alt](src)`` line.

    Defensive: internal writing notes (备选标题, 开头：/结尾： labels,
    video placeholders, TODO/审稿/备注) are stripped via
    :func:`sanitize_zhihu_markdown` first, so the converter can never emit
    them as body blocks even if a source file still carries them. Use
    :func:`assert_no_zhihu_meta_leaks` / :func:`load_payload` for the hard
    gate that FAILS publishing on such leaks.
    """
    # sanitize_zhihu_markdown is defined below; late import via globals to
    # keep this function position stable (no forward-ref issue at runtime
    # because the call happens after module load).
    try:
        _sanitize = globals().get("sanitize_zhihu_markdown")
        if callable(_sanitize):
            md_text, _ = _sanitize(md_text or "")
    except Exception:
        pass
    lines = (md_text or "").splitlines()
    title = ""
    blocks: list[dict] = []
    i = 0
    # Title: first "# " line.
    for idx, ln in enumerate(lines):
        if ln.startswith("# "):
            title = ln[2:].strip()
            i = idx + 1
            break
    pending_caption_for: int | None = None
    while i < len(lines):
        raw = lines[i]
        s = raw.strip()
        i += 1
        if not s:
            continue
        if s.startswith("# ") and not title:
            title = s[2:].strip()
            continue
        if s.startswith("## "):
            text = s[3:].strip()
            blocks.append({"kind": "heading", "level": 2, "text": text, "spans": parse_inline(text)})
            continue
        if s.startswith("### "):
            text = s[4:].strip()
            blocks.append({"kind": "heading", "level": 3, "text": text, "spans": parse_inline(text)})
            continue
        if s in ("---", "***", "___"):
            blocks.append({"kind": "divider"})
            continue
        if s.startswith(">"):
            text = s.lstrip(">").strip()
            blocks.append({"kind": "quote", "text": text, "spans": parse_inline(text)})
            continue
        m = re.match(r"!\[(.*?)\]\((.*?)\)", s)
        if m:
            alt, src = m.group(1).strip(), m.group(2).strip()
            caption = ""
            # Attach a following *caption* line if present.
            if i < len(lines):
                cap = _strip_asterisk_caption(lines[i])
                if cap is not None:
                    caption = cap
                    i += 1
            blocks.append({"kind": "image", "src": src, "alt": alt, "caption": caption})
            continue
        cap_only = _strip_asterisk_caption(s)
        if cap_only is not None and blocks and blocks[-1].get("kind") == "image" and not blocks[-1].get("caption"):
            blocks[-1]["caption"] = cap_only
            continue
        # Skip raw HTML comments / placeholders for video embeds; keep visible text.
        if s.startswith("<!--"):
            continue
        blocks.append({"kind": "paragraph", "text": s, "spans": parse_inline(s)})
    return {"title": title, "blocks": blocks}


def count_text_blocks(blocks: list[dict]) -> int:
    """Count paragraph/heading/quote blocks (for draft verification)."""
    return sum(1 for b in blocks if b.get("kind") in ("paragraph", "heading", "quote"))


# Correct ending for self-made-chart articles (owner-approved 2026-09-27):
# single merged sentence, no video mention when no video attached, no separate
# 素材与授权 section when no third-party material, one AI statement only.
SELF_MADE_ENDING = (
    "本文图表均为自研回测结果，历史数据仅供参考；文案由 AI 辅助生成。"
    "本内容为投资者教育，不构成投资建议，过往业绩不代表未来表现。"
    "投资有风险，入市需谨慎。"
)


def build_disclaimer_ending(
    has_video: bool = False,
    has_third_party: bool = False,
    third_party_note: str = "",
) -> str:
    """Build the article ending that matches reality (pure, unit-testable).

    - Self-made charts, no video, no third-party → :data:`SELF_MADE_ENDING`.
    - ``has_video`` adds a video-AI sentence (only when a video is attached).
    - ``has_third_party`` prepends a 素材与授权 sentence (only when used).
    - Duplicate AI statements are merged into one sentence.
    """
    parts: list[str] = []
    if has_third_party:
        note = (third_party_note or "第三方素材已获授权").strip()
        parts.append(f"【素材与授权】{note}；")
    if has_video:
        parts.append("本文图表均为自研回测结果，历史数据仅供参考；文案与视频口播由 AI 辅助生成。")
    else:
        parts.append("本文图表均为自研回测结果，历史数据仅供参考；文案由 AI 辅助生成。")
    parts.append("本内容为投资者教育，不构成投资建议，过往业绩不代表未来表现。投资有风险，入市需谨慎。")
    text = "".join(parts)
    if not has_video and not has_third_party:
        assert text == SELF_MADE_ENDING, "self-made ending must match owner-approved text"
    return text


def normalize_topics(topics: list[str], limit: int = TOPIC_LIMIT) -> list[str]:
    """Dedupe + strip topics, capped to Zhihu's limit (pure, unit-testable)."""
    seen: list[str] = []
    for t in topics or []:
        s = str(t or "").strip()
        if not s or s in seen:
            continue
        seen.append(s)
        if len(seen) >= limit:
            break
    return seen


def is_upload_done_src(src: str) -> bool:
    """True when an upload has left blob:/data: (safe to save).

    Lifecycle (verified 2026-09-27): blob: → https://pic-private.zhihu.com/…
    (temporary preview, progress gone) → https://*.zhimg.com/* (permanent,
    only after save + reload). Saving while still blob: loses the image.
    """
    s = (src or "").strip()
    if not s or s.startswith("blob:") or s.startswith("data:"):
        return False
    return s.startswith("https://") and ("zhihu.com" in s or "zhimg.com" in s)


def is_final_image_src(src: str) -> bool:
    """True when an editor img src is the permanent CDN URL (after reload).

    Only https://*.zhimg.com/* counts (pic-private is pre-save temporary).
    """
    s = (src or "").strip()
    if not s or s.startswith("blob:") or s.startswith("data:"):
        return False
    return "zhimg.com" in s and s.startswith("https://")


def select_cover_image(images_in_order: list[str], cover_image: str | None) -> str | None:
    """Pick the cover path: payload field first, else first chart (pure)."""
    if cover_image and str(cover_image).strip():
        return str(cover_image)
    imgs = [str(x) for x in (images_in_order or []) if str(x or "").strip()]
    return imgs[0] if imgs else None


def ai_after_reload_blocks_publish(decl_state: str | None, ai_set_before_save: bool) -> bool:
    """Whether a missing AI badge after draft reload must block publish (pure).

    Zhihu draft quirk (verified 2026-09-27, fix2 ep9): the 创作声明 combobox
    is set to 包含 AI 辅助创作 before save (screenshot proof), reverts to
    无声明 after draft reload, but persists on the PUBLIC page after
    publish/update (ep9 public footer badge verified logged-in). So when the
    panel was successfully set before save, an after-reload 无声明 is advisory
    (re-applied before publish), not fatal. Only block when it was never set.
    """
    cur = (decl_state or "").strip()
    if DECL_AI_OPTION_TEXT in cur or "AI" in cur:
        return False
    return not bool(ai_set_before_save)


# --------------------------------------------------------------------------- #
# Internal writing-notes leak guard (leakfix 2026-09-27: ep1/ep2 published
# with 备选标题 / 开头： labels in the body).
#
# Root cause: article.md files carried editor notes (alternate titles,
# section labels like 开头：/结尾：/标题：, video placeholders, TODO/审稿/
# 备注) and parse_zhihu_markdown() copied every non-empty line into a
# paragraph/heading/quote block with no filtering. The publisher then typed
# those blocks verbatim into the Zhihu editor.
#
# Fix layers (all pure + unit-tested):
#   1. sanitize_zhihu_markdown(): strip meta lines, fix "## 开头：X" headings.
#   2. parse_zhihu_markdown(): sanitizes defensively (never emits meta blocks).
#   3. find_zhihu_meta_leaks() + assert_no_zhihu_meta_leaks(): hard gate —
#      load_payload() FAILS (ValueError) when raw markdown still has meta.
# --------------------------------------------------------------------------- #

HEADING_LABEL_RE = re.compile(r"^\s*#{1,3}\s*(开头|结尾|标题|备选标题|备选|审稿|备注|TODO|FIXME)\s*[:：]")
PLAIN_LABEL_RE = re.compile(r"^\s*(开头|结尾|标题|审稿|备注|TODO|FIXME|XXX)\s*[:：]")
TITLE_USE_RE = re.compile(r"标题\s*[（(]\s*发布用")
WORKING_TITLE_RE = re.compile(r"^\s*#\s*专栏文章\b")
QUOTE_NUMBERED_RE = re.compile(r"^\s*>\s*\d+[.\、．。]\s*")
PLAIN_NUMBERED_RE = re.compile(r"^\s*\d+[.\、．。]\s*\S+")
TODO_RE = re.compile(r"\b(TODO|FIXME|XXX)\b", re.IGNORECASE)
SHENGAO_BEIZHU_RE = re.compile(r"(审稿|备注)\s*[:：]")
BRACKET_NOTE_RE = re.compile(r"【[^】]*?(发布时|嵌入|占位|留档|备选|待定|手动).*?】")
VIDEO_PLACEHOLDER_SUBSTRS = ("【发布时", "在此嵌入", "由本人手动上传", "放在开头之后")


def _is_meta_line(line: str, has_beixuan: bool, lineno_1based: int = 0) -> bool:
    """True when a single markdown line is internal writing notes (not body)."""
    s = line.strip()
    if not s:
        return False
    if "备选标题" in s:
        return True
    if "发布只用主标题" in s or "其余留档" in s:
        return True
    if "留档" in s:
        return True
    if TITLE_USE_RE.search(s):
        return True
    if WORKING_TITLE_RE.match(line):
        return True
    if HEADING_LABEL_RE.match(line):
        return True
    # Plain "开头：..." / "标题：..." labels (but never 图注：/口径盒 etc.).
    if PLAIN_LABEL_RE.match(line):
        return True
    for sub in VIDEO_PLACEHOLDER_SUBSTRS:
        if sub in s:
            return True
    if BRACKET_NOTE_RE.search(s):
        # 【素材与授权】 is legitimate body (third-party only); it never
        # matches BRACKET_NOTE_RE keywords, but double-guard here.
        if "素材与授权" in s and "发布时" not in s and "嵌入" not in s:
            return False
        return True
    if TODO_RE.search(s):
        return True
    if SHENGAO_BEIZHU_RE.search(s):
        return True
    # Alternate-title leftovers: "> 1. xxx" (ep2/ep8/ep3) or "1. xxx" header
    # (ep11) — only when the file carries a 备选标题 block.
    if has_beixuan:
        if QUOTE_NUMBERED_RE.match(line):
            return True
        if lineno_1based and lineno_1based <= 15 and PLAIN_NUMBERED_RE.match(line):
            return True
    return False


def _strip_heading_label(line: str) -> str:
    """Turn '## 开头：X' into '## X' (same for 结尾/标题/备选/审稿/备注/TODO)."""
    m = re.match(r"^(\s*#{1,3}\s*)(开头|结尾|标题|备选标题|备选|审稿|备注|TODO|FIXME)\s*[:：]\s*(.*)$", line)
    if m:
        prefix, _, rest = m.group(1), m.group(2), m.group(3)
        return f"{prefix}{rest}".rstrip()
    m2 = re.match(r"^(\s*)(开头|结尾|标题|审稿|备注|TODO|FIXME|XXX)\s*[:：]\s*(.*)$", line)
    if m2:
        _, _, rest = m2.group(1), m2.group(2), m2.group(3)
        # Only strip when there is real content after the label; a bare
        # "开头：" line is pure meta (caller drops it).
        if rest.strip():
            return rest.strip()
    return line


def find_zhihu_meta_leaks(md_text: str) -> list[str]:
    """Return human-readable leak hits (empty = clean). Pure, unit-testable."""
    lines = (md_text or "").splitlines()
    has_beixuan = "备选标题" in (md_text or "")
    hits: list[str] = []
    for idx, ln in enumerate(lines, start=1):
        s = ln.strip()
        if not s:
            continue
        # Headings with labels count as leaks even though sanitizer could fix
        # them — the gate forces fixing at the source file.
        if HEADING_LABEL_RE.match(ln) or PLAIN_LABEL_RE.match(ln):
            # Allow legitimate "图注："? Not in label lists, so no exception.
            hits.append(f"line {idx}: {s[:80]}")
            continue
        if _is_meta_line(ln, has_beixuan, idx):
            hits.append(f"line {idx}: {s[:80]}")
    return hits


def sanitize_zhihu_markdown(md_text: str) -> tuple[str, list[str]]:
    """Strip internal notes; fix '## 开头：X' headings. Returns (cleaned, removed).

    Pure pre-publish sanitizer. Removes whole meta lines, rewrites labelled
    headings to their real text, drops the early '---' separator that belongs
    to the ep11-style header block. Late '---' dividers (before the ending)
    are kept.
    """
    lines = (md_text or "").splitlines()
    has_beixuan = "备选标题" in (md_text or "")
    cleaned: list[str] = []
    removed: list[str] = []
    nonempty_kept = 0
    for idx, ln in enumerate(lines, start=1):
        s = ln.strip()
        if not s:
            cleaned.append(ln)
            continue
        # Early divider belonging to a meta header block (ep11 line 9):
        # only when still in the header region and little real content kept.
        if s == "---" and has_beixuan and idx <= 15 and nonempty_kept <= 2:
            removed.append(f"line {idx}: {s[:80]}")
            continue
        if _is_meta_line(ln, has_beixuan, idx):
            # Headings like "## 开头：X" are fixable: keep "## X".
            if HEADING_LABEL_RE.match(ln):
                fixed = _strip_heading_label(ln)
                if fixed.strip() and fixed.strip() not in ("#", "##", "###"):
                    cleaned.append(fixed)
                    removed.append(f"line {idx}: {s[:80]} -> {fixed.strip()[:60]}")
                    if fixed.strip():
                        nonempty_kept += 1
                else:
                    removed.append(f"line {idx}: {s[:80]}")
                continue
            if PLAIN_LABEL_RE.match(ln):
                fixed = _strip_heading_label(ln)
                # If stripping leaves real content, keep it; else drop.
                if fixed.strip() and fixed.strip() != s:
                    cleaned.append(fixed)
                    removed.append(f"line {idx}: {s[:80]} -> {fixed.strip()[:60]}")
                    nonempty_kept += 1
                else:
                    removed.append(f"line {idx}: {s[:80]}")
                continue
            removed.append(f"line {idx}: {s[:80]}")
            continue
        cleaned.append(ln)
        nonempty_kept += 1
    # Collapse 3+ consecutive blanks to at most 2 (keep diffs small).
    out: list[str] = []
    blanks = 0
    for ln in cleaned:
        if not ln.strip():
            blanks += 1
            if blanks <= 2:
                out.append(ln)
        else:
            blanks = 0
            out.append(ln)
    return "\n".join(out) + ("\n" if out and not out[-1].endswith("\n") else "" if out else ""), removed


def assert_no_zhihu_meta_leaks(md_text: str) -> None:
    """Hard gate: raise ValueError when any internal-notes line remains."""
    hits = find_zhihu_meta_leaks(md_text)
    if hits:
        raise ValueError(f"zhihu meta leaks detected ({len(hits)}): " + "; ".join(hits[:8]))


# --------------------------------------------------------------------------- #
# Publish-success detection (leakfix B: ep2 reported FAILED but was live).
#
# The old code treated any publish-click exception as failure without looking
# at the page. Zhihu often navigates to /p/<id> even when the click future
# times out ("not enabled" / timeout). New rule: a URL of /p/<id> (no /edit,
# no /write) OR a published-article DOM counts as success. After ANY click
# error we re-check the page before reporting failure, and we never click
# publish twice once the article is live.
# --------------------------------------------------------------------------- #

ARTICLE_ID_RE = re.compile(r"/p/(\d+)")
PUBLISHED_DOM_MARKERS = (
    "Post-Title",
    "Post-Main",
    "Post-RichText",
    "Post-Header",
    "ColumnPage",
    "ContentItem",
    "RichContent",
)
EDITOR_DOM_MARKERS = ("ProseMirror", "contenteditable", "保存草稿", "Write-titleInput")


def extract_zhihu_article_id(url: str) -> str | None:
    """Extract the numeric article id from a Zhihu专栏 URL, else None."""
    m = ARTICLE_ID_RE.search(url or "")
    return m.group(1) if m else None


def is_published_article_url(url: str) -> bool:
    """True when url is a public article (/p/<id>, not /edit or /write)."""
    u = (url or "").strip()
    if not u or "/zhuanlan.zhihu.com/p/" not in u:
        # Also accept bare /p/<id> paths.
        if not ARTICLE_ID_RE.search(u):
            return False
    if "/edit" in u or "/write" in u or "/draft" in u:
        return False
    return extract_zhihu_article_id(u) is not None


def is_published_article_html(html: str) -> bool:
    """Heuristic for a published-article DOM (vs editor). Pure, testable."""
    h = html or ""
    if not h:
        return False
    has_pub = any(m in h for m in PUBLISHED_DOM_MARKERS)
    has_editor = any(m in h for m in EDITOR_DOM_MARKERS)
    if has_pub and not has_editor:
        return True
    if has_pub and has_editor:
        # Edit view can embed a preview; published markers alone are weak —
        # require public-only text as tiebreak.
        return any(t in h for t in ("编辑于", "发布于", "赞同", "喜欢", "评论"))
    return False


def load_payload(payload_path: str | Path) -> dict:
    """Load ``publish_payload.json`` and resolve relative paths to absolute.

    Hard gate: raises ``ValueError`` when the body markdown still contains
    internal writing notes (备选标题, 开头：/结尾：/标题： labels, video
    placeholders, TODO/审稿/备注, bracketed editor notes). Fix the source
    ``article.md`` with :func:`sanitize_zhihu_markdown` first.
    """
    p = Path(payload_path).resolve()
    data = json.loads(p.read_text(encoding="utf-8"))
    base = p.parent
    body_rel = data.get("body_markdown_path", "article.md")
    body_path = (base / body_rel).resolve()
    cover = data.get("cover_image")
    cover_path = str((base / cover).resolve()) if cover else None
    images = [str((base / rel).resolve()) for rel in data.get("images_in_order", [])]
    md_text = Path(body_path).read_text(encoding="utf-8")
    # Hard gate BEFORE parsing (parse itself sanitizes defensively, but
    # publishing must FAIL on leaks so sources get fixed).
    assert_no_zhihu_meta_leaks(md_text)
    parsed = parse_zhihu_markdown(md_text)
    # Post-sanitize verification: converter output must never contain leaks.
    for b in parsed.get("blocks", []):
        txt = str(b.get("text", "") or "")
        if find_zhihu_meta_leaks(txt + "\n" + str(b.get("caption", "") or "")):
            raise ValueError(f"zhihu meta leak in parsed block: {txt[:80]!r}")
    return {
        "payload_path": str(p),
        "base_dir": str(base),
        "title": data.get("title") or parsed["title"],
        "body_markdown_path": str(body_path),
        "blocks": parsed["blocks"],
        "cover_image": cover_path,
        "topics": list(data.get("topics", [])),
        "column": data.get("column"),
        "declaration": data.get("declaration", ""),
        "images_in_order": images,
        "raw": data,
    }


# --------------------------------------------------------------------------- #
# Pure login-state / idempotency helpers (unit-testable, no browser)
# --------------------------------------------------------------------------- #


def is_captcha_html(html: str) -> bool:
    """True if page HTML/text looks like a captcha/security verification."""
    if not html:
        return False
    return any(t in html for t in CAPTCHA_TEXTS)


def classify_login_state(url: str, html: str) -> str:
    """Classify a Zhihu page as logged-in / logged-out / verification / unknown.

    Pure helper so login-state detection is unit-testable without a browser.
    ``url`` is the current page URL, ``html`` is page content / innerText.
    Returns one of ``"logged_in"``, ``"logged_out"``, ``"verification"``,
    ``"unknown"``.
    """
    u = (url or "").lower()
    h = html or ""
    if is_captcha_html(h):
        return "verification"
    if "signin" in u or "login" in u:
        # Captcha text on a signin page is still verification-first.
        return "verification" if is_captcha_html(h) else "logged_out"
    # Explicit logged-out markers in markup.
    if "SignFlow" in h or "/signin" in h:
        # An avatar/profile link alongside still means logged in.
        if "Avatar" in h or "/people/" in h or "AppHeader-profile" in h:
            return "logged_in"
        return "logged_out"
    # Logged-in markers.
    if "Avatar" in h or "/people/" in h or "AppHeader-profile" in h or "提问" in h:
        return "logged_in"
    if "登录" in h and "Avatar" not in h:
        # Bare 登录 button with no avatar is weak evidence; keep unknown
        # unless URL also suggests logged-out.
        return "unknown"
    return "unknown"


def is_logged_in_state(url: str, html: str) -> bool:
    """True only when :func:`classify_login_state` says ``logged_in``."""
    return classify_login_state(url, html) == "logged_in"


def is_headless_blocked_state(url: str, html: str, title: str = "") -> bool:
    """Heuristic for 'headless is blocked, fall back to headed'.

    True when the page is blank/thin, shows verification, or carries an
    anti-scraping payload (e.g. Zhihu 40362 JSON) — i.e. headless Chrome is
    detected even though the profile itself is logged in.
    """
    if classify_login_state(url, html) == "verification":
        return True
    h = (html or "").strip()
    if not h or len(h) < 300:
        return True
    if "40362" in h or "请求存在异常" in h or "暂时限制本次访问" in h:
        return True
    t = (title or "").strip().lower()
    if t in ("", "about:blank", "blank"):
        return True
    return False


def get_published_path(payload_path: str | Path) -> Path:
    """``published.json`` lives next to the payload (payload folder)."""
    return Path(payload_path).resolve().parent / PUBLISHED_FILENAME


def load_published_record(payload_path: str | Path) -> dict | None:
    """Load ``published.json`` if present, else None. Never raises."""
    try:
        p = get_published_path(payload_path)
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001 - idempotency check is best-effort
        return None


def is_already_published(payload_path: str | Path) -> tuple[bool, dict | None]:
    """True when ``published.json`` already holds a URL."""
    rec = load_published_record(payload_path)
    if rec and str(rec.get("url") or "").strip().startswith("http"):
        return True, rec
    return False, rec


def should_refuse_publish(payload_path: str | Path, force: bool = False) -> tuple[bool, dict | None]:
    """Idempotency gate: refuse publish when already published unless forced."""
    if force:
        return False, load_published_record(payload_path)
    return is_already_published(payload_path)


def build_published_record(
    url: str,
    screenshots: list[str] | None = None,
    title: str = "",
    draft_url: str | None = None,
) -> dict:
    """Build the ``published.json`` payload (url + timestamp + screenshots)."""
    return {
        "url": url,
        "published_at": datetime.now().isoformat(timespec="seconds"),
        "title": title,
        "draft_url": draft_url,
        "screenshots": list(screenshots or []),
    }


def save_published_record(
    payload_path: str | Path,
    record: dict,
) -> Path:
    """Write ``published.json`` next to the payload. Returns the path."""
    out = get_published_path(payload_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def open_url_in_browser(url: str) -> bool:
    """Open URL in the default browser (``open <url>``). Best-effort."""
    try:
        subprocess.run(["open", url], timeout=15, check=False)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"open_url_in_browser failed: {e}")
        return False


def cleanup_own_chrome_processes(profile_dir: str | Path) -> int:
    """Kill leftover Chrome processes that still hold OUR profile dir.

    Matches only command lines containing the profile path, so the user's
    normal Chrome, Docker, :8000 worker and other apps are never touched.
    Returns the number of processes signalled.
    """
    try:
        needle = str(profile_dir)
        ps = subprocess.run(["ps", "aux"], capture_output=True, text=True, timeout=10, check=False)
        killed = 0
        for line in (ps.stdout or "").splitlines():
            if needle in line and ("chrome" in line.lower() or "chromium" in line.lower()):
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    pid = parts[1]
                    # Never kill ourselves (this python) — cmdline match is chrome-only.
                    try:
                        subprocess.run(["kill", pid], timeout=5, check=False)
                        killed += 1
                    except Exception:  # noqa: BLE001, S112
                        continue
        return killed
    except Exception as e:  # noqa: BLE001
        logger.warning(f"cleanup_own_chrome_processes failed: {e}")
        return 0


# --------------------------------------------------------------------------- #
# macOS owner notification (best-effort, never raises)
# --------------------------------------------------------------------------- #


def notify_owner(message: str, title: str = NOTIFY_TITLE) -> None:
    try:
        subprocess.run(
            ["osascript", "-e", f'display notification "{message}" with title "{title}" sound name "Glass"'],
            timeout=10,
            check=False,
            capture_output=True,
        )
    except Exception as e:  # noqa: BLE001 - notification is best-effort
        logger.warning(f"notify_owner failed: {e}")


def bring_chrome_front() -> None:
    try:
        subprocess.run(
            ["osascript", "-e", 'tell application "Google Chrome" to activate'],
            timeout=10,
            check=False,
            capture_output=True,
        )
    except Exception as e:  # noqa: BLE001 - best-effort
        logger.warning(f"bring_chrome_front failed: {e}")


def write_need_login_flag() -> None:
    try:
        NEED_LOGIN_FILE.parent.mkdir(parents=True, exist_ok=True)
        NEED_LOGIN_FILE.write_text(
            "请在弹出的浏览器里扫码登录知乎 (Video Factory zhihu publisher).\n", encoding="utf-8"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"write NEED_LOGIN failed: {e}")


def clear_need_login_flag() -> None:
    try:
        NEED_LOGIN_FILE.unlink(missing_ok=True)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"clear NEED_LOGIN failed: {e}")


# --------------------------------------------------------------------------- #
# Publisher
# --------------------------------------------------------------------------- #


@dataclass
class DraftCheck:
    ok: bool
    title_match: bool
    expected_paragraphs: int
    found_paragraphs: int
    expected_images: int
    found_images: int
    issues: list[str] = field(default_factory=list)


class ZhihuPublisher(BasePublisher):
    """Zhihu 专栏 publisher with a persistent Chromium profile (headless-first)."""

    def __init__(
        self,
        profile_dir: str | Path | None = None,
        headless: bool = True,
        smoke_dir: str | Path | None = None,
        login_timeout_s: int = LOGIN_POLL_SECONDS,
        **kwargs,
    ):
        super().__init__(cookies=None, headless=headless)
        self.profile_dir = Path(profile_dir or DEFAULT_PROFILE_DIR)
        self.smoke_dir = Path(smoke_dir or DEFAULT_SMOKE_DIR)
        self.login_timeout_s = login_timeout_s
        self._pw = None
        self._persistent_ctx = None
        self.extra = kwargs
        self._fell_back_to_headed = False
        self._started_headless = bool(headless)

    @property
    def platform_name(self) -> str:
        return "Zhihu"

    @property
    def login_url(self) -> str:
        return LOGIN_URL

    @property
    def upload_url(self) -> str:
        return WRITE_URL

    # -- browser lifecycle (persistent profile) --------------------------- #

    async def init_browser(self):  # pragma: no cover - needs real browser
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        launch_kwargs: dict = {
            "headless": self.headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-sandbox",
            ],
            "viewport": {"width": 1280, "height": 860},
            "user_agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "locale": "zh-CN",
        }
        # Prefer the locally installed Chrome so no browser download is needed.
        # Falls back to bundled Chromium when Chrome is absent (e.g. CI).
        import shutil

        if shutil.which("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome") or shutil.which(
            "google-chrome"
        ):
            launch_kwargs["channel"] = "chrome"
        self._persistent_ctx = await self._pw.chromium.launch_persistent_context(
            str(self.profile_dir), **launch_kwargs
        )
        self.context = self._persistent_ctx
        pages = self.context.pages
        self.page = pages[0] if pages else await self.context.new_page()

    async def close_browser(self):  # pragma: no cover - needs real browser
        try:
            if self._persistent_ctx is not None:
                await self._persistent_ctx.close()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"close persistent context failed: {e}")
        finally:
            self._persistent_ctx = None
            self.context = None
            self.page = None
        try:
            if self._pw is not None:
                await self._pw.stop()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"playwright stop failed: {e}")
        finally:
            self._pw = None
            self.browser = None

    # -- login ------------------------------------------------------------ #

    async def _page_state(self) -> tuple[str, str, str]:  # pragma: no cover - needs real browser
        """Best-effort (url, html, title) snapshot for login classification."""
        try:
            url = self.page.url or ""
        except Exception:  # noqa: BLE001
            url = ""
        try:
            html = (await self.page.content())[:200000]
        except Exception:  # noqa: BLE001
            html = ""
        try:
            title = await self.page.title()
        except Exception:  # noqa: BLE001
            title = ""
        return url, html, title

    async def check_login(self) -> bool:  # pragma: no cover - needs real browser
        """Cheap login check: creator page first, then home. Headless-safe."""
        for check_url in (CREATOR_URL, HOME_URL):
            try:
                await self.page.goto(check_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)
                for sel in LOGGED_IN_SELECTORS:
                    try:
                        el = await self.page.query_selector(sel)
                        if el is not None:
                            return True
                    except Exception:  # noqa: BLE001, S112 - try next selector
                        continue
                url, html, _ = await self._page_state()
                if is_logged_in_state(url, html):
                    return True
                state = classify_login_state(url, html)
                if state == "logged_in":
                    return True
                # verification / logged_out / unknown → try next URL before giving up.
                if state == "verification":
                    return False
            except Exception as e:  # noqa: BLE001
                logger.warning(f"check_login via {check_url} failed: {e}")
                continue
        try:
            url = (self.page.url or "").lower()
            if "signin" in url or "login" in url:
                return False
        except Exception:  # noqa: BLE001
            pass
        return False

    async def relaunch_headed(self) -> None:  # pragma: no cover - needs real browser
        """Close the headless context and relaunch the SAME profile headed.

        Must close first: Chrome locks the profile dir, so two concurrent
        contexts on the same profile would fail/corrupt state.
        """
        try:
            await self.close_browser()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"relaunch_headed close failed: {e}")
        self.headless = False
        try:
            self._fell_back_to_headed = True
        except AttributeError:
            pass
        await self.init_browser()

    async def ensure_login_headless_first(self) -> tuple[bool, bool, bool]:  # pragma: no cover - needs real browser
        """Headless-first login: cheap check, auto-fallback to headed.

        Returns ``(logged_in, login_was_needed, relaunched_headed)``.
        If the headless check fails (logged-out, QR, captcha, blank,
        detection), the headless context is closed, the SAME profile is
        relaunched headed, the window is brought to front, a macOS
        notification + NEED_LOGIN marker are created, and we wait up to
        ``login_timeout_s`` for manual login/verification. Captchas are
        never solved automatically.
        """
        if await self.check_login():
            return True, False, False
        captcha_now = await self.detect_captcha()
        if captcha_now:
            logger.info("Captcha/verification seen headless — falling back to headed.")
        else:
            logger.info("Headless login check failed — relaunching SAME profile headed.")
        if self.headless:
            try:
                await self.close_browser()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"headless close before headed fallback failed: {e}")
            self.headless = False
            try:
                self._fell_back_to_headed = True
            except AttributeError:
                pass
            await self.init_browser()
            relaunched = True
        else:
            relaunched = bool(getattr(self, "_fell_back_to_headed", False))
        # Headed session: ask owner to log in / verify manually.
        try:
            await self.page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"goto login page failed: {e}")
        bring_chrome_front()
        notify_owner(NOTIFY_LOGIN_MSG)
        write_need_login_flag()
        logger.info("Zhihu login required — waiting for owner to scan QR / verify (up to 20 min).")
        deadline = asyncio.get_event_loop().time() + self.login_timeout_s
        last_notify = asyncio.get_event_loop().time()
        logged_in = False
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(10)
            if await self.check_login():
                logged_in = True
                break
            if await self.detect_captcha():
                notify_owner(NOTIFY_CAPTCHA_MSG)
                # Captcha must be solved manually; keep waiting within budget.
            now = asyncio.get_event_loop().time()
            if now - last_notify >= LOGIN_RENOTIFY_SECONDS:
                notify_owner(NOTIFY_LOGIN_MSG)
                bring_chrome_front()
                last_notify = now
        if logged_in:
            clear_need_login_flag()
            logger.info("Zhihu login detected.")
            return True, True, relaunched
        logger.error("Zhihu login timed out.")
        return False, True, relaunched

    async def ensure_login(self) -> tuple[bool, bool]:
        """Ensure logged in; returns ``(logged_in, login_was_needed)``.

        Headless-first: cheap creator-page check, auto-fallback to headed
        with owner notification + NEED_LOGIN flag + 20-min wait.
        Never raises for a timeout — returns ``(False, True)`` instead.
        """
        logged_in, needed, _ = await self.ensure_login_headless_first()
        return logged_in, needed

    async def detect_captcha(self) -> bool:  # pragma: no cover - needs real browser
        """Best-effort captcha/verification detection. Never solves anything."""
        try:
            for sel in CAPTCHA_SELECTORS:
                try:
                    el = await self.page.query_selector(sel)
                    if el is not None and await el.is_visible():
                        return True
                except Exception:  # noqa: BLE001, S112
                    continue
            try:
                body = (await self.page.content())[:200000]
            except Exception:  # noqa: BLE001
                return False
            return any(t in body for t in CAPTCHA_TEXTS)
        except Exception:  # noqa: BLE001
            return False

    async def wait_captcha_if_present(self) -> bool:
        """If a captcha is showing, notify + wait up to 20 min for manual solve.

        Headless-first: when verification appears while headless, the headless
        context is closed and the SAME profile is relaunched headed (visible)
        so the owner can solve it manually. Never solves anything automatically.
        Returns True to continue, False when still blocked (caller reports
        ``BLOCKED: verification``).
        """
        if not await self.detect_captcha():
            return True
        if self.headless:
            logger.info("Verification seen headless — relaunching SAME profile headed.")
            try:
                await self.close_browser()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"headless close before captcha fallback failed: {e}")
            self.headless = False
            try:
                self._fell_back_to_headed = True
            except AttributeError:
                pass
            await self.init_browser()
        notify_owner(NOTIFY_CAPTCHA_MSG)
        bring_chrome_front()
        logger.info("Captcha/verification detected — waiting for manual solve (up to 20 min).")
        deadline = asyncio.get_event_loop().time() + CAPTCHA_WAIT_SECONDS
        last_notify = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(10)
            if not await self.detect_captcha():
                logger.info("Captcha appears solved; continuing.")
                return True
            if asyncio.get_event_loop().time() - last_notify >= LOGIN_RENOTIFY_SECONDS:
                notify_owner(NOTIFY_CAPTCHA_MSG)
                last_notify = asyncio.get_event_loop().time()
        logger.error("Captcha still present after 20 min.")
        return False

    # -- editor helpers --------------------------------------------------- #

    async def _first_visible(self, selectors: list[str], timeout_each_ms: int = 3000):
        last_err: Exception | None = None
        for sel in selectors:
            try:
                el = await self.page.wait_for_selector(sel, timeout=timeout_each_ms, state="visible")
                if el is not None:
                    return el
            except Exception as e:  # noqa: BLE001, PERF203 - try next selector
                last_err = e
                continue
        raise TimeoutError(f"element not found (tried {selectors}): {last_err}")

    async def _human_pause(self, lo: float = 0.4, hi: float = 1.2) -> None:
        await asyncio.sleep(random.uniform(lo, hi))

    async def _type_spans(self, spans: list[dict]) -> None:
        """Type ``spans`` with bold toggled via Ctrl/Cmd+B. Human-paced."""
        mod = "Meta" if "darwin" in os.uname().sysname.lower() or os.name != "nt" else "Control"
        # Simpler heuristic: Playwright accepts "ControlOrMeta".
        for sp in spans:
            text = sp.get("text", "")
            if not text:
                continue
            if sp.get("bold"):
                await self.page.keyboard.press("ControlOrMeta+B")
                await asyncio.sleep(0.15)
            # Chunk long text so a single paste is not one bulk action.
            for idx in range(0, len(text), 60):
                chunk = text[idx : idx + 60]
                await self.page.keyboard.type(chunk, delay=random.randint(12, 35))
                await asyncio.sleep(random.uniform(0.05, 0.2))
            if sp.get("bold"):
                await asyncio.sleep(0.15)
                await self.page.keyboard.press("ControlOrMeta+B")
                await asyncio.sleep(0.15)
        _ = mod  # documented; Playwright handles the platform mapping.

    async def fill_title(self, title: str) -> None:  # pragma: no cover - browser
        el = await self._first_visible(TITLE_SELECTORS, timeout_each_ms=8000)
        await el.click(timeout=10000)
        await asyncio.sleep(0.3)
        try:
            await el.fill("", timeout=5000)
        except Exception:  # noqa: BLE001 - fallback to select-all+delete
            await self.page.keyboard.press("ControlOrMeta+A")
            await self.page.keyboard.press("Backspace")
        await self._human_pause(0.3, 0.7)
        await self.page.keyboard.type(title, delay=random.randint(15, 40))
        await self._human_pause()

    async def _focus_editor(self):  # pragma: no cover - browser
        el = await self._first_visible(EDITOR_SELECTORS, timeout_each_ms=10000)
        await el.click(timeout=10000)
        await asyncio.sleep(0.4)
        return el

    async def _new_paragraph(self) -> None:  # pragma: no cover - browser
        await self.page.keyboard.press("Enter")
        await self._human_pause(0.2, 0.5)

    async def write_heading(self, text: str, spans: list[dict]) -> None:  # pragma: no cover
        await self._new_paragraph()
        # Try Markdown shortcut first ("## text"): many ProseMirror editors
        # convert it to H2 automatically.
        await self.page.keyboard.type("## ", delay=20)
        await self._type_spans(spans or [{"text": text, "bold": False}])
        await self._human_pause(0.3, 0.6)
        # If the editor did not convert, bold the line as graceful fallback.
        try:
            h2_count = await self.page.evaluate(
                "() => document.querySelectorAll('.ProseMirror h2, [contenteditable] h2').length"
            )
            if isinstance(h2_count, int) and h2_count < 1:
                logger.info("heading shortcut not converted; leaving text + bold fallback")
        except Exception:  # noqa: BLE001
            pass

    async def write_paragraph(self, spans: list[dict]) -> None:  # pragma: no cover
        await self._new_paragraph()
        await self._type_spans(spans)

    async def write_quote(self, spans: list[dict]) -> None:  # pragma: no cover
        await self._new_paragraph()
        # Try toolbar quote button; fall back to "> " prefix text.
        quote_clicked = False
        for sel in [
            'button[aria-label*="引用" i]',
            'button[title*="引用" i]',
            'button:has-text("引用")',
            '[data-testid*="quote" i]',
        ]:
            try:
                btn = await self.page.query_selector(sel)
                if btn is not None and await btn.is_visible():
                    await btn.click(timeout=5000)
                    quote_clicked = True
                    break
            except Exception:  # noqa: BLE001, S112
                continue
        if not quote_clicked:
            await self.page.keyboard.type("> ", delay=20)
        await self._type_spans(spans)

    async def wait_for_image_upload_complete(self, expected_min: int = 1, timeout_s: int = 90) -> bool:  # pragma: no cover
        """Wait until every editor image left blob: (safe to save) and no progress.

        Fixes the headless race where the draft was saved while the blue
        uploading progress bar was still visible (image vanished after reload).
        Pre-save success is pic-private (temporary); zhimg (permanent) is only
        verified AFTER reload.
        """
        deadline = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < deadline:
            try:
                state = await self.page.evaluate(
                    """() => {
                        const imgs = Array.from(document.querySelectorAll('[contenteditable] img, [contenteditable="true"] img, .ProseMirror img'));
                        const srcs = imgs.map(i => i.getAttribute('src') || '');
                        const uploadingText = (document.body.innerText || '').includes('上传中')
                            || (document.body.innerText || '').includes('正在上传');
                        const prog = document.querySelectorAll('[role="progressbar"], [class*="Progress" i], [class*="progress" i], [class*="Uploading" i], [class*="uploading" i]').length;
                        return {n: imgs.length, srcs, uploadingText, prog};
                    }"""
                )
            except Exception:  # noqa: BLE001
                await asyncio.sleep(1.0)
                continue
            n = int(state.get("n", 0) or 0)
            srcs = list(state.get("srcs", []) or [])
            uploading = bool(state.get("uploadingText")) or int(state.get("prog", 0) or 0) > 0
            all_done = n >= expected_min and all(is_upload_done_src(s) for s in srcs) if srcs else False
            if all_done and not uploading:
                # Extra settle so Zhihu's server-side draft catches up.
                await asyncio.sleep(2.0)
                return True
            await asyncio.sleep(1.0)
        logger.warning("image upload did not leave blob: state in time")
        return False

    async def write_image(self, image_path: str, caption: str = "") -> bool:  # pragma: no cover
        """Upload one image at the cursor; waits for real CDN finish (max 3 tries)."""
        p = Path(image_path)
        if not p.exists():
            logger.error(f"image missing: {image_path}")
            return False
        for attempt in range(1, 3 + 1):
            try:
                before = 0
                try:
                    before = await self.page.evaluate(
                        "() => document.querySelectorAll('[contenteditable] img, [contenteditable=\"true\"] img, .ProseMirror img').length"
                    )
                    before = int(before or 0)
                except Exception:  # noqa: BLE001
                    before = 0
                await self._new_paragraph()
                # Prefer the hidden file input; else click toolbar image button
                # and use the file chooser.
                uploaded = False
                for sel in IMAGE_INPUT_SELECTORS:
                    try:
                        handle = await self.page.query_selector(sel)
                        if handle is not None:
                            await handle.set_input_files(str(p))
                            uploaded = True
                            break
                    except Exception:  # noqa: BLE001, S112
                        continue
                if not uploaded:
                    for btn_sel in [
                        'button[aria-label*="图片" i]',
                        'button[title*="图片" i]',
                        'button:has-text("图片")',
                        '[data-testid*="image" i]',
                    ]:
                        try:
                            btn = await self.page.query_selector(btn_sel)
                            if btn is not None and await btn.is_visible():
                                async with self.page.expect_file_chooser(timeout=8000) as fc:
                                    await btn.click(timeout=5000)
                                chooser = await fc.value
                                await chooser.set_files(str(p))
                                uploaded = True
                                break
                        except Exception:  # noqa: BLE001, S112
                            continue
                if not uploaded:
                    raise TimeoutError("image upload control not found (tried file inputs + toolbar)")
                # Wait for the new image to appear, then for its CDN finish.
                await self.page.wait_for_function(
                    f"() => document.querySelectorAll('[contenteditable] img, [contenteditable=\"true\"] img, .ProseMirror img').length > {int(before)}",
                    timeout=60000,
                )
                ok = await self.wait_for_image_upload_complete(expected_min=before + 1, timeout_s=90)
                if not ok:
                    raise TimeoutError("upload progress did not finish (no final CDN src)")
                await self._human_pause(0.8, 1.2)
                if caption:
                    await self._new_paragraph()
                    await self.page.keyboard.type(caption, delay=random.randint(12, 30))
                    await self._human_pause(0.3, 0.7)
                return True
            except Exception as e:  # noqa: BLE001
                logger.warning(f"image upload attempt {attempt}/3 failed for {p.name}: {e}")
                await self._human_pause(1.0, 2.0)
        logger.error(f"image upload failed after 3 tries: {p.name}; leaving draft and continuing")
        return False

    async def get_cover_state(self) -> dict:  # pragma: no cover
        """Read current cover state from the publish panel (for verification).

        Pre-save preview is pic-private (upload done); post-reload permanent
        is zhimg. has_cover True for either (not blob:/empty); callers check
        is_final_image_src for post-reload strictness.
        """
        try:
            src = await self.page.evaluate(
                f"() => document.querySelector('{COVER_PREVIEW_SELECTOR}')?.getAttribute('src') || ''"
            )
            src = src or ""
            has = bool(src) and is_upload_done_src(src)
            return {"has_cover": has, "src": src, "final": is_final_image_src(src)}
        except Exception:  # noqa: BLE001
            return {"has_cover": False, "src": "", "final": False}

    async def get_topics_state(self) -> list[str]:  # pragma: no cover
        """Read selected topic chips from the publish panel."""
        try:
            return await self.page.evaluate(
                f"() => Array.from(document.querySelectorAll('{TOPIC_CHIP_SELECTOR}')).map(e => (e.innerText||'').trim()).filter(Boolean)"
            )
        except Exception:  # noqa: BLE001
            return []

    async def get_declaration_state(self) -> str:  # pragma: no cover
        """Read the 创作声明 combobox text (无声明 vs 包含 AI …)."""
        try:
            return await self.page.evaluate(
                """() => {
                    const labels = Array.from(document.querySelectorAll('label'));
                    for (const lb of labels) {
                        if ((lb.innerText||'').includes('创作声明')) {
                            const btn = lb.parentElement?.querySelector('button[role="combobox"]');
                            if (btn) return (btn.innerText||'').trim();
                        }
                    }
                    const all = Array.from(document.querySelectorAll('button[role="combobox"]')).map(b=>(b.innerText||'').trim());
                    const hit = all.find(t => t.includes('声明') || t.includes('AI'));
                    return hit || all.join('|').slice(0,120);
                }"""
            )
        except Exception:  # noqa: BLE001
            return ""

    async def try_cover(self, cover_path: str | None) -> bool:  # pragma: no cover
        """Upload the payload cover via hidden input; verify preview CHANGED (every time)."""
        if not cover_path or not Path(cover_path).exists():
            logger.info("no cover image; skipping cover step")
            return False
        try:
            before = await self.get_cover_state()
            old_src = before.get("src", "") or ""
            loc = self.page.locator(COVER_INPUT_SELECTOR)
            n = await loc.count()
            if n < 1:
                logger.warning("cover input not found (non-fatal)")
                return False
            await loc.first.set_input_files(str(cover_path))
            # Wait for preview to change to a NEW upload-done URL (pic-private
            # pre-save; zhimg permanent only after save+reload).
            deadline = asyncio.get_event_loop().time() + 90
            while asyncio.get_event_loop().time() < deadline:
                st = await self.get_cover_state()
                src = st.get("src", "") or ""
                if src and src != old_src and is_upload_done_src(src):
                    await asyncio.sleep(2.0)
                    # Confirm still present after settle (server-side).
                    st2 = await self.get_cover_state()
                    if st2.get("src") == src:
                        logger.info(f"cover uploaded: {Path(cover_path).name}")
                        return True
                await asyncio.sleep(1.0)
            # If src never changed but a cover exists, it may already be correct;
            # report True only when a cover is present (caller verifies after reload).
            st = await self.get_cover_state()
            if st.get("has_cover"):
                logger.warning("cover src unchanged (already set?); keeping existing")
                return True
            logger.warning("cover preview did not appear in time (non-fatal)")
            return False
        except Exception as e:  # noqa: BLE001
            logger.warning(f"cover step failed (non-fatal): {e}")
            return False

    async def try_topics(self, topics: list[str]) -> dict:  # pragma: no cover
        """Add payload topics via the picker; returns {added, current, missing}.

        Flow per topic (verified in real UI): click 添加话题 → search input
        becomes visible → type → click exact button.css-gfrh4c suggestion.
        Existing chips are kept; duplicates skipped; capped to TOPIC_LIMIT.
        """
        wanted = normalize_topics(topics, TOPIC_LIMIT)
        current = await self.get_topics_state()
        added: list[str] = []
        missing: list[str] = []
        try:
            # At limit (3 chips, add button hidden): remove non-payload chips first
            # so payload topics fit (e.g. ep9 投资策略/回测 → 股票技术分析/量化交易).
            live0 = await self.get_topics_state()
            if len(live0) >= TOPIC_LIMIT:
                for chip in list(live0):
                    if chip not in wanted and len(await self.get_topics_state()) >= TOPIC_LIMIT:
                        try:
                            # Click the X on chips not in payload.
                            removed = await self.page.evaluate(
                                """(wanted) => {
                                    const chips = Array.from(document.querySelectorAll('.css-nut0iz'));
                                    for (const c of chips) {
                                        const name = (c.querySelector('.css-1d3pntc')?.innerText||'').trim();
                                        if (name && !wanted.includes(name)) {
                                            c.querySelector('button')?.click();
                                            return name;
                                        }
                                    }
                                    return '';
                                }""",
                                wanted,
                            )
                            if removed:
                                logger.info(f"removed non-payload topic: {removed}")
                                await asyncio.sleep(1.5)
                            else:
                                break
                        except Exception:  # noqa: BLE001
                            break
            for topic in wanted:
                if topic in current or topic in added:
                    continue
                # Zhihu limit is 3 chips (add button hidden at 3).
                live = await self.get_topics_state()
                if len(live) >= TOPIC_LIMIT:
                    logger.info(f"topic limit reached ({TOPIC_LIMIT}); skipping {topic}")
                    missing.append(topic + " (limit)")
                    continue
                try:
                    # Dismiss any stale dropdown from the previous topic first.
                    try:
                        await self.page.keyboard.press("Escape")
                    except Exception:  # noqa: BLE001
                        pass
                    await asyncio.sleep(0.5)
                    add_btn = self.page.get_by_role("button", name=TOPIC_ADD_BUTTON_NAME)
                    if await add_btn.count() > 0:
                        try:
                            await add_btn.first.scroll_into_view_if_needed(timeout=5000)
                        except Exception:  # noqa: BLE001
                            pass
                        try:
                            await add_btn.first.click(timeout=5000)
                        except Exception:  # noqa: BLE001
                            pass
                        await asyncio.sleep(1.2)
                    box = self.page.locator(TOPIC_SEARCH_INPUT_SELECTOR)
                    try:
                        await box.first.wait_for(state="visible", timeout=8000)
                    except Exception:  # noqa: BLE001
                        logger.warning(f"topic search input not visible for '{topic}'")
                        missing.append(topic)
                        continue
                    await box.first.fill("", timeout=5000)
                    await box.first.type(topic, delay=40)
                    await asyncio.sleep(2.5)
                    sug = self.page.locator(TOPIC_SUGGESTION_SELECTOR)
                    found = False
                    try:
                        cnt = await sug.count()
                        for k in range(min(cnt, 8)):
                            try:
                                txt = (await sug.nth(k).inner_text(timeout=3000) or "").strip()
                            except Exception:  # noqa: BLE001, S112
                                continue
                            if txt == topic:
                                await sug.nth(k).click(timeout=5000)
                                found = True
                                break
                    except Exception:  # noqa: BLE001
                        found = False
                    if not found:
                        # No exact suggestion (e.g. 均线/投资者教育): report, do not guess.
                        logger.warning(f"topic '{topic}' has no exact suggestion; skipping")
                        try:
                            await self.page.keyboard.press("Escape")
                        except Exception:  # noqa: BLE001
                            pass
                        try:
                            await box.first.fill("", timeout=3000)
                        except Exception:  # noqa: BLE001
                            pass
                        missing.append(topic)
                        await asyncio.sleep(1.0)
                        continue
                    await asyncio.sleep(2.0)
                    try:
                        await self.page.keyboard.press("Escape")
                    except Exception:  # noqa: BLE001
                        pass
                    await asyncio.sleep(0.5)
                    live2 = await self.get_topics_state()
                    if topic in live2:
                        added.append(topic)
                    else:
                        missing.append(topic)
                    await self._human_pause(0.4, 0.8)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"topic '{topic}' failed (non-fatal): {e}")
                    missing.append(topic)
                    continue
            final = await self.get_topics_state()
            logger.info(f"topics wanted={wanted} added={added} final={final} missing={missing}")
            return {"added": added, "current": final, "missing": missing, "wanted": wanted}
        except Exception as e:  # noqa: BLE001
            logger.warning(f"topic step failed (non-fatal): {e}")
            return {"added": added, "current": current, "missing": missing, "wanted": wanted}

    async def try_ai_declaration(self, declaration: str = "") -> bool:  # pragma: no cover
        """Set 创作声明 to AI-assisted every time; verify the combobox text."""
        _ = declaration  # body text already carries the sentence; panel badge is mandatory.
        try:
            cur = await self.get_declaration_state()
            if DECL_AI_OPTION_TEXT in (cur or ""):
                logger.info("AI declaration already set")
                return True
            # Click the 创作声明 combobox (ID shifts per load; find by label).
            clicked = False
            try:
                handled = await self.page.evaluate(
                    """() => {
                        const labels = Array.from(document.querySelectorAll('label'));
                        for (const lb of labels) {
                            if ((lb.innerText||'').includes('创作声明')) {
                                const btn = lb.parentElement?.querySelector('button[role="combobox"]');
                                if (btn) { btn.click(); return true; }
                            }
                        }
                        return false;
                    }"""
                )
                clicked = bool(handled)
            except Exception:  # noqa: BLE001
                clicked = False
            if not clicked:
                # Fallback: button containing 无声明.
                try:
                    cand = self.page.get_by_role("button", name=DECL_NONE_TEXT)
                    if await cand.count() > 0:
                        await cand.first.click(timeout=5000)
                        clicked = True
                except Exception:  # noqa: BLE001
                    pass
            if not clicked:
                logger.warning("declaration combobox not found (non-fatal)")
                return False
            await asyncio.sleep(1.5)
            # Dropdown options are plain buttons; click the AI one.
            opt = self.page.get_by_role("button", name=DECL_AI_OPTION_TEXT)
            if await opt.count() < 1:
                # Fallback substring match.
                opt = self.page.locator(f'button:has-text("{DECL_AI_OPTION_TEXT}")')
            if await opt.count() < 1:
                logger.warning("AI declaration option not found (non-fatal)")
                try:
                    await self.page.keyboard.press("Escape")
                except Exception:  # noqa: BLE001
                    pass
                return False
            await opt.first.click(timeout=8000)
            await asyncio.sleep(1.5)
            cur2 = await self.get_declaration_state()
            ok = DECL_AI_OPTION_TEXT in (cur2 or "") or "AI" in (cur2 or "")
            logger.info(f"AI declaration set: {cur2[:60]!r} ok={ok}")
            return bool(ok)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"AI declaration step failed (non-fatal): {e}")
            return False

    async def try_column(self, column: str | None) -> dict:  # pragma: no cover
        """Put the article into the configured column if it exists.

        The write page exposes no 专栏 picker; column membership is verified
        on the public page / profile (专栏0 = missing). Never auto-creates.
        Returns {ok, exists, note}.
        """
        if not column or not str(column).strip():
            return {"ok": False, "exists": False, "note": "no column configured"}
        # No picker on the write page (verified DOM has zero 专栏 nodes);
        # existence is checked via profile (专栏0 means the column is missing).
        logger.info(f"column '{column}': no picker on write page; will verify post-publish (never auto-create)")
        return {"ok": False, "exists": None, "note": "no picker on write page; verify manually"}

    async def save_draft(self) -> str | None:  # pragma: no cover - browser
        """Save as draft; waits for uploads to finish first; returns draft URL."""
        # Never save while an upload progress bar is still visible (race fix).
        try:
            n = await self.page.evaluate(
                "() => document.querySelectorAll('[contenteditable] img, [contenteditable=\"true\"] img, .ProseMirror img').length"
            )
            await self.wait_for_image_upload_complete(expected_min=int(n or 0), timeout_s=60)
        except Exception:  # noqa: BLE001
            pass
        try:
            for sel in SAVE_DRAFT_SELECTORS:
                try:
                    btn = await self.page.query_selector(sel)
                    if btn is not None and await btn.is_visible():
                        await btn.click(timeout=8000)
                        break
                except Exception:  # noqa: BLE001, S112
                    continue
        except Exception as e:  # noqa: BLE001
            logger.warning(f"save-draft click failed, relying on autosave: {e}")
        await self._human_pause(1.5, 2.5)
        try:
            await self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:  # noqa: BLE001
            pass
        # Wait for autosave to assign a /p/<id>/edit URL (new drafts start at /write).
        deadline = asyncio.get_event_loop().time() + 30
        while asyncio.get_event_loop().time() < deadline:
            try:
                url = self.page.url or ""
            except Exception:  # noqa: BLE001
                url = ""
            if "/zhuanlan.zhihu.com/p/" in url and "/edit" in url:
                break
            await asyncio.sleep(1.0)
        await asyncio.sleep(2)
        return self.page.url

    async def verify_draft(self, expected_title: str, blocks: list[dict]) -> DraftCheck:  # pragma: no cover
        issues: list[str] = []
        exp_title = (expected_title or "").strip()
        # Title lives in a textarea/input whose live value is NOT reflected in
        # page.content() HTML serialization — read input_value/inner_text instead.
        title_vals: list[str] = []
        for sel in TITLE_SELECTORS:
            try:
                loc = self.page.locator(sel)
                n = await loc.count()
                for k in range(min(n, 3)):
                    try:
                        v = await loc.nth(k).input_value(timeout=3000)
                        if v and v.strip():
                            title_vals.append(v.strip())
                            continue
                    except Exception:  # noqa: BLE001, S112
                        pass
                    try:
                        t = await loc.nth(k).inner_text(timeout=3000)
                        if t and t.strip():
                            title_vals.append(t.strip())
                    except Exception:  # noqa: BLE001, S112
                        pass
            except Exception:  # noqa: BLE001, S112
                continue
        try:
            body_text_full = await self.page.evaluate("() => document.body.innerText || ''")
        except Exception:  # noqa: BLE001
            body_text_full = ""
        title_match = False
        if exp_title:
            title_match = any((exp_title in v or v in exp_title) for v in title_vals if v)
            if not title_match and exp_title in (body_text_full or ""):
                title_match = True
        if not title_match:
            issues.append(f"title text not found in draft page (title inputs seen: {title_vals[:2]})")
        exp_para = count_text_blocks(blocks)
        try:
            counts = await self.page.evaluate(
                """() => {
                    const ed = document.querySelector('[contenteditable]');
                    const root = ed || document.body;
                    const q = (s) => root.querySelectorAll(s).length;
                    return {
                        p: q('p'), h: q('h1,h2,h3,h4'), quote: q('blockquote'),
                        li: q('li'), fig: q('figure'),
                        img: root.querySelectorAll('img').length,
                        textLen: (root.innerText || '').length,
                    };
                }"""
            )
        except Exception as e:  # noqa: BLE001
            issues.append(f"editor DOM read failed: {e}")
            counts = {}
        found_para = int((counts.get("p", 0) if counts else 0)) + int(counts.get("h", 0) if counts else 0) + int(
            counts.get("quote", 0) if counts else 0
        ) + int(counts.get("li", 0) if counts else 0)
        found_text_len = int(counts.get("textLen", 0) if counts else 0)
        exp_img = sum(1 for b in blocks if b.get("kind") == "image")
        found_img = int(counts.get("img", 0) if counts else 0)
        exp_chars = sum(len(str(b.get("text", "") or "")) for b in blocks if b.get("kind") in ("paragraph", "heading", "quote"))
        exp_chars += sum(len(str(b.get("caption", "") or "")) for b in blocks if b.get("kind") == "image")
        exp_chars += len(exp_title)
        chars_ratio = (found_text_len / exp_chars) if exp_chars else 0.0
        logger.info(
            f"draft verify: blocks p/h/quote/li={found_para} (exp~{exp_para}), "
            f"img={found_img}/{exp_img}, chars={found_text_len}/{exp_chars} ({chars_ratio:.2f}), "
            f"title_match={title_match}"
        )
        # Paragraph structure varies by editor version (p vs div); text length is
        # the primary signal, block count is advisory unless both are way off.
        if exp_para and found_para < max(5, int(exp_para * 0.3)) and chars_ratio < 0.5:
            issues.append(
                f"content looks thin: blocks~{found_para} (expected ~{exp_para}), "
                f"chars {found_text_len}/{exp_chars}"
            )
        elif exp_para and abs(found_para - exp_para) > max(5, exp_para // 2):
            issues.append(
                f"paragraph count differs (expected ~{exp_para}, found ~{found_para}) "
                f"but chars {found_text_len}/{exp_chars} — advisory only"
            )
        if found_img < exp_img:
            issues.append(f"images missing: expected {exp_img}, found {found_img}")
        try:
            editor_text = await self.page.evaluate(
                "() => (document.querySelector('[contenteditable]')||document.body).innerText || ''"
            )
        except Exception:  # noqa: BLE001
            editor_text = ""
        if "**" in editor_text or "![" in editor_text:
            issues.append("raw markdown markers visible in editor (formatting broken?)")
        fatal = [x for x in issues if ("images missing" in x or "content looks thin" in x or "title text not found" in x or "raw markdown" in x)]
        ok = title_match and found_img >= exp_img and not fatal
        return DraftCheck(ok, title_match, exp_para, found_para, exp_img, found_img, issues)

    # -- BasePublisher compat -------------------------------------------- #

    async def check_login_simple(self) -> bool:
        return await self.check_login()

    async def upload(  # type: ignore[override]
        self,
        video_path=None,
        title: str = "",
        description: str | None = None,
        tags: list[str] | None = None,
        **kwargs,
    ) -> PublishResult:
        payload = kwargs.get("payload") or kwargs.get("article_payload")
        if not payload:
            return PublishResult(
                success=False,
                platform=self.platform_name,
                error="Zhihu publisher writes 专栏 articles, not videos: pass payload=<publish_payload.json>.",
            )
        res = await self.publish_article_from_payload(
            payload, mode=kwargs.get("mode", "draft"), **kwargs
        )
        if res.get("status") == "published":
            return PublishResult(
                success=True,
                platform=self.platform_name,
                post_url=res.get("public_url"),
                published_at=datetime.now(),
            )
        if res.get("status") == "draft":
            return PublishResult(
                success=True,
                platform=self.platform_name,
                post_url=res.get("draft_url"),
                error=None,
                published_at=datetime.now(),
            )
        return PublishResult(
            success=False, platform=self.platform_name, error=res.get("error", "unknown")
        )

    # -- full article flow ------------------------------------------------- #

    async def publish_article_from_payload(  # pragma: no cover - browser E2E
        self,
        payload_path: str | Path,
        mode: str = "draft",
        smoke_label: str = "ep9",
        draft_url: str | None = None,
        force: bool = False,
        no_open: bool = False,
        **kwargs,
    ) -> dict:
        """Write the article, save draft, verify, optionally publish.

        Headless-first with the persistent profile: starts headless, does a
        cheap creator-page login check, and only relaunches the SAME profile
        headed (visible) when login/verification is needed — then continues
        automatically. Captchas are never solved.

        When ``draft_url`` is given, the existing draft is reused: no text is
        typed, the draft is simply reloaded, verified and (in publish mode)
        published. This avoids duplicate drafts after a verification-only fix.

        Idempotency: in ``publish`` mode, refuses when ``published.json``
        already holds a URL unless ``force=True``.

        On publish success, ``published.json`` (url + timestamp +
        screenshots) is saved next to the payload.

        Returns a result dict with ``status`` one of ``published`` / ``draft`` /
        ``blocked`` / ``error`` plus urls, screenshots and verification.
        """
        _ = kwargs  # forward-compat (e.g. no_open passed via upload())
        _ = no_open  # `open <url>` is handled by the CLI layer (--no-open).
        data = load_payload(payload_path)
        title, blocks = data["title"], data["blocks"]
        self.smoke_dir.mkdir(parents=True, exist_ok=True)
        self._fell_back_to_headed = False
        self._started_headless = bool(self.headless)

        if mode == "publish":
            refuse, rec = should_refuse_publish(payload_path, force=force)
            if refuse:
                return {
                    "status": "error",
                    "error": (
                        f"already published: {rec.get('url')} "
                        f"(at {rec.get('published_at', '?')}); pass --force to republish"
                    ),
                    "public_url": rec.get("url"),
                    "published_json": str(get_published_path(payload_path)),
                    "title": title,
                }

        await self.init_browser()
        try:
            logged_in, login_needed = await self.ensure_login()
            if not logged_in:
                return {"status": "blocked", "reason": "login", "error": "BLOCKED: login"}
            if not await self.wait_captcha_if_present():
                return {"status": "blocked", "reason": "verification", "error": "BLOCKED: verification"}

            images_ok = 0
            images_total = sum(1 for b in blocks if b.get("kind") == "image")
            if draft_url:
                # Reuse an existing draft (no typing): reload it for verification.
                logger.info(f"reusing existing draft: {draft_url}")
                try:
                    await self.page.goto(draft_url, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(3)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"goto existing draft failed: {e}")
                images_ok = images_total  # counted during verification below
                shot1 = None
            else:
                await self.page.goto(WRITE_URL, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)
                if not await self.wait_captcha_if_present():
                    return {"status": "blocked", "reason": "verification", "error": "BLOCKED: verification"}

                await self.fill_title(title)
                await self._focus_editor()
                for b in blocks:
                    kind = b.get("kind")
                    try:
                        if kind == "heading":
                            await self.write_heading(b.get("text", ""), b.get("spans", []))
                        elif kind == "quote":
                            await self.write_quote(b.get("spans", []))
                        elif kind == "image":
                            base = Path(data["base_dir"])
                            src = b.get("src", "")
                            img_path = src if Path(src).is_absolute() else str((base / src).resolve())
                            ok = await self.write_image(img_path, b.get("caption", ""))
                            images_ok += 1 if ok else 0
                        elif kind == "divider":
                            await self._new_paragraph()
                            await self.page.keyboard.type("---", delay=20)
                        else:
                            await self.write_paragraph(b.get("spans", []))
                    except Exception as e:  # noqa: BLE001
                        logger.warning(f"block write failed ({kind}): {e}")
                    await self._human_pause(0.3, 0.8)
                    if await self.detect_captcha():
                        if not await self.wait_captcha_if_present():
                            return {
                                "status": "blocked",
                                "reason": "verification",
                                "error": "BLOCKED: verification",
                            }

            # Publish-panel settings BEFORE save so they persist + verify after reload.
            # (Cover/topics/AI were previously best-effort after verification — that is
            # why ep9 shipped without them.)
            cover_ok = False
            topics_res: dict = {"added": [], "current": [], "missing": [], "wanted": []}
            ai_ok = False
            col_res: dict = {"ok": False, "exists": None, "note": ""}
            if not draft_url:
                # New draft: body just written; set panel now.
                cover_ok = await self.try_cover(data.get("cover_image"))
                topics_res = await self.try_topics(data.get("topics", []))
                ai_ok = await self.try_ai_declaration(data.get("declaration", ""))
                col_res = await self.try_column(data.get("column"))
            else:
                # Reused draft: still enforce panel settings (idempotent).
                try:
                    cover_ok = await self.try_cover(data.get("cover_image"))
                except Exception:  # noqa: BLE001
                    cover_ok = False
                try:
                    topics_res = await self.try_topics(data.get("topics", []))
                except Exception:  # noqa: BLE001
                    pass
                try:
                    ai_ok = await self.try_ai_declaration(data.get("declaration", ""))
                except Exception:  # noqa: BLE001
                    ai_ok = False
                try:
                    col_res = await self.try_column(data.get("column"))
                except Exception:  # noqa: BLE001
                    pass

            shot_panel = self.smoke_dir / f"{smoke_label}_publish_panel.png"
            try:
                await self.page.screenshot(path=str(shot_panel), full_page=True, timeout=20000)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"panel screenshot failed: {e}")
                shot_panel = None

            reused = draft_url is not None
            if not reused:
                draft_url = await self.save_draft()
                shot1 = self.smoke_dir / f"{smoke_label}_draft_editor.png"
                try:
                    await self.page.screenshot(path=str(shot1), full_page=True, timeout=20000)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"screenshot failed: {e}")
                    shot1 = None
            else:
                # Reused draft: panel changes autosave; give them time + explicit save wait.
                try:
                    await self.page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:  # noqa: BLE001
                    pass
                await asyncio.sleep(3)
                shot1 = self.smoke_dir / f"{smoke_label}_draft_reused.png"
                try:
                    await self.page.screenshot(path=str(shot1), full_page=True, timeout=20000)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"screenshot failed: {e}")
                    shot1 = None

            # Reload the draft and verify body + panel.
            if draft_url:
                try:
                    await self.page.goto(draft_url, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(3)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"reload draft failed: {e}")
            check = await self.verify_draft(title, blocks)
            if reused:
                images_ok = int(check.found_images)
            # Panel verification after reload (cover/topics/AI must survive).
            cover_state = await self.get_cover_state()
            topics_state = await self.get_topics_state()
            decl_state = await self.get_declaration_state()
            # Zhihu draft quirk: AI badge reverts to 无声明 after reload even when
            # set before save (fix2 ep9: public badge persists after publish).
            # Retry once after reload; if still missing but pre-save set succeeded,
            # treat as advisory (re-applied before publish), not fatal.
            if DECL_AI_OPTION_TEXT not in (decl_state or "") and "AI" not in (decl_state or ""):
                if ai_ok:
                    try:
                        await self.try_ai_declaration(data.get("declaration", ""))
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        decl_state = await self.get_declaration_state()
                    except Exception:  # noqa: BLE001
                        pass
            panel_issues: list[str] = []
            if not cover_state.get("has_cover"):
                panel_issues.append("cover missing after reload")
            if ai_after_reload_blocks_publish(decl_state, bool(ai_ok)):
                panel_issues.append(f"AI declaration not set after reload (seen: {(decl_state or '')[:40]!r})")
            elif DECL_AI_OPTION_TEXT not in (decl_state or "") and "AI" not in (decl_state or ""):
                # Advisory only: set before save, lost on reload, re-applied at publish.
                check_issues_advisory = f"AI declaration reset after reload but set before save (seen: {(decl_state or '')[:40]!r}); re-applied before publish (known Zhihu draft quirk)"
                panel_issues.append(check_issues_advisory + " [advisory]")
            wanted = list(topics_res.get("wanted", []) or normalize_topics(data.get("topics", [])))
            exact_missing = [t for t in wanted if t not in (topics_state or [])]
            # Topics without an exact Zhihu suggestion (e.g. 均线/投资者教育) are
            # reported, not fatal; at least one wanted topic must survive.
            if wanted and not any(t in (topics_state or []) for t in wanted):
                panel_issues.append(f"topics missing after reload: wanted={wanted} found={topics_state}")
            check_issues = list(check.issues) + panel_issues
            fatal = [
                x
                for x in check_issues
                if "[advisory]" not in x
                and ("images missing" in x or "content looks thin" in x or "title text not found" in x or "raw markdown" in x or "cover missing" in x or "AI declaration not set" in x)
            ]
            check_ok = check.title_match and check.found_images >= check.expected_images and not fatal
            shot2 = self.smoke_dir / f"{smoke_label}_draft_reloaded.png"
            try:
                await self.page.screenshot(path=str(shot2), full_page=True, timeout=20000)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"screenshot failed: {e}")
                shot2 = None

            result: dict = {
                "status": "draft",
                "mode": mode,
                "title": title,
                "draft_url": draft_url,
                "login_needed": login_needed,
                "headless_started": bool(getattr(self, "_started_headless", True)),
                "headless_used": bool(self.headless and not getattr(self, "_fell_back_to_headed", False)),
                "fallback_to_headed": bool(getattr(self, "_fell_back_to_headed", False)),
                "images_uploaded": f"{images_ok}/{images_total}",
                "cover": {"ok": bool(cover_ok or cover_state.get("has_cover")), "after_reload": cover_state},
                "topics": {
                    "wanted": wanted,
                    "added": topics_res.get("added", []),
                    "current_after_reload": topics_state,
                    "missing": exact_missing,
                },
                "declaration": {"ok": bool(ai_ok), "after_reload": decl_state},
                "column": col_res,
                "verification": {
                    "ok": check_ok,
                    "title_match": check.title_match,
                    "expected_paragraphs": check.expected_paragraphs,
                    "found_paragraphs": check.found_paragraphs,
                    "expected_images": check.expected_images,
                    "found_images": check.found_images,
                    "issues": check_issues,
                },
                "screenshots": [str(s) for s in (shot_panel, shot1, shot2) if s],
            }
            if mode == "draft":
                if not check_ok:
                    result["status"] = "error"
                    result["error"] = f"draft verification failed: {check_issues}"
                return result
            # mode == publish: only continue when verification passes.
            if not check_ok:
                result["status"] = "error"
                result["error"] = f"draft verification failed: {check_issues}"
                return result

            # Re-apply AI declaration right before publish (draft reload loses it;
            # ep9 proved it persists on public page when set here).
            try:
                await self.try_ai_declaration(data.get("declaration", ""))
            except Exception:  # noqa: BLE001
                pass

            # Click publish (max 3 attempts total = initial + 2 retries).
            # Success = URL changed to /p/<id> (not /edit) OR published DOM.
            # After ANY click error we re-check the page before retrying, and
            # we never click publish twice once the article is live (ep2:
            # click timed out as "not enabled" but the page had navigated).
            async def _snapshot_url() -> str:
                try:
                    return self.page.url or ""
                except Exception:  # noqa: BLE001
                    return ""

            async def _find_article_link() -> str | None:
                try:
                    link = await self.page.query_selector('a[href*="/zhuanlan.zhihu.com/p/"]')
                    if link is not None:
                        href = await link.get_attribute("href")
                        if href:
                            abs_url = (
                                href
                                if href.startswith("http")
                                else f"https:{href}"
                                if href.startswith("//")
                                else href
                            )
                            if is_published_article_url(abs_url):
                                return abs_url
                except Exception:  # noqa: BLE001
                    pass
                return None

            async def _recover_public_url() -> str | None:
                url = await _snapshot_url()
                if is_published_article_url(url):
                    return url
                link_url = await _find_article_link()
                if link_url:
                    return link_url
                try:
                    html = (await self.page.content())[:200000]
                except Exception:  # noqa: BLE001
                    html = ""
                if is_published_article_html(html):
                    if link_url:
                        return link_url
                    aid = extract_zhihu_article_id(url)
                    if aid:
                        return f"https://zhuanlan.zhihu.com/p/{aid}"
                return None

            public_url: str | None = None
            last_err: str | None = None
            recovered_after_click_error = False
            for attempt in range(1, 4):
                # Never double-publish: if the page is already live, stop.
                if attempt > 1:
                    try:
                        pre = await _recover_public_url()
                        if pre and is_published_article_url(pre):
                            public_url = pre
                            recovered_after_click_error = True
                            logger.info(f"already published before attempt {attempt}: {pre}; not clicking again")
                            break
                    except Exception:  # noqa: BLE001
                        pass
                try:
                    btn = await self._first_visible(PUBLISH_SELECTORS, timeout_each_ms=8000)
                    await btn.click(timeout=8000)
                    await self._human_pause(1.0, 2.0)
                    # Confirm dialog (column selection etc. if present).
                    try:
                        confirm = await self._first_visible(
                            CONFIRM_PUBLISH_SELECTORS, timeout_each_ms=8000
                        )
                        # Column choice: click the configured column if offered.
                        col = data.get("column")
                        if col:
                            try:
                                col_el = await self.page.query_selector(f'*:has-text("{col}")')
                                if col_el is not None and await col_el.is_visible():
                                    await col_el.click(timeout=5000)
                                    await asyncio.sleep(1.0)
                            except Exception:  # noqa: BLE001, S112
                                pass
                        await confirm.click(timeout=8000)
                    except TimeoutError:
                        logger.info("no confirm dialog; single-click publish assumed")
                    await self.page.wait_for_load_state("networkidle", timeout=20000)
                    await asyncio.sleep(3)
                    got = await _recover_public_url()
                    if got and is_published_article_url(got):
                        public_url = got
                        break
                    cur = await _snapshot_url()
                    last_err = f"no navigation to /p/<id> after click (url={cur[:120]!r})"
                    logger.warning(f"publish attempt {attempt}/3: {last_err}")
                    await self._human_pause(2.0, 3.0)
                except Exception as e:  # noqa: BLE001
                    last_err = str(e)
                    logger.warning(f"publish attempt {attempt}/3 failed: {e}")
                    # After ANY click error, check whether already published.
                    try:
                        await asyncio.sleep(2)
                        got = await _recover_public_url()
                        if got and is_published_article_url(got):
                            public_url = got
                            recovered_after_click_error = True
                            logger.info(f"click raised ({e}) but already published: {got}")
                            break
                    except Exception:  # noqa: BLE001
                        pass
                    await self._human_pause(2.0, 3.0)
            # Final recovery sweep before reporting failure (ep2 timeout-after-nav).
            if not public_url or not is_published_article_url(public_url):
                try:
                    got = await _recover_public_url()
                    if got and is_published_article_url(got):
                        if not public_url:
                            recovered_after_click_error = True
                        public_url = got
                        logger.info(f"recovered public URL on final check: {got}")
                except Exception:  # noqa: BLE001
                    pass
            if not public_url or not is_published_article_url(public_url):
                result["status"] = "error"
                result["error"] = f"publish click failed after 3 tries: {last_err}; draft kept at {draft_url}"
                return result
            if recovered_after_click_error:
                result["recovered_after_click_error"] = True

            shot3 = self.smoke_dir / f"{smoke_label}_published.png"
            try:
                await self.page.screenshot(path=str(shot3), full_page=True, timeout=20000)
                result["screenshots"].append(str(shot3))
            except Exception as e:  # noqa: BLE001
                logger.warning(f"screenshot failed: {e}")
            result["status"] = "published"
            result["public_url"] = public_url
            # Persist published.json next to the payload (url + timestamp + screenshots).
            try:
                record = build_published_record(
                    public_url,
                    screenshots=list(result.get("screenshots", [])),
                    title=title,
                    draft_url=draft_url,
                )
                out_path = save_published_record(payload_path, record)
                result["published_json"] = str(out_path)
                result["published_at"] = record["published_at"]
            except Exception as e:  # noqa: BLE001
                logger.warning(f"save published.json failed: {e}")
            return result
        finally:
            try:
                await self.close_browser()
            except Exception:  # noqa: BLE001
                pass
            # Best-effort: kill only leftover Chrome processes holding OUR profile.
            try:
                cleanup_own_chrome_processes(self.profile_dir)
            except Exception:  # noqa: BLE001
                pass


async def verify_public_logged_out(public_url: str, out_path: str | Path) -> dict:  # pragma: no cover
    """Open the public URL in a fresh non-persistent context (logged-out check)."""
    from playwright.async_api import async_playwright

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pw = await async_playwright().start()
    browser = None
    try:
        import shutil

        kwargs: dict = {"headless": True}
        if shutil.which("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome") or shutil.which(
            "google-chrome"
        ):
            kwargs["channel"] = "chrome"
        browser = await pw.chromium.launch(**kwargs)
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 860}, locale="zh-CN"
        )
        page = await ctx.new_page()
        try:
            resp = await page.goto(public_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)
            status = resp.status if resp else None
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "reason": f"goto failed: {e}"}
        try:
            await page.screenshot(path=str(out_path), full_page=True, timeout=20000)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"logged-out screenshot failed: {e}")
        try:
            text = await page.evaluate("() => document.body.innerText || ''")
        except Exception:  # noqa: BLE001
            text = ""
        if status and 200 <= status < 300 and len(text) > 500:
            return {"ok": True, "status": status, "screenshot": str(out_path)}
        review_hints = ["审核", " reviewing", "待审核", "仅自己可见", "已删除", "404", "不存在"]
        hint = next((h for h in review_hints if h in text), "")
        return {
            "ok": False,
            "status": status,
            "reason": f"review-pending or not public (hint={hint!r}, chars={len(text)})"
            if hint or (status != 200)
            else f"thin page (chars={len(text)})",
            "screenshot": str(out_path),
        }
    finally:
        try:
            if browser is not None:
                await browser.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            await pw.stop()
        except Exception:  # noqa: BLE001
            pass
