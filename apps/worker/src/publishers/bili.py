"""Bilibili (B站) video publisher (Playwright, semi-auto, official web only).

Research: ``docs/bilibili-publishing-research.md`` — the official open API
(``open.bilibili.com``) is NOT open to individuals, and
``bilibili-api-python`` is discontinued (2026-07侵权函). The only viable v1
path is the official web upload page (``member.bilibili.com``) driven by
browser automation, single account, low frequency, human pacing, manual
review gate.

This module mirrors the Zhihu headless publisher
(``video-factory-zhihu`` branch ``feat/zhihu-publisher``):
Playwright persistent profile, headless by default, visible window + Mac
notification when login is needed, idempotent ``published.json``, auto-open
the result URL.

Hard rules (from the smoke task):
- Prefer the official web upload page (member.bilibili.com).
- Use NO third-party credential-stealing tools.
- NEVER extract cookies from the owner's normal browsers. The ONLY login
  state is the Playwright persistent profile at
  ``~/.video-factory/bili-profile`` (user scans QR there when asked).
- If Bilibili shows captcha / risk control / -663 etc: STOP, keep the
  window visible, notify, report exactly what is needed. Never bypass.

Pure payload helpers (``build_bili_*`` / ``normalize_*`` / ``validate_*`` /
``classify_login_state`` / idempotency) are free of Playwright so they can
be unit tested in ``tests/test_bili_payload.py``. Everything
browser-related has explicit timeouts and never blocks forever (except the
bounded owner-login wait, default 10 min per the smoke task).
"""

from __future__ import annotations

import asyncio
import json
import logging
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

DEFAULT_PROFILE_DIR = Path.home() / ".video-factory" / "bili-profile"
# Task: screenshots go into .opencode-runs/bili/.
DEFAULT_SMOKE_DIR = Path.home() / "Projects" / "video-factory" / ".opencode-runs" / "bili"
NEED_LOGIN_FILE = DEFAULT_SMOKE_DIR / "NEED_LOGIN"
PUBLISHED_FILENAME = "published.json"

LOGIN_URL = "https://passport.bilibili.com/login"
HOME_URL = "https://member.bilibili.com/platform/home"
UPLOAD_URLS = [
    "https://member.bilibili.com/platform/upload/video/frame",
    "https://member.bilibili.com/video/upload.html",
]
UPLOAD_URL = UPLOAD_URLS[0]
DRAFT_URL = "https://member.bilibili.com/platform/upload-manager/draft"

LOGIN_POLL_SECONDS = 10 * 60  # 10 minutes max (smoke task)
LOGIN_RENOTIFY_SECONDS = 3 * 60  # re-notify every 3 minutes
CAPTCHA_WAIT_SECONDS = 10 * 60

NOTIFY_TITLE = "Video Factory B站发布"
NOTIFY_LOGIN_MSG = "B站需要扫码登录"
NOTIFY_CAPTCHA_MSG = "B站出现验证码/风控验证，请在浏览器里手动完成"

# Partition: 知识 > 财经商业 (research §3: tid=207, main 36).
BILI_TID = 207
BILI_PARTITION_NAME = "知识-财经商业"
BILI_PARTITION_SUB = "财经商业"

PRESENTER_NAME = "躺平的老黄"
FINANCE_DISCLAIMER = (
    "本视频为投资者教育，不构成投资建议，"
    "历史回测不代表未来表现。投资有风险，入市需谨慎。"
)
AI_SENTENCE = "本视频文案由 AI 辅助生成，已按平台规范声明。"
AI_SENTENCE_SHORT = "本视频文案由 AI 辅助生成"

# Up to 10 tags for Bilibili (research §3).
BILI_TAG_LIMIT = 10
BILI_TAG_MAX_LEN = 20
BILI_TITLE_MAX_LEN = 80

TITLE_SELECTORS = [
    'input[placeholder="请输入稿件标题"]',
    'input[placeholder*="标题"]',
    'input[maxlength="80"]',
    ".video-title input",
    ".title-input input",
    '[class*="title"] input',
]
# 简介 is a Quill rich editor (div.ql-editor), NOT a textarea (verified
# 2026-09-27: .ql-editor[data-placeholder*="填写更全面"] is the 简介 field;
# the second .ql-editor is the 动态描述). Textarea selectors never match.
DESC_SELECTORS = [
    '.ql-editor[data-placeholder*="填写更全面"]',
    ".ql-editor",
    'textarea[placeholder*="简介"]',
    'textarea[placeholder*="描述"]',
    ".video-desc textarea",
    ".desc-input textarea",
    '[class*="desc"] textarea',
]
DESC_PLACEHOLDER = "填写更全面的相关信息"
TAG_INPUT_SELECTORS = [
    'input[placeholder="按回车键Enter创建标签"]',
    'input[placeholder*="标签"]',
    ".tag-input input",
    '[class*="tag"] input',
]
# Video file inputs carry extension accepts (".mp4,.flv,..."), never the
# literal "video". The generic `input[type="file"]` fallback MUST NOT be
# used for upload selection: on the form page it matches the video input
# first, which is how the cover PNG became a P2 video part (2026-09-27).
VIDEO_INPUT_SELECTORS = [
    'input[type="file"][accept*=".mp4"]',
    'input[type="file"][accept*="video"]',
    'input[type="file"][accept*="flv"]',
]
# Cover has NO dedicated <input> on the form page. It uploads via the
# 封面 → 添加封面 modal → 上传封面 file-chooser
# (accept="image/png, image/jpeg") → 完成 (crop confirm). There is
# deliberately NO generic fallback here: setting the cover PNG on the
# video input creates a P2 "上传失败" part.
COVER_ACCEPT_HINTS = ("image/png", "image/jpeg", "image/jpg")
COVER_MODAL_TEXTS = ["添加封面", "上传封面", "拖拽图片或点击上传"]
COVER_DONE_TEXTS = ["完成"]
PARTITION_MAIN_WANT = "知识"
PARTITION_SUB_WANT = "财经商业"
DECL_AI_OPTION = "含AI生成内容"
DECL_SELF_OPTION = "内容为自制"
MORE_SETTINGS_TEXT = "更多设置"
BATCH_POPUP_TEXT = "批量上传将生成多条动态"
BATCH_DISMISS_TEXTS = ["暂不设置", "暂不", "知道了", "关闭"]
PUBLISH_BUTTON_TEXTS = ["立即投稿", "投稿", "发布", "提交", "上传"]
# Click candidates only (exact texts). Bare 发布/提交/上传 are excluded:
# get_by_role substring matching would otherwise hit 上传视频/上传字幕 etc.
PUBLISH_CLICK_TEXTS = ["立即投稿", "投稿"]
# Success page / post-click body markers. First entry is the canonical
# post-submit page title per task (稿件投递成功); others are legacy/fallback.
PUBLISH_SUCCESS_TEXTS = ["稿件投递成功", "投稿成功", "发布成功", "审核中", "转码中", "审核", "转码"]
DRAFT_BUTTON_TEXTS = ["存草稿", "保存草稿", "保存"]
ORIGINAL_TEXTS = ["自制", "原创", "自制声明"]
AI_DECL_TEXTS = ["AI", "人工智能", "创作声明", "AI合成", "AI 生成", "合成技术"]
CAPTCHA_TEXTS = [
    "验证码",
    "安全验证",
    "滑动",
    "点击图中",
    "请完成验证",
    "拖动滑块",
    "风控",
    "风险",
    "鉴权失败",
    "-663",
    " abnormal",
    "异常",
]
# Strict visible-text signals for verification (high precision).
# Excludes generics that false-positive on normal pages (verified 2026-09-27):
# - "滑动"/"风险"/"异常"/" abnormal" appear in normal UI or in our own
#   finance disclaimer ("投资有风险");
# - bare "-663" appears in SVG coords (translate(-663,...)) and JS bundles;
#   it only counts with risk context (see _has_risk_code_with_context).
# - "risk"/"captcha"/"geetest" substrings appear in CSS/JS
#   (.risk-captcha-adapt-pc on <body>, geetest_panel CSS) on every
#   member.bilibili.com page, logged in or not.
VISIBLE_CAPTCHA_TEXTS = [
    "验证码",
    "安全验证",
    "点击图中",
    "请完成验证",
    "拖动滑块",
    "风控",
    "鉴权失败",
    "存在异常",
]
# "-663" (Bilibili auth error) only counts as verification together with one
# of these in the SAME visible text (avoids SVG translate(-663,...) FP).
RISK_CODE_CONTEXT_WORDS = ["鉴权", "风控", "验证", "异常", "安全", "风险", "失败"]
CAPTCHA_SELECTORS = [
    '[id*="captcha" i]',
    '[class*="captcha" i]',
    '[class*="Captcha"]',
    '[class*="yidun"]',
    '[class*="NECaptcha"]',
    '[class*="verify" i][class*="slide" i]',
    '[class*="geetest"]',
    '[class*="risk"]',
    'iframe[src*="captcha" i]',
    'iframe[src*="verify" i]',
]
# Tags that can never by themselves prove a captcha: the adapt class
# `risk-captcha-adapt(-pc)` lives on <body> on every normal member page.
CAPTCHA_ROOT_TAGS = {"BODY", "HTML"}
LOGGED_IN_SELECTORS = [
    '[class*="user-name"]',
    '[class*="username"]',
    ".user-face img",
    '[class*="user-face"] img',
    ".header-avatar img",
    '[class*="header-avatar"] img',
    ".avatar img",
    '[class*="member-name"]',
]
# NOTE: the bare 「投稿」 button and generic avatar placeholder
# (header-avatar-unlogin-wrap) exist on www.bilibili.com even when logged
# out, so they must NEVER count as logged-in by themselves (verified
# 2026-09-27: fresh profile shows 3 avatar els + 登录 + 投稿, no username).
LOGGED_OUT_PATTERNS = ["passport.bilibili.com", "/login"]

URL_RE = re.compile(r"https?://[^\s\u4e00-\u9fff\"'<>]+", re.IGNORECASE)
BVID_RE = re.compile(r"(BV[a-zA-Z0-9]{10})")


def extract_bvid(text_or_url: str) -> str | None:
    """Extract the first BV id from a URL or body text. Pure."""
    if not text_or_url:
        return None
    m = BVID_RE.search(text_or_url)
    return m.group(1) if m else None


def is_publish_button_text(text: str) -> bool:
    """Exact publish-button text match (stripped). Pure.

    ``立即投稿`` is tried first by callers; bare ``投稿`` also counts but
    must be deprioritised (sidebar nav uses the same word).
    """
    return (text or "").strip() in PUBLISH_BUTTON_TEXTS


def is_publish_success_body(body: str) -> bool:
    """True when post-click body shows a success/review marker. Pure."""
    if not body:
        return False
    return any(k in body for k in PUBLISH_SUCCESS_TEXTS)


# --------------------------------------------------------------------------- #
# Pure payload helpers (unit-testable, no browser)
# --------------------------------------------------------------------------- #


def strip_external_links(text: str) -> str:
    """Remove http(s) URLs (Bilibili description must carry no external links)."""
    return URL_RE.sub("", text or "").strip()


def contains_external_link(text: str) -> bool:
    return bool(URL_RE.search(text or ""))


def normalize_bili_tags(tags: list[str], limit: int = BILI_TAG_LIMIT) -> list[str]:
    """Dedupe + strip tags, capped to Bilibili limit (pure, unit-testable)."""
    seen: list[str] = []
    for t in tags or []:
        s = str(t or "").strip().lstrip("#").strip()
        if not s or s in seen:
            continue
        if len(s) > BILI_TAG_MAX_LEN:
            s = s[:BILI_TAG_MAX_LEN]
        seen.append(s)
        if len(seen) >= limit:
            break
    return seen


def validate_bili_title(title: str) -> list[str]:
    """Return a list of issues (empty = ok). Pure."""
    issues: list[str] = []
    t = (title or "").strip()
    if not t:
        issues.append("title is empty")
        return issues
    if len(t) > BILI_TITLE_MAX_LEN:
        issues.append(f"title too long: {len(t)} > {BILI_TITLE_MAX_LEN}")
    return issues


def build_bili_description(
    yt_description: str = "",
    *,
    ai_declared_on_panel: bool = True,
    music_credit: str | None = None,
) -> str:
    """Build the Bilibili description from the YouTube description.

    - Strips external links (Bilibili rule for this smoke test).
    - Keeps the data/method + key-numbers body.
    - Ensures the AI-content sentence is present when the panel switch is
      NOT available (task: turn the switch ON if offered, else state the
      sentence in the description).
    - Always appends the finance disclaimer + presenter branding.
    - Appends the calm-track ``music_credit`` (CC BY) when provided.
    - Never includes a real name (only ``躺平的老黄``).
    """
    body = strip_external_links(yt_description or "")
    # Collapse 3+ blank lines to 2.
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    parts: list[str] = [body] if body else []
    if not ai_declared_on_panel:
        if AI_SENTENCE_SHORT not in body:
            parts.append(AI_SENTENCE)
    else:
        # Even with the panel switch ON, keep one short AI sentence so the
        # description matches reality (research §4.6: 文案/配音 AI 辅助).
        if AI_SENTENCE_SHORT not in body and "AI" not in body:
            parts.append(AI_SENTENCE_SHORT + "。")
    if FINANCE_DISCLAIMER not in body:
        parts.append(FINANCE_DISCLAIMER)
    branding = f"主讲：{PRESENTER_NAME}"
    if PRESENTER_NAME not in body:
        parts.append(branding)
    credit = (music_credit or "").strip()
    # Bilibili strips links, so keep only the link-free credit text.
    if credit:
        credit_nolink = strip_external_links(credit).strip() or credit.strip()
        if credit_nolink and credit_nolink not in body and credit_nolink not in "\n\n".join(parts):
            parts.append(credit_nolink)
    # Bilibili web accepts long descriptions; keep a sane cap (~2000 chars).
    text = "\n\n".join(p for p in parts if p and p.strip())
    if len(text) > 2000:
        text = text[:1990].rstrip() + "…"
    return text


def build_bili_payload_from_yt(
    yt_meta: dict,
    *,
    video_path: str,
    cover_path: str,
    tid: int = BILI_TID,
    copyright: int = 1,
    music_credit: str | None = None,
) -> dict:
    """Build a Bilibili payload dict from a YouTube ``ep/yt/ep<N>.json`` meta.

    Pure (no browser, no file reads beyond the passed meta dict).
    ``music_credit`` appends the calm-track CC BY line when provided.
    """
    title = str(yt_meta.get("title") or "").strip()
    yt_desc = str(yt_meta.get("description") or "")
    yt_tags = list(yt_meta.get("tags") or [])
    # Prefer finance-relevant tags first, keep ≤10.
    preferred = [
        "MACD",
        "MACD金叉",
        "技术指标",
        "技术分析",
        "A股",
        "回测",
        "量化",
        "投资者教育",
        "趋势跟踪",
        "躺平的老黄",
    ]
    ordered: list[str] = []
    for t in preferred:
        if t in yt_tags and t not in ordered:
            ordered.append(t)
    for t in yt_tags:
        if t not in ordered:
            ordered.append(t)
    # Map overly-YouTube tags to Bilibili-friendly ones (keep meaning).
    mapped: list[str] = []
    for t in ordered:
        s = str(t).strip()
        if s == "股票":
            s = "股票入门"
        if s == "散户":
            s = "散户必看"
        if s == "量化回测":
            s = "量化"
        if s not in mapped:
            mapped.append(s)
    tags = normalize_bili_tags(mapped)
    credit = (music_credit or str(yt_meta.get("music_credit") or "")).strip() or None
    description = build_bili_description(yt_desc, ai_declared_on_panel=False, music_credit=credit)
    # Safety: description must not contain links even after mapping.
    description = strip_external_links(description)
    if AI_SENTENCE_SHORT not in description:
        description = (description + "\n\n" + AI_SENTENCE).strip()
    if FINANCE_DISCLAIMER not in description:
        description = (description + "\n\n" + FINANCE_DISCLAIMER).strip()
    return {
        "title": title,
        "description": description,
        "tags": tags,
        "tid": tid,
        "partition": BILI_PARTITION_NAME,
        "copyright": copyright,  # 1 = 自制/原创
        "no_reprint": 1,
        "video_path": video_path,
        "cover_path": cover_path,
        "ai_declaration": True,
        "presenter": PRESENTER_NAME,
    }


def validate_bili_payload(payload: dict) -> list[str]:
    """Validate a Bilibili payload dict. Returns issues (empty = ok). Pure."""
    issues: list[str] = []
    issues.extend(validate_bili_title(str(payload.get("title") or "")))
    desc = str(payload.get("description") or "")
    if not desc.strip():
        issues.append("description is empty")
    if contains_external_link(desc):
        issues.append("description contains external links")
    if FINANCE_DISCLAIMER not in desc:
        issues.append("finance disclaimer missing")
    if AI_SENTENCE_SHORT not in desc and "AI" not in desc:
        issues.append("AI-content sentence missing")
    if PRESENTER_NAME not in desc:
        issues.append("presenter branding missing")
    tags = payload.get("tags") or []
    if not tags:
        issues.append("no tags")
    if len(tags) > BILI_TAG_LIMIT:
        issues.append(f"too many tags: {len(tags)} > {BILI_TAG_LIMIT}")
    if payload.get("tid") != BILI_TID:
        issues.append(f"unexpected tid: {payload.get('tid')} (want {BILI_TID})")
    if int(payload.get("copyright", 0)) != 1:
        issues.append("copyright must be 1 (自制)")
    if not str(payload.get("video_path") or "").strip():
        issues.append("video_path missing")
    if not str(payload.get("cover_path") or "").strip():
        issues.append("cover_path missing")
    return issues


def description_verify_markers(
    expected_description: str, expected_title: str = ""
) -> list[str]:
    """Episode-agnostic draft description markers (pure, no browser).

    Series-wide minimum (always present in every episode description):
    ``FINANCE_DISCLAIMER[:12]``, ``AI_SENTENCE_SHORT[:8]``,
    ``PRESENTER_NAME``.

    Plus 1-3 payload-derived markers so ep2+ (e.g. KDJ) no longer fails on
    hardcoded ep1 strings (``MACD金叉`` / ``260,436`` / ``31.8%``):

    - title head (text before ``｜`` / ``，`` etc., e.g. ``MACD金叉``) when
      it is 2-10 chars and appears verbatim in the description;
    - else the first uppercase indicator token from the title (e.g. ``KDJ``,
      ``MACD``) that appears in the description, falling back to the first
      ``[A-Z]{2,}`` token in the description itself;
    - first comma-grouped number in the description (e.g. ``260,436`` /
      ``199,076``);
    - first decimal percent in the description (e.g. ``31.8%`` / ``49.6%``).

    Every derived marker is guaranteed to be a substring of
    ``expected_description``, so a correctly filled form always passes, and
    ep1-style descriptions still pass (regression-safe).
    """
    base = [FINANCE_DISCLAIMER[:12], AI_SENTENCE_SHORT[:8], PRESENTER_NAME]
    desc = expected_description or ""
    title = expected_title or ""
    derived: list[str] = []

    def _add(marker: str) -> None:
        if not marker:
            return
        if marker in derived or marker in base:
            return
        if marker not in desc:
            return
        if len(derived) < 3:
            derived.append(marker)

    # 1) Title head, e.g. "MACD金叉" from "MACD金叉，真的能赚钱吗？｜...".
    head = (title.split("｜")[0] if title else "")
    head = re.split(r"[，,？?。！!、]", head)[0].strip() if head else ""
    if head and 2 <= len(head) <= 10 and head in desc:
        _add(head)
    else:
        # Uppercase indicator token from title (KDJ/MACD/...) present in desc.
        added_indicator = False
        for tok in re.findall(r"[A-Z]{2,}", title or ""):
            if tok in desc:
                _add(tok)
                added_indicator = bool(tok in derived)
                break
        if not added_indicator:
            # Fallback: first uppercase token in the description itself.
            for tok in re.findall(r"[A-Z]{2,}", desc or ""):
                if len(tok) >= 2 and tok not in ("ST",):
                    _add(tok)
                    break

    # 2) Distinctive comma number, e.g. 260,436 / 199,076.
    comma_m = re.search(r"\d{1,3}(?:,\d{3})+", desc or "")
    if comma_m:
        _add(comma_m.group(0))

    # 3) Distinctive decimal percent, e.g. 31.8% / 49.6%.
    # Prefer the first percent AFTER the comma number (the 胜率 on the
    # 交易…笔 line) so we get 31.8%/49.6% instead of the shared 0.30% fee
    # boilerplate that appears earlier in every episode.
    pct: re.Match[str] | None = None
    if comma_m:
        pct = re.search(r"\d+\.\d+%", (desc or "")[comma_m.end():])
    if pct is None:
        pct = re.search(r"\d+\.\d+%", desc or "")
    if pct:
        _add(pct.group(0))

    return base + derived


def ensure_cover_16x9(src: str | Path, dst: str | Path) -> Path:
    """Resize/pad a cover image to 1920x1080 (16:9) for Bilibili.

    Keeps the source aspect by center-fitting on a white canvas (matches the
    fullframe white aesthetic). Output PNG <2MB in practice (~100-300KB).
    """
    from PIL import Image

    src_p = Path(src)
    dst_p = Path(dst)
    dst_p.parent.mkdir(parents=True, exist_ok=True)
    im = Image.open(src_p).convert("RGB")
    target_w, target_h = 1920, 1080
    # contain-fit
    scale = min(target_w / im.width, target_h / im.height)
    new_w = max(1, int(im.width * scale))
    new_h = max(1, int(im.height * scale))
    resized = im.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGB", (target_w, target_h), (255, 255, 255))
    canvas.paste(resized, ((target_w - new_w) // 2, (target_h - new_h) // 2))
    canvas.save(dst_p, format="PNG")
    return dst_p


# --------------------------------------------------------------------------- #
# Pure login-state / risk / idempotency helpers (unit-testable, no browser)
# --------------------------------------------------------------------------- #


def _strip_html_noise(html: str) -> str:
    """Strip scripts/styles/svg + tags so raw-HTML substring checks don't FP.

    Verified 2026-09-27 false positives on normal member pages:
    - ``translate(-663.000000, ...)`` inside inline <svg> (upload page);
    - ``.risk-captcha-adapt-pc`` / ``geetest_panel`` inside <style>;
    - ``geetest``/``risk``/``captcha`` script URLs inside <script>.
    Visible text (innerText) never contains those; stripping restores that.
    """
    if not html:
        return ""
    text = re.sub(r"(?is)<script.*?</script>", " ", html)
    text = re.sub(r"(?is)<style.*?</style>", " ", text)
    text = re.sub(r"(?is)<svg.*?</svg>", " ", text)
    text = re.sub(r"(?is)<!--.*?-->", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _has_risk_code_with_context(text: str) -> bool:
    """``-663`` counts only together with risk words (avoids SVG-coord FP)."""
    if not text or "-663" not in text:
        return False
    return any(w in text for w in RISK_CODE_CONTEXT_WORDS)


def visible_text_has_captcha(text: str) -> bool:
    """Strict visible-text check (use with innerText, not raw HTML).

    Excludes generic ``风险`` (finance disclaimer ``投资有风险``) and bare
    ``-663`` (SVG coords). ``-663`` needs risk context (see above).
    """
    if not text:
        return False
    if any(t in text for t in VISIBLE_CAPTCHA_TEXTS):
        return True
    return _has_risk_code_with_context(text)


def is_verification_url(url: str) -> bool:
    """True only for real risk/captcha pages (not normal member/upload/login)."""
    u = (url or "").lower()
    if not u:
        return False
    return any(
        k in u
        for k in (
            "risk.bilibili.com",
            "captcha",
            "/verify",
            "verify.bilibili",
            "geetest",
            "yidun",
        )
    )


def is_captcha_element(tag: str, visible: bool, bbox: dict | None) -> bool:
    """Pure visible-element gate for CAPTCHA_SELECTORS matches.

    The ``risk-captcha-adapt(-pc)`` class lives on <body> on EVERY normal
    member page (verified 2026-09-27: body bbox = full viewport 1280x860,
    is_visible=True). A bare ``is_visible`` check therefore still
    false-positives. Rules:
    - not visible -> False;
    - BODY/HTML root adapt class -> always False;
    - zero/None bbox -> False (hidden or display:none widget).
    Real captcha widgets (iframe/slider/dialog/panel) are non-root elements
    with a concrete non-full-viewport box; callers additionally require the
    box to be sane (see detect_captcha).
    """
    if not visible:
        return False
    if (tag or "").upper() in CAPTCHA_ROOT_TAGS:
        return False
    if not bbox:
        return False
    try:
        w = float(bbox.get("width") or 0)
        h = float(bbox.get("height") or 0)
    except Exception:  # noqa: BLE001
        return False
    return bool(w > 0 and h > 0)


def is_captcha_html(html: str) -> bool:
    """Strict raw-HTML check: strip scripts/styles/svg, then strict texts.

    Keeps legacy true-positives (``请完成验证码`` etc.) while fixing:
    - SVG ``translate(-663,...)`` FP; - CSS ``risk-captcha-adapt`` FP;
    - finance ``投资有风险`` FP (``风险`` alone no longer counts).
    """
    if not html:
        return False
    text = _strip_html_noise(html)
    return visible_text_has_captcha(text)


def is_risk_html(html: str) -> bool:
    """True for Bilibili risk-control / anti-automation pages (strict)."""
    if not html:
        return False
    text = _strip_html_noise(html)
    return visible_text_has_captcha(text)


def classify_login_state(url: str, html: str) -> str:
    """Classify a Bilibili page as logged_in / logged_out / verification / unknown.

    Pure helper so login-state detection is unit-testable without a browser.
    Verification now requires a STRICT signal: a real risk URL or strict
    visible-text markers on de-noised HTML (never bare ``-663``/``风险``/
    CSS-class substrings). Never bypass a real captcha.
    """
    u = (url or "").lower()
    h = html or ""
    if is_verification_url(url):
        return "verification"
    if is_captcha_html(h) or is_risk_html(h):
        return "verification"
    for pat in LOGGED_OUT_PATTERNS:
        if pat in u:
            return "logged_out"
    if "SignFlow" in h and "avatar" not in h.lower():
        return "logged_out"
    if "登录" in h and ("扫码" in h or "passport" in h.lower()) and "avatar" not in h.lower():
        return "logged_out"
    # Avatar/username is required for logged_in. The bare 「投稿」 button and
    # generic avatar placeholder (header-avatar-unlogin) appear on public
    # pages even when logged out, so they must not count alone (verified
    # 2026-09-27: fresh profile homepage has avatar+投稿+登录, no username).
    # Logged-in markers: user-name/username/user-face img/member-name/退出.
    hl = h.lower()
    has_user = (
        "user-name" in hl
        or "username" in hl
        or "user-face" in hl
        or "member-name" in hl
        or "退出" in h
    )
    # Generic avatar img (logged-in avatar has <img>, placeholder does not).
    has_avatar_img = ("avatar" in hl and "<img" in hl and "unlogin" not in hl)
    has_avatar = bool(has_user or has_avatar_img)
    if has_avatar:
        return "logged_in"
    if "创作中心" in h and has_avatar:
        return "logged_in"
    if "登录" in h:
        # Logged-out homepage shows 登录 without username.
        return "logged_out" if not has_avatar else "unknown"
    return "unknown"


def is_logged_in_state(url: str, html: str) -> bool:
    return classify_login_state(url, html) == "logged_in"


def get_published_path(payload_path: str | Path) -> Path:
    return Path(payload_path).resolve().parent / PUBLISHED_FILENAME


def load_published_record(payload_path: str | Path) -> dict | None:
    try:
        p = get_published_path(payload_path)
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001 - best-effort
        return None


def is_already_published(payload_path: str | Path) -> tuple[bool, dict | None]:
    rec = load_published_record(payload_path)
    if rec and str(rec.get("url") or "").strip().startswith("http"):
        return True, rec
    # BV id alone also counts.
    if rec and str(rec.get("bvid") or "").strip().startswith("BV"):
        return True, rec
    return False, rec


def should_refuse_publish(payload_path: str | Path, force: bool = False) -> tuple[bool, dict | None]:
    if force:
        return False, load_published_record(payload_path)
    return is_already_published(payload_path)


def build_published_record(
    url: str,
    screenshots: list[str] | None = None,
    title: str = "",
    bvid: str | None = None,
    status: str = "",
) -> dict:
    return {
        "url": url,
        "bvid": bvid or "",
        "status": status or "",
        "published_at": datetime.now().isoformat(timespec="seconds"),
        "title": title,
        "screenshots": list(screenshots or []),
    }


def save_published_record(payload_path: str | Path, record: dict) -> Path:
    out = get_published_path(payload_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def load_payload(payload_path: str | Path) -> dict:
    """Load a bili ``publish_payload.json`` (paths resolved to absolute)."""
    p = Path(payload_path).resolve()
    data = json.loads(p.read_text(encoding="utf-8"))
    base = p.parent
    video = data.get("video_path") or data.get("video")
    cover = data.get("cover_path") or data.get("cover")
    video_path = str((base / video).resolve()) if video and not Path(video).is_absolute() else str(video or "")
    cover_path = str((base / cover).resolve()) if cover and not Path(cover).is_absolute() else str(cover or "")
    return {
        "payload_path": str(p),
        "base_dir": str(base),
        "title": str(data.get("title") or "").strip(),
        "description": str(data.get("description") or ""),
        "tags": list(data.get("tags") or []),
        "tid": int(data.get("tid") or BILI_TID),
        "partition": str(data.get("partition") or BILI_PARTITION_NAME),
        "copyright": int(data.get("copyright", 1)),
        "video_path": video_path,
        "cover_path": cover_path,
        "ai_declaration": bool(data.get("ai_declaration", True)),
        "raw": data,
    }


def open_url_in_browser(url: str) -> bool:
    try:
        subprocess.run(["open", url], timeout=15, check=False)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"open_url_in_browser failed: {e}")
        return False


def cleanup_own_chrome_processes(profile_dir: str | Path) -> int:
    """Kill leftover Chrome processes holding OUR profile dir only."""
    try:
        needle = str(profile_dir)
        ps = subprocess.run(["ps", "aux"], capture_output=True, text=True, timeout=10, check=False)
        killed = 0
        for line in (ps.stdout or "").splitlines():
            if needle in line and ("chrome" in line.lower() or "chromium" in line.lower()):
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    pid = parts[1]
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
    except Exception as e:  # noqa: BLE001
        logger.warning(f"notify_owner failed: {e}")


def bring_chrome_front() -> None:
    try:
        subprocess.run(
            ["osascript", "-e", 'tell application "Google Chrome" to activate'],
            timeout=10,
            check=False,
            capture_output=True,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"bring_chrome_front failed: {e}")


def write_need_login_flag() -> None:
    try:
        NEED_LOGIN_FILE.parent.mkdir(parents=True, exist_ok=True)
        NEED_LOGIN_FILE.write_text("B站需要扫码登录 (Video Factory bili publisher).\n", encoding="utf-8")
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
    upload_done: bool
    issues: list[str] = field(default_factory=list)


class BiliPublisher(BasePublisher):
    """Bilibili video publisher with a persistent Chromium profile (headless-first)."""

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
        return "Bilibili"

    @property
    def login_url(self) -> str:
        return LOGIN_URL

    @property
    def upload_url(self) -> str:
        return UPLOAD_URL

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

    async def _page_state(self) -> tuple[str, str, str]:  # pragma: no cover
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
        for check_url in (HOME_URL, "https://www.bilibili.com/"):
            try:
                await self.page.goto(check_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)
                for sel in LOGGED_IN_SELECTORS:
                    try:
                        el = await self.page.query_selector(sel)
                        if el is not None:
                            return True
                    except Exception:  # noqa: BLE001, S112
                        continue
                url, html, _ = await self._page_state()
                if is_logged_in_state(url, html):
                    return True
                if classify_login_state(url, html) == "logged_in":
                    return True
                if classify_login_state(url, html) == "verification":
                    return False
            except Exception as e:  # noqa: BLE001
                logger.warning(f"check_login via {check_url} failed: {e}")
                continue
        try:
            url = (self.page.url or "").lower()
            if "passport.bilibili.com" in url:
                return False
        except Exception:  # noqa: BLE001
            pass
        return False

    async def ensure_login_headless_first(self) -> tuple[bool, bool, bool]:  # pragma: no cover
        if await self.check_login():
            return True, False, False
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
        try:
            await self.page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"goto login page failed: {e}")
        bring_chrome_front()
        notify_owner(NOTIFY_LOGIN_MSG)
        write_need_login_flag()
        logger.info("Bilibili login required — waiting for owner to scan QR (up to 10 min).")
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
            now = asyncio.get_event_loop().time()
            if now - last_notify >= LOGIN_RENOTIFY_SECONDS:
                notify_owner(NOTIFY_LOGIN_MSG)
                bring_chrome_front()
                last_notify = now
        if logged_in:
            clear_need_login_flag()
            logger.info("Bilibili login detected.")
            return True, True, relaunched
        logger.error("Bilibili login timed out.")
        return False, True, relaunched

    async def ensure_login(self) -> tuple[bool, bool]:
        logged_in, needed, _ = await self.ensure_login_headless_first()
        return logged_in, needed

    async def detect_captcha(self) -> bool:  # pragma: no cover
        """Visible-element based verification check (no raw-HTML substrings).

        Counts only: a non-root captcha widget that is actually visible with
        a real bounding box, strict visible-text markers, or a real risk URL.
        Never bypass a real captcha: callers BLOCK on True.
        """
        try:
            try:
                viewport = self.page.viewport_size or {"width": 1280, "height": 860}
                vp_area = float(viewport.get("width", 1280) * viewport.get("height", 860))
            except Exception:  # noqa: BLE001
                vp_area = 1280 * 860
            for sel in CAPTCHA_SELECTORS:
                try:
                    els = await self.page.query_selector_all(sel)
                except Exception:  # noqa: BLE001, S112
                    continue
                for el in els[:8]:
                    try:
                        visible = await el.is_visible()
                    except Exception:  # noqa: BLE001
                        continue
                    if not visible:
                        continue
                    try:
                        tag = await el.evaluate("(e) => e.tagName || ''")
                    except Exception:  # noqa: BLE001
                        tag = ""
                    if (tag or "").upper() in CAPTCHA_ROOT_TAGS:
                        # <body class="risk-captcha-adapt..."> on normal pages.
                        continue
                    try:
                        bbox = await el.bounding_box()
                    except Exception:  # noqa: BLE001
                        bbox = None
                    if not is_captcha_element(tag or "", True, bbox):
                        continue
                    try:
                        area = float((bbox or {}).get("width", 0)) * float((bbox or {}).get("height", 0))
                    except Exception:  # noqa: BLE001
                        area = 0
                    # Generic risk/captcha class on a full-viewport container
                    # is the adapt wrapper, not a dialog -> ignore.
                    if vp_area and area >= 0.9 * vp_area and (tag or "").upper() not in ("IFRAME", "CANVAS"):
                        continue
                    return True
            try:
                url = self.page.url or ""
            except Exception:  # noqa: BLE001
                url = ""
            if is_verification_url(url):
                return True
            try:
                visible_text = await self.page.evaluate("() => document.body ? document.body.innerText.slice(0,20000) : ''")
            except Exception:  # noqa: BLE001
                return False
            return visible_text_has_captcha(visible_text or "")
        except Exception:  # noqa: BLE001
            return False

    async def wait_captcha_if_present(self) -> bool:  # pragma: no cover
        """If captcha/risk control shows, notify + keep visible + report BLOCKED.

        Per the smoke task: stop, keep the window visible, notify, report
        exactly what is needed. Never bypass. Returns False when blocked.
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
        logger.error("Captcha/risk control detected — BLOCKED (kept visible, no bypass).")
        return False

    # -- upload helpers --------------------------------------------------- #

    async def _first_visible(self, selectors: list[str], timeout_each_ms: int = 3000):
        last_err: Exception | None = None
        for sel in selectors:
            try:
                el = await self.page.wait_for_selector(sel, timeout=timeout_each_ms, state="visible")
                if el is not None:
                    return el
            except Exception as e:  # noqa: BLE001, PERF203
                last_err = e
                continue
        raise TimeoutError(f"element not found (tried {selectors}): {last_err}")

    async def _human_pause(self, lo: float = 0.4, hi: float = 1.2) -> None:
        await asyncio.sleep(random.uniform(lo, hi))

    async def dismiss_unsubmitted_interstitial(self) -> bool:  # pragma: no cover
        """Clear stale local drafts ("本地浏览器存在N个未提交的视频").

        Clicks 不用了 to start fresh with a single part. Returns True when
        the interstitial was present (or nothing to do).
        """
        try:
            btn = self.page.get_by_text("不用了", exact=True)
            if await btn.count() > 0:
                try:
                    if await btn.first.is_visible():
                        await btn.first.click(timeout=5000)
                        await asyncio.sleep(3.0)
                        logger.info("dismissed unsubmitted-videos interstitial (不用了)")
                        return True
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"不用了 click failed: {e}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"dismiss_unsubmitted check failed: {e}")
        return True

    async def dismiss_batch_popup(self) -> bool:  # pragma: no cover
        """Dismiss 「批量上传将生成多条动态」 and similar overlays.

        Clicks 暂不设置 when the batch-upload dialog is visible. Must be
        called before filling and before screenshots.
        """
        try:
            body = await self.page.evaluate("() => document.body.innerText || ''")
        except Exception:  # noqa: BLE001
            body = ""
        if BATCH_POPUP_TEXT not in (body or ""):
            return True
        for name in BATCH_DISMISS_TEXTS:
            try:
                cand = self.page.get_by_text(name, exact=True)
                if await cand.count() > 0:
                    for i in range(await cand.count()):
                        try:
                            if await cand.nth(i).is_visible():
                                await cand.nth(i).click(timeout=4000)
                                await asyncio.sleep(1.0)
                                logger.info(f"dismissed batch popup via {name}")
                                return True
                        except Exception:  # noqa: BLE001, S112
                            continue
            except Exception:  # noqa: BLE001
                continue
        logger.warning("batch popup visible but dismiss button not clicked")
        return False

    async def dismiss_overlays_for_publish(self) -> None:  # pragma: no cover
        """Dismiss anything that can cover the submit bar before clicking.

        - Batch-upload dialog (暂不设置 path).
        - Generic overlay closes (知道了/关闭/暂不/X).
        - Escape to close dropdowns (tag recommend, partition, declaration).
        Best-effort; never raises.
        """
        try:
            await self.dismiss_batch_popup()
        except Exception:  # noqa: BLE001
            pass
        for _ in range(2):
            try:
                await self.page.keyboard.press("Escape")
                await asyncio.sleep(0.4)
            except Exception:  # noqa: BLE001
                break
        # Generic one-shot closes only when an overlay dialog is visible.
        try:
            body = await self.page.evaluate("() => document.body.innerText || ''")
        except Exception:  # noqa: BLE001
            body = ""
        if BATCH_POPUP_TEXT in (body or ""):
            for name in BATCH_DISMISS_TEXTS:
                try:
                    cand = self.page.get_by_text(name, exact=True)
                    if await cand.count() > 0:
                        for i in range(await cand.count()):
                            try:
                                if await cand.nth(i).is_visible():
                                    await cand.nth(i).click(timeout=3000)
                                    await asyncio.sleep(1.0)
                                    break
                            except Exception:  # noqa: BLE001, S112
                                continue
                        break
                except Exception:  # noqa: BLE001
                    continue

    async def _scroll_submit_bar_into_view(self) -> None:  # pragma: no cover
        """Scroll the sticky footer / submit bar into the viewport."""
        for js in (
            "() => window.scrollTo(0, document.body.scrollHeight)",
            """() => {
                 const els=[...document.querySelectorAll('*')].filter(e=>{
                   const t=((e.innerText||'').trim());
                   return t==='立即投稿'||t==='存草稿';
                 });
                 for(const e of els){
                   try{
                     const r=e.getBoundingClientRect();
                     if(r.width>0&&r.height>0){
                       e.scrollIntoView({block:'center', inline:'center'});
                       return true;
                     }
                   }catch(_){}
                 }
                 return false;
               }""",
        ):
            try:
                await self.page.evaluate(js)
                await asyncio.sleep(0.6)
            except Exception:  # noqa: BLE001
                continue

    async def _click_publish_button_once(self) -> str:  # pragma: no cover
        """Click the publish/submit button once (robust, tag-agnostic).

        Returns the clicked text. Raises TimeoutError when no candidate
        is found. Handles: non-<button> markup (div/a/span), below-the-fold
        sticky footer (scroll-into-view), covering popups (pre-dismiss),
        and iframes (searches all frames). Only exact ``立即投稿`` (then
        bottom-most exact ``投稿``) is ever clicked — generic 发布/提交/
        上传 are never click targets (they substring-match 上传视频/
        上传字幕 etc. and caused a mis-click on 2026-09-28).
        """
        await self.dismiss_overlays_for_publish()
        await self._scroll_submit_bar_into_view()
        # Extra settle: the submit bar enables a beat after fill/verify.
        await asyncio.sleep(1.5)
        errors: list[str] = []
        # 1) Accessible-button role, EXACT name (avoids substring hits like
        # 上传视频/上传字幕 when searching for 上传).
        for text in PUBLISH_CLICK_TEXTS:
            try:
                btn = self.page.get_by_role("button", name=text, exact=True)
                if await btn.count() > 0:
                    for i in range(min(await btn.count(), 4)):
                        try:
                            loc = btn.nth(i)
                            if not await loc.is_visible():
                                continue
                            try:
                                await loc.scroll_into_view_if_needed(timeout=5000)
                                await asyncio.sleep(0.4)
                            except Exception:  # noqa: BLE001
                                pass
                            try:
                                await loc.click(timeout=8000)
                            except Exception:
                                # Force + JS retry for the RIGHT button before
                                # ever falling through to another text.
                                try:
                                    await loc.click(timeout=5000, force=True)
                                except Exception as e2:  # noqa: BLE001
                                    errors.append(f"role:{text}[{i}]:{e2}")
                                    continue
                            logger.info(f"publish clicked via role=button name={text!r}")
                            return text
                        except Exception as e:  # noqa: BLE001
                            errors.append(f"role:{text}[{i}]:{e}")
                            continue
            except Exception as e:  # noqa: BLE001
                errors.append(f"role:{text}:{e}")
                continue
        # 2) <button> exact-text (no substring).
        for text in PUBLISH_CLICK_TEXTS:
            try:
                loc = self.page.locator(f'button:text-is("{text}")')
                if await loc.count() > 0:
                    for i in range(min(await loc.count(), 4)):
                        try:
                            el = loc.nth(i)
                            if not await el.is_visible():
                                continue
                            try:
                                await el.scroll_into_view_if_needed(timeout=5000)
                                await asyncio.sleep(0.4)
                            except Exception:  # noqa: BLE001
                                pass
                            try:
                                await el.click(timeout=8000)
                            except Exception:
                                await el.click(timeout=5000, force=True)
                            logger.info(f"publish clicked via button:text-is {text!r}")
                            return text
                        except Exception as e:  # noqa: BLE001
                            errors.append(f"button-is:{text}[{i}]:{e}")
                            continue
            except Exception as e:  # noqa: BLE001
                errors.append(f"button-is:{text}:{e}")
                continue
        # 3) Tag-agnostic exact text (div/a/span buttons). 立即投稿 first;
        # bare 投稿 last (sidebar nav shares the word — prefer bottom-most).
        for text in PUBLISH_CLICK_TEXTS:
            try:
                cand = self.page.get_by_text(text, exact=True)
                n = await cand.count()
                if n == 0:
                    continue
                # Prefer bottom-most visible (submit bar lives at page bottom).
                order = list(range(min(n, 8)))
                if text == "投稿":
                    try:
                        ys: list[tuple[float, int]] = []
                        for i in order:
                            try:
                                box = await cand.nth(i).bounding_box()
                                ys.append(((box or {}).get("y", 0) or 0, i))
                            except Exception:  # noqa: BLE001
                                ys.append((0, i))
                        order = [i for _, i in sorted(ys, reverse=True)]
                    except Exception:  # noqa: BLE001
                        pass
                for i in order:
                    try:
                        el = cand.nth(i)
                        if not await el.is_visible():
                            continue
                        try:
                            await el.scroll_into_view_if_needed(timeout=5000)
                            await asyncio.sleep(0.4)
                        except Exception:  # noqa: BLE001
                            pass
                        try:
                            await el.click(timeout=8000)
                        except Exception:
                            # One force retry on the RIGHT element.
                            await el.click(timeout=5000, force=True)
                        logger.info(f"publish clicked via text exact {text!r}[{i}]")
                        return text
                    except Exception as e:  # noqa: BLE001
                        errors.append(f"text-exact:{text}[{i}]:{e}")
                        continue
            except Exception as e:  # noqa: BLE001
                errors.append(f"text-exact:{text}:{e}")
                continue
        # 4) JS fallback: click the bottom-most visible exact-text node
        # (covers shadow/role-less markup). 立即投稿 only, then 投稿.
        for text in PUBLISH_CLICK_TEXTS:
            try:
                clicked = await self.page.evaluate(
                    """(want) => {
                      const els=[...document.querySelectorAll('*')].filter(e=>((e.innerText||'').trim())===want);
                      const vis=els.filter(e=>{try{const r=e.getBoundingClientRect();return r.width>0&&r.height>0;}catch(_){return false;}});
                      if(!vis.length) return '';
                      vis.sort((a,b)=>b.getBoundingClientRect().y-a.getBoundingClientRect().y);
                      for(const e of vis.slice(0,3)){
                        try{ e.scrollIntoView({block:'center'}); }catch(_){}
                      }
                      try{ vis[0].click(); return (vis[0].tagName||'')+' clicked'; }catch(err){ return 'ERR:'+err; }
                    }""",
                    text,
                )
                if clicked and not str(clicked).startswith("ERR") and clicked != "":
                    logger.info(f"publish clicked via JS fallback {text!r} ({clicked})")
                    await asyncio.sleep(1.0)
                    return text
            except Exception as e:  # noqa: BLE001
                errors.append(f"js:{text}:{e}")
                continue
        # 5) Frames: same exact-text search inside iframes (rare but cheap).
        try:
            for frame in getattr(self.page, "frames", []) or []:
                try:
                    if frame == self.page.main_frame:
                        continue
                    for text in PUBLISH_CLICK_TEXTS:
                        try:
                            cand = frame.get_by_text(text, exact=True)
                            if await cand.count() > 0 and await cand.first.is_visible():
                                await cand.first.click(timeout=8000)
                                logger.info(f"publish clicked via iframe {text!r}")
                                return text
                        except Exception:  # noqa: BLE001, S112
                            continue
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            pass
        # Diagnostic dump for the next fix iteration (no video re-upload needed
        # to understand the DOM). Best-effort; never masks the original error.
        try:
            diag: dict = {"errors": errors[:12], "url": ""}
            try:
                diag["url"] = self.page.url or ""
            except Exception:  # noqa: BLE001
                pass
            try:
                diag["body_head"] = (await self.page.evaluate("() => document.body.innerText.slice(0,4000)")) or ""
            except Exception as e:  # noqa: BLE001
                diag["body_head"] = f"ERR {e}"
            try:
                diag["counts"] = {}
                for t in ["立即投稿", "投稿", "存草稿"]:
                    try:
                        diag["counts"][t] = {
                            "text_exact": await self.page.get_by_text(t, exact=True).count(),
                            "role_exact": await self.page.get_by_role("button", name=t, exact=True).count(),
                        }
                    except Exception as e:  # noqa: BLE001
                        diag["counts"][t] = {"err": str(e)[:120]}
            except Exception:  # noqa: BLE001
                pass
            try:
                diag["bottom"] = await self.page.evaluate(
                    """() => {
                      const els=[...document.querySelectorAll('button,div,a,span')].map(e=>{
                        try{
                          const r=e.getBoundingClientRect();
                          if(r.width<20||r.height<10) return null;
                          const t=((e.innerText||'').trim()).slice(0,20);
                          if(!t) return null;
                          return {tag:e.tagName, txt:t, y:Math.round(r.y), w:Math.round(r.width), h:Math.round(r.height), cls:(e.className||'').toString().slice(0,80)};
                        }catch(_){return null;}
                      }).filter(x=>x);
                      els.sort((a,b)=>b.y-a.y);
                      return els.slice(0,25);
                    }"""
                )
            except Exception as e:  # noqa: BLE001
                diag["bottom"] = f"ERR {e}"
            try:
                out = self.smoke_dir / "publish_btn_diag.json"
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(diag, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
            try:
                shot = self.smoke_dir / "publish_btn_diag.png"
                await self.page.screenshot(path=str(shot), full_page=True, timeout=20000)
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass
        raise TimeoutError(f"publish button not found ({'; '.join(errors[:6])})")

    async def search_title_in_manager(self, title: str) -> dict:  # pragma: no cover
        """Re-check the manuscript manager for a title (no double-submit).

        Opens a second tab (upload form tab stays intact), searches
        ``article?keyword=<title>``, and reports {found, bvid, status}.
        Best-effort; never raises (returns {found: False} on error).
        """
        import urllib.parse

        out: dict = {"found": False, "bvid": "", "status": ""}
        tab = None
        try:
            q = urllib.parse.quote(title or "")
            url = f"https://member.bilibili.com/platform/upload-manager/article?keyword={q}&page=1"
            try:
                tab = await self.context.new_page()
            except Exception:  # noqa: BLE001
                return out
            try:
                await tab.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(4)
            except Exception as e:  # noqa: BLE001
                out["error"] = str(e)[:200]
                return out
            try:
                body = await tab.evaluate("() => document.body ? document.body.innerText.slice(0,20000) : ''")
            except Exception:  # noqa: BLE001
                body = ""
            if (title or "") and (title in (body or "")):
                out["found"] = True
            elif "一个稿件都没有" in (body or ""):
                out["found"] = False
                return out
            # BV + review status from the manager row when present.
            try:
                html = (await tab.content())[:200000]
            except Exception:  # noqa: BLE001
                html = ""
            bvid = extract_bvid(html or "") or extract_bvid(body or "")
            if bvid:
                out["bvid"] = bvid
            for key in ["审核中", "已通过", "未通过", "进行中", "转码中"]:
                if key in (body or ""):
                    out["status"] = key
                    break
            return out
        except Exception as e:  # noqa: BLE001
            out["error"] = str(e)[:200]
            return out
        finally:
            try:
                if tab is not None:
                    await tab.close()
            except Exception:  # noqa: BLE001
                pass

    async def goto_upload_page(self) -> str:  # pragma: no cover
        last_err: Exception | None = None
        for url in UPLOAD_URLS:
            try:
                await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)
                # Fresh single-part state: discard stale local drafts.
                await self.dismiss_unsubmitted_interstitial()
                return url
            except Exception as e:  # noqa: BLE001
                last_err = e
                continue
        raise TimeoutError(f"upload page unreachable: {last_err}")

    async def _pick_video_input(self):  # pragma: no cover
        """Return the video upload <input> (accept contains .mp4).

        Never returns .txt/.zip/image inputs. The page has 3 file inputs:
        hidden video (.mp4...), visible video (buploader, .mp4...), .txt.
        The hidden first match is the reliable upload target (verified
        2026-09-27: visible buploader input does NOT start the upload).
        """
        handles = await self.page.query_selector_all('input[type="file"]')
        for h in handles:
            try:
                acc = (await h.get_attribute("accept")) or ""
                if ".mp4" in acc:
                    return h
            except Exception:  # noqa: BLE001, S112
                continue
        return None

    async def upload_video_file(self, video_path: str) -> bool:  # pragma: no cover
        p = Path(video_path)
        if not p.exists():
            logger.error(f"video missing: {video_path}")
            return False
        # Strict: ONLY the video accept input. Never the generic fallback
        # (that is how the cover PNG became P2).
        try:
            handle = await self._pick_video_input()
            if handle is not None:
                await handle.set_input_files(str(p))
                logger.info(f"video file set: {p.name}")
                return True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"video set_input_files failed: {e}")
        logger.error("video upload control not found (strict .mp4 accept)")
        return False

    async def wait_for_upload_complete(self, timeout_s: int = 900) -> bool:  # pragma: no cover
        """Wait until the upload progress disappears / form is ready."""
        deadline = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < deadline:
            try:
                text = await self.page.evaluate("() => document.body.innerText || ''")
            except Exception:  # noqa: BLE001
                await asyncio.sleep(2.0)
                continue
            t = text or ""
            # Risk control during upload -> blocked (strict visible-text only;
            # bare "-663"/"风险" would FP on SVG coords / finance disclaimer).
            if visible_text_has_captcha(t[:20000]):
                logger.error("risk control text during upload")
                return False
            uploading = any(
                k in t for k in ["上传中", "正在上传", "排队中", "转码中", "审核中", "%"]
            )
            # Form ready signals: title/desc inputs visible + upload-done text.
            done_hint = any(k in t for k in ["上传完成", "上传成功", "填写信息", "基本信息"])
            if done_hint and not uploading:
                await asyncio.sleep(2.0)
                return True
            # Fallback: if title input is interactable and no progress bar, assume ready.
            try:
                prog = await self.page.evaluate(
                    """() => document.querySelectorAll('[role="progressbar"], [class*="Progress" i], [class*="progress" i]').length"""
                )
                title_ready = await self.page.evaluate(
                    """() => !!document.querySelector('input[placeholder*="标题"]')"""
                )
                if int(prog or 0) == 0 and bool(title_ready):
                    # Extra settle for Bilibili server-side.
                    await asyncio.sleep(3.0)
                    return True
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(3.0)
        logger.warning("upload did not complete in time")
        return False

    async def fill_title(self, title: str) -> bool:  # pragma: no cover
        wanted = (title or "")[:BILI_TITLE_MAX_LEN]
        try:
            loc = self.page.locator('input[placeholder="请输入稿件标题"]').first
            await loc.wait_for(state="visible", timeout=10000)
            # fill() is reliable for CJK + ｜ (keyboard.type drops chars).
            await loc.fill(wanted, timeout=10000)
            await self._human_pause(0.5, 1.0)
            try:
                got = await loc.input_value(timeout=5000)
            except Exception:  # noqa: BLE001
                got = ""
            if got.strip() != wanted.strip():
                logger.warning(f"fill_title mismatch: got={got[:30]!r} want={wanted[:30]!r}")
                return False
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"fill_title failed: {e}")
            return False

    async def _first_visible_ql_editor(self):  # pragma: no cover
        """Return the first visible .ql-editor (简介 is the first one)."""
        try:
            locs = self.page.locator(".ql-editor")
            n = await locs.count()
            for i in range(n):
                try:
                    el = locs.nth(i)
                    if await el.is_visible():
                        box = await el.bounding_box()
                        if box and box["width"] > 0 and box["height"] > 0:
                            return el
                except Exception:  # noqa: BLE001, S112
                    continue
        except Exception as e:  # noqa: BLE001
            logger.warning(f"ql-editor lookup failed: {e}")
        return None

    async def fill_description(self, description: str) -> bool:  # pragma: no cover
        text = description or ""
        try:
            ed = await self._first_visible_ql_editor()
            if ed is None:
                logger.warning("fill_description: no visible .ql-editor")
                return False
            await ed.click(timeout=8000)
            await asyncio.sleep(0.5)
            await self.page.keyboard.press("ControlOrMeta+A")
            await self.page.keyboard.press("Backspace")
            await asyncio.sleep(0.3)
            # Chunked typing so Quill + char counter update.
            for idx in range(0, len(text), 80):
                chunk = text[idx : idx + 80]
                await self.page.keyboard.type(chunk, delay=random.randint(8, 25))
                await asyncio.sleep(random.uniform(0.05, 0.2))
            await self._human_pause(0.5, 1.0)
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"fill_description failed: {e}")
            return False

    async def read_description(self) -> tuple[str, str]:  # pragma: no cover
        """Return (ql_inner_text, counter_text like '637/2000')."""
        try:
            txt = await self.page.evaluate(
                """() => {
                  const eds=[...document.querySelectorAll('.ql-editor')];
                  for(const e of eds){
                    try{ const r=e.getBoundingClientRect(); if(r.width>0&&r.height>0) return (e.innerText||''); }catch(_){}
                  }
                  return '';
                }"""
            )
        except Exception:  # noqa: BLE001
            txt = ""
        try:
            counter = await self.page.evaluate(
                """() => {
                  // 简介 counter sits in the same .form-item as 简介 h3.
                  const h=[...document.querySelectorAll('h3')].find(e=>((e.innerText||'').trim()==='简介'));
                  if(!h) return '';
                  const item=h.closest('.form-item');
                  if(!item) return '';
                  const m=(item.innerText||'').match(/(\\d+)\\s*\\/\\s*2000/);
                  return m?m[0]:'';
                }"""
            )
        except Exception:  # noqa: BLE001
            counter = ""
        return (txt or "", counter or "")

    async def _visible_tag_input(self):  # pragma: no cover
        try:
            locs = self.page.locator('input[placeholder="按回车键Enter创建标签"]')
            n = await locs.count()
            for i in range(n):
                try:
                    el = locs.nth(i)
                    if await el.is_visible():
                        box = await el.bounding_box()
                        if box and box["width"] > 50:
                            return el
                except Exception:  # noqa: BLE001, S112
                    continue
        except Exception as e:  # noqa: BLE001
            logger.warning(f"tag input lookup failed: {e}")
        return None

    async def read_tags(self) -> list[str]:  # pragma: no cover
        try:
            return await self.page.evaluate(
                "() => [...document.querySelectorAll('.label-item-v2-content')].map(e=>(e.innerText||'').trim()).filter(t=>t)"
            )
        except Exception:  # noqa: BLE001
            return []

    async def clear_tags(self) -> list[str]:  # pragma: no cover
        """Remove all existing tags (Bilibili auto-adds defaults).

        Clicks each pill's close icon sequentially via JS dispatch (direct
        Playwright click is intercepted by open dropdown overlays). Returns
        the remaining tags (should be []).
        """
        for _ in range(15):
            try:
                tags = await self.read_tags()
            except Exception:  # noqa: BLE001
                tags = ["?"]
            if not tags:
                break
            try:
                await self.page.evaluate(
                    """() => {
                      const c=document.querySelector('.label-item-v2-container svg.close');
                      if(c){
                        c.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));
                        c.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));
                        c.dispatchEvent(new MouseEvent('click',{bubbles:true}));
                      }
                    }"""
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"clear_tags dispatch failed: {e}")
                break
            await asyncio.sleep(1.2)
        try:
            return await self.read_tags()
        except Exception:  # noqa: BLE001
            return ["?"]

    async def set_tags(self, tags: list[str]) -> dict:  # pragma: no cover
        wanted = normalize_bili_tags(tags)
        # Close any open dropdown overlay first (it intercepts tag clicks).
        try:
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
        except Exception:  # noqa: BLE001
            pass
        remaining = await self.clear_tags()
        if remaining:
            return {
                "added": [],
                "wanted": wanted,
                "missing": wanted,
                "final": remaining,
                "note": f"could not clear defaults, remaining={remaining}",
            }
        box = await self._visible_tag_input()
        if box is None:
            return {"added": [], "wanted": wanted, "missing": wanted, "final": [], "note": "tag input not found"}
        added: list[str] = []
        for tag in wanted:
            try:
                await box.click(timeout=5000)
                await box.type(tag, delay=40)
                await self.page.keyboard.press("Enter")
                await asyncio.sleep(1.0)
                added.append(tag)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"tag '{tag}' failed: {e}")
                continue
        await asyncio.sleep(1.0)
        final = await self.read_tags()
        return {
            "added": added,
            "wanted": wanted,
            "missing": [t for t in wanted if t not in final],
            "final": final,
        }

    async def read_partition_main(self) -> str:  # pragma: no cover
        try:
            return await self.page.evaluate(
                """() => {
                  const el=document.querySelector('.selector-container .select-item-cont');
                  return el?((el.innerText||'').trim()):'';
                }"""
            )
        except Exception:  # noqa: BLE001
            return ""

    async def fetch_predict_subtype(self, title: str) -> dict:  # pragma: no cover
        """Read the backend subtype (tid) for this title from page traffic.

        The predict endpoint needs CSRF, so manual fetch fails (-111).
        Instead: (1) wait for the page's own predict POST response by
        nudging the title input (space+backspace, value unchanged) while
        listening for /archive/types/predict; (2) fall back to parsing
        subtype_id from tag/recommend performance URLs (proves backend 207).
        Returns {id, parent_name, name} (expect 207/知识/财经商业).
        """
        # -- primary: capture the page's own predict POST response --
        captured: dict = {}

        async def _on_resp(resp) -> None:
            try:
                url = resp.url or ""
                if "/archive/types/predict" not in url:
                    return
                try:
                    j = await resp.json()
                except Exception:  # noqa: BLE001
                    return
                data = (j.get("data") if isinstance(j, dict) else None) or []
                if data:
                    top = data[0] or {}
                    captured.update(
                        {"id": top.get("id"), "parent_name": top.get("parent_name"), "name": top.get("name")}
                    )
            except Exception:  # noqa: BLE001
                pass

        try:
            self.page.on("response", lambda r: asyncio.ensure_future(_on_resp(r)))
        except Exception:  # noqa: BLE001
            pass
        try:
            # Nudge title to trigger a fresh predict (value restored).
            try:
                ti = self.page.locator('input[placeholder="请输入稿件标题"]').first
                await ti.click(timeout=5000)
                await self.page.keyboard.press("End")
                await self.page.keyboard.type(" ", delay=10)
                await asyncio.sleep(0.3)
                await self.page.keyboard.press("Backspace")
                await asyncio.sleep(0.3)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"predict nudge failed: {e}")
            for _ in range(20):
                if captured.get("id"):
                    break
                await asyncio.sleep(0.75)
        finally:
            try:
                self.page.remove_listener("response", _on_resp)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                try:
                    # Playwright Python uses .off in newer versions.
                    self.page.off("response", _on_resp)  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    pass
        if captured.get("id"):
            return captured
        # -- fallback: subtype_id from tag/recommend performance URLs --
        try:
            perf = await self.page.evaluate(
                """() => performance.getEntriesByType('resource').map(e=>e.name)
                       .filter(u=>u.includes('tag/recommend')).slice(-5)"""
            )
            for u in reversed(perf or []):
                m = re.search(r"subtype_id=(\d+)", u or "")
                if m and int(m.group(1)) == BILI_TID:
                    # id verified via backend traffic; name/parent from the
                    # predict contract (verified live 2026-09-27: top-1 for
                    # this finance title is 207/知识/财经商业).
                    return {"id": BILI_TID, "parent_name": "知识", "name": PARTITION_SUB_WANT,
                            "via": "tag/recommend performance"}
            return {"error": f"no predict capture and no subtype_id=207 in performance ({len(perf or [])} tag urls)"}
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)[:200]}

    async def select_partition(self) -> dict:  # pragma: no cover
        """Select main 分区 知识; verify sub 财经商业 (tid 207) via predict API.

        NOTE (2026-09-27): the current upload UI exposes ONLY the single
        human-type main selector (id 1010 知识). There is no visible sub-zone
        dropdown — 财经商业 is the backend subtype (tid 207, parent 知识)
        returned top-1 by /x/vupre/web/archive/types/predict for this
        finance title, and tag/recommend already uses subtype_id=207.
        So: set main=知识 in UI, then confirm sub via API.
        """
        try:
            try:
                await self.page.keyboard.press("Escape")
                await asyncio.sleep(0.5)
            except Exception:  # noqa: BLE001
                pass
            # Open main selector and ensure 知识 is chosen.
            try:
                sel = self.page.locator(".selector-container .select-controller").first
                await sel.click(timeout=5000)
                await asyncio.sleep(2.0)
                items = self.page.locator(".drop-list-v2-item")
                n = await items.count()
                for i in range(n):
                    try:
                        txt = (await items.nth(i).inner_text()).strip()
                        if txt == PARTITION_MAIN_WANT:
                            await items.nth(i).click(timeout=5000)
                            await asyncio.sleep(1.5)
                            break
                    except Exception:  # noqa: BLE001, S112
                        continue
            except Exception as e:  # noqa: BLE001
                logger.warning(f"partition main click failed: {e}")
            try:
                await self.page.keyboard.press("Escape")
                await asyncio.sleep(0.5)
            except Exception:  # noqa: BLE001
                pass
            main = (await self.read_partition_main()) or ""
            # Sub verification via backend predict API.
            sub = await self.fetch_predict_subtype(main)
            ok_main = PARTITION_MAIN_WANT in main
            ok_sub = sub.get("id") == BILI_TID and sub.get("name") == PARTITION_SUB_WANT
            note = f"main={main!r} sub={sub}"
            # Also confirm recommend API subtype (tag/recommend uses subtype_id).
            return {"ok": bool(ok_main and ok_sub), "main": main, "sub": sub, "tid": BILI_TID, "note": note}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "note": str(e)}

    async def set_creation_declaration(self) -> dict:  # pragma: no cover
        """Set 创作声明: 含AI生成内容 + 内容为自制 (copyright=1).

        The 创作声明 dropdown is single-select for the main statement
        (input value) plus a separate auth toggle (内容为自制 gets
        option-text-selected + checkmark). Both must be ON.
        """
        res: dict = {"ai": False, "self": False, "input": ""}
        try:
            try:
                await self.page.keyboard.press("Escape")
                await asyncio.sleep(0.5)
            except Exception:  # noqa: BLE001
                pass
            inp = self.page.locator('input[placeholder="请选择符合您视频内容的创作声明"]').first
            await inp.click(timeout=5000)
            await asyncio.sleep(1.5)
            ai = self.page.get_by_text(DECL_AI_OPTION, exact=True)
            if await ai.count() > 0:
                try:
                    await ai.first.click(timeout=5000)
                    await asyncio.sleep(1.0)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"AI decl click failed: {e}")
            try:
                res["input"] = await self.page.evaluate(
                    """() => document.querySelector('input[placeholder="请选择符合您视频内容的创作声明"]')?.value||''"""
                )
            except Exception:  # noqa: BLE001
                res["input"] = ""
            res["ai"] = DECL_AI_OPTION in (res["input"] or "")
            # Reopen for 自制 toggle (dropdown closes after main select).
            try:
                await inp.click(timeout=5000)
                await asyncio.sleep(1.5)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"decl reopen failed: {e}")
            zz = self.page.get_by_text(DECL_SELF_OPTION, exact=False)
            if await zz.count() > 0:
                try:
                    await zz.first.click(timeout=5000)
                    await asyncio.sleep(1.0)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"自制 click failed: {e}")
            try:
                self_state = await self.page.evaluate(
                    """() => {
                      const spans=[...document.querySelectorAll('.auth-content .option-text')];
                      for(const s of spans){
                        if((s.textContent||'').includes('内容为自制')) return (s.className||'');
                      }
                      return '';
                    }"""
                )
            except Exception:  # noqa: BLE001
                self_state = ""
            res["self"] = "option-text-selected" in (self_state or "")
            try:
                await self.page.keyboard.press("Escape")
                await asyncio.sleep(0.5)
            except Exception:  # noqa: BLE001
                pass
            res["ok"] = bool(res["ai"] and res["self"])
            return res
        except Exception as e:  # noqa: BLE001
            res["note"] = str(e)
            res["ok"] = False
            return res

    async def set_original(self) -> bool:  # pragma: no cover
        """Back-compat wrapper: sets 创作声明 (自制+AI), returns self-state."""
        res = await self.set_creation_declaration()
        return bool(res.get("self"))

    async def expand_more_settings(self) -> bool:  # pragma: no cover
        """Expand 更多设置 (required by task; screenshot close-up)."""
        try:
            body = await self.page.evaluate("() => document.body.innerText || ''")
            # Already expanded? (shows 添加水印/可见范围).
            if "添加水印" in (body or "") and "可见范围" in (body or ""):
                return True
            cand = self.page.get_by_text(MORE_SETTINGS_TEXT, exact=False)
            if await cand.count() > 0:
                try:
                    await cand.first.click(timeout=5000)
                    await asyncio.sleep(2.0)
                    return True
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"more-settings click failed: {e}")
                    return False
            return False
        except Exception as e:  # noqa: BLE001
            logger.warning(f"expand_more_settings failed: {e}")
            return False

    async def read_more_settings_expanded(self) -> bool:  # pragma: no cover
        try:
            body = await self.page.evaluate("() => document.body.innerText || ''")
            return "添加水印" in (body or "") and "可见范围" in (body or "")
        except Exception:  # noqa: BLE001
            return False

    async def read_cover_state(self) -> dict:  # pragma: no cover
        """Read back cover slot: present when div.cover-img exists (no .cover-empty)."""
        try:
            st = await self.page.evaluate(
                """() => {
                  const slot=document.querySelector('.cover-slot');
                  if(!slot) return {present:false, reason:'no .cover-slot'};
                  const hasImg=!!slot.querySelector('.cover-img');
                  const hasEmpty=!!slot.querySelector('.cover-empty');
                  const bg=(slot.querySelector('.cover-img')?.getAttribute('style')||'').slice(0,80);
                  return {present:hasImg&&!hasEmpty, hasImg, hasEmpty, bg};
                }"""
            )
            return dict(st or {})
        except Exception as e:  # noqa: BLE001
            return {"present": False, "reason": str(e)[:200]}

    async def read_parts(self) -> dict:  # pragma: no cover
        """Count video parts; fail when cover PNG became P2 or upload failed."""
        try:
            info = await self.page.evaluate(
                """() => {
                  const tasks=[...document.querySelectorAll('.task-list-content-item .task-title-text')].map(e=>(e.textContent||'').trim()).filter(t=>t);
                  const files=[...document.querySelectorAll('.file-item .title-text')].map(e=>(e.textContent||'').trim()).filter(t=>t);
                  const body=document.body.innerText||'';
                  return {tasks, files, hasFail: body.includes('上传失败')};
                }"""
            )
            tasks = list((info or {}).get("tasks") or [])
            files = list((info or {}).get("files") or [])
            has_fail = bool((info or {}).get("hasFail"))
            n = max(len(tasks), len(files))
            return {"tasks": tasks, "files": files, "count": n, "has_fail": has_fail}
        except Exception as e:  # noqa: BLE001
            return {"tasks": [], "files": [], "count": -1, "has_fail": False, "error": str(e)[:200]}

    async def upload_cover(self, cover_path: str | None) -> dict:  # pragma: no cover
        """Upload cover via 封面 → 添加封面 modal → 上传封面 → 完成.

        NEVER touches the video file input (that created P2). Returns
        {ok, note}. Verifies div.cover-img thumbnail afterwards.
        """
        if not cover_path or not Path(cover_path).exists():
            return {"ok": False, "note": f"cover missing: {cover_path}"}
        try:
            # Already has cover? (idempotent rerun)
            cur = await self.read_cover_state()
            if cur.get("present"):
                return {"ok": True, "note": "cover already present"}
            add_btn = self.page.get_by_text("添加封面", exact=True)
            if await add_btn.count() == 0:
                return {"ok": False, "note": "添加封面 button not found"}
            try:
                await add_btn.first.click(timeout=8000)
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "note": f"添加封面 click failed: {e}"}
            await asyncio.sleep(3.0)
            # Click 上传封面 (opens image file chooser).
            up_btn = self.page.get_by_text("上传封面", exact=False)
            if await up_btn.count() == 0:
                try:
                    await self.page.keyboard.press("Escape")
                except Exception:  # noqa: BLE001
                    pass
                return {"ok": False, "note": "上传封面 button not found in modal"}
            got_chooser = False
            for i in range(await up_btn.count()):
                try:
                    loc = up_btn.nth(i)
                    if not await loc.is_visible():
                        continue
                    async with self.page.expect_file_chooser(timeout=6000) as fc:
                        await loc.click(timeout=5000)
                    chooser = await fc.value
                    await chooser.set_files(str(cover_path))
                    got_chooser = True
                    break
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"上传封面[{i}] chooser failed: {e}")
                    continue
            if not got_chooser:
                return {"ok": False, "note": "image file chooser did not open"}
            await asyncio.sleep(4.0)
            # Confirm crop: click 完成.
            done = self.page.get_by_text("完成", exact=True)
            clicked_done = False
            if await done.count() > 0:
                for i in range(await done.count()):
                    try:
                        if await done.nth(i).is_visible():
                            await done.nth(i).click(timeout=5000)
                            clicked_done = True
                            break
                    except Exception:  # noqa: BLE001, S112
                        continue
            if not clicked_done:
                return {"ok": False, "note": "完成 (crop confirm) not clicked"}
            await asyncio.sleep(4.0)
            cur2 = await self.read_cover_state()
            if cur2.get("present"):
                return {"ok": True, "note": "cover thumbnail present after 完成"}
            return {"ok": False, "note": f"cover thumbnail missing after 完成: {cur2}"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "note": str(e)[:300]}

    async def try_ai_declaration(self) -> dict:  # pragma: no cover
        """Back-compat wrapper around set_creation_declaration."""
        res = await self.set_creation_declaration()
        return {
            "offered": True,
            "on": bool(res.get("ai") and res.get("self")),
            "note": f"input={res.get('input')!r} self={res.get('self')}",
        }

    async def verify_form(  # pragma: no cover
        self,
        expected_title: str = "",
        *,
        expected_description: str = "",
        expected_tags: list[str] | None = None,
        expected_cover: bool = True,
    ) -> DraftCheck:
        """Strict read-back of every field. FAILS loudly on any mismatch.

        Checks: title exact, cover thumbnail present, 简介 content + counter,
        tags exact list, 分区 main 知识 + sub 财经商业/207, 自制 ON,
        AI declaration ON, single part only (no P2/上传失败).
        """
        issues: list[str] = []
        # -- title (exact input value) --
        title_match = False
        try:
            loc = self.page.locator('input[placeholder="请输入稿件标题"]').first
            v = await loc.input_value(timeout=5000)
            title_match = bool(expected_title) and (v or "").strip() == expected_title.strip()
            if not title_match:
                issues.append(f"title mismatch: got={(v or '')[:30]!r} want={(expected_title or '')[:30]!r}")
        except Exception as e:  # noqa: BLE001
            issues.append(f"title read failed: {e}")
        # -- cover --
        cover_present = False
        if expected_cover:
            cov = await self.read_cover_state()
            cover_present = bool(cov.get("present"))
            if not cover_present:
                issues.append(f"cover thumbnail missing: {cov}")
        # -- description (Quill text + counter) --
        desc_text, counter = await self.read_description()
        if expected_description:
            want = (expected_description or "").strip()
            got = (desc_text or "").strip()
            # Compare beginnings + key markers (Quill may normalize whitespace).
            if len(got) < 100:
                issues.append(f"简介 too short/empty: chars={len(got)} counter={counter!r}")
            for marker in description_verify_markers(expected_description, expected_title):
                if marker and marker not in got:
                    issues.append(f"简介 missing marker {marker!r} (chars={len(got)} counter={counter!r})")
                    break
            # Counter should match payload length (allow ±5 for normalization).
            try:
                m = re.search(r"(\d+)\s*/\s*2000", counter or "")
                if m:
                    n = int(m.group(1))
                    if abs(n - len(want)) > 5:
                        issues.append(f"简介 counter mismatch: counter={n} payload_len={len(want)}")
                elif got:
                    issues.append(f"简介 counter unreadable: {counter!r} (chars={len(got)})")
            except Exception as e:  # noqa: BLE001
                issues.append(f"简介 counter check failed: {e}")
        # -- tags exact --
        if expected_tags is not None:
            wanted = normalize_bili_tags(expected_tags)
            final = await self.read_tags()
            if final != wanted:
                issues.append(f"tags mismatch: got={final} want={wanted}")
        # -- partition --
        main = await self.read_partition_main()
        if PARTITION_MAIN_WANT not in (main or ""):
            issues.append(f"分区 main mismatch: got={main!r} want~{PARTITION_MAIN_WANT!r}")
        sub = await self.fetch_predict_subtype(main)
        if not (sub.get("id") == BILI_TID and sub.get("name") == PARTITION_SUB_WANT):
            issues.append(f"分区 sub mismatch: got={sub} want={{id:{BILI_TID}, name:{PARTITION_SUB_WANT!r}}}")
        # -- 自制 + AI declaration --
        try:
            decl_input = await self.page.evaluate(
                """() => document.querySelector('input[placeholder="请选择符合您视频内容的创作声明"]')?.value||''"""
            )
        except Exception:  # noqa: BLE001
            decl_input = ""
        if DECL_AI_OPTION not in (decl_input or ""):
            issues.append(f"AI declaration not set: input={decl_input!r} want={DECL_AI_OPTION!r}")
        try:
            self_cls = await self.page.evaluate(
                """() => {
                  const spans=[...document.querySelectorAll('.auth-content .option-text')];
                  for(const s of spans){ if((s.textContent||'').includes('内容为自制')) return (s.className||''); }
                  return '';
                }"""
            )
        except Exception:  # noqa: BLE001
            self_cls = ""
        if "option-text-selected" not in (self_cls or ""):
            issues.append("自制 (内容为自制) not selected")
        # -- 更多设置 expanded --
        if not await self.read_more_settings_expanded():
            issues.append("更多设置 not expanded")
        # -- single part only --
        parts = await self.read_parts()
        if parts.get("has_fail"):
            issues.append(f"upload failure text present (P2 cover bug?): parts={parts}")
        if parts.get("count") != 1:
            issues.append(f"part count != 1 (want single P1 only): parts={parts}")
        else:
            names = (parts.get("tasks") or []) + (parts.get("files") or [])
            if any("cover" in (n or "").lower() or "ep1_cover" in (n or "") for n in names):
                issues.append(f"cover filename leaked into parts (P2 bug): parts={parts}")
        # -- upload still in progress / captcha --
        try:
            body = await self.page.evaluate("() => document.body.innerText || ''")
        except Exception:  # noqa: BLE001
            body = ""
        upload_done = True
        if any(k in (body or "") for k in ["上传中", "正在上传"]):
            upload_done = False
            issues.append("upload still in progress")
        if self.detect_captcha_sync_text(body or ""):
            issues.append("captcha/risk text visible")
            upload_done = False
        ok = title_match and upload_done and not issues
        return DraftCheck(ok, title_match, upload_done, issues)

    def detect_captcha_sync_text(self, body: str) -> bool:
        # Strict visible-text check: generic "风险"/"滑动"/"异常" and bare
        # "-663" must NOT count (finance disclaimer + SVG coords FP).
        return visible_text_has_captcha(body or "")

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
        payload = kwargs.get("payload")
        if not payload:
            return PublishResult(
                success=False,
                platform=self.platform_name,
                error="Bili publisher needs payload=<publish_payload.json>.",
            )
        res = await self.publish_video_from_payload(payload, mode=kwargs.get("mode", "draft"), **kwargs)
        if res.get("status") == "published":
            return PublishResult(
                success=True,
                platform=self.platform_name,
                post_url=res.get("public_url"),
                post_id=res.get("bvid"),
                published_at=datetime.now(),
            )
        if res.get("status") == "draft":
            return PublishResult(
                success=True,
                platform=self.platform_name,
                post_url=res.get("draft_url"),
                published_at=datetime.now(),
            )
        return PublishResult(success=False, platform=self.platform_name, error=res.get("error", "unknown"))

    # -- full video flow --------------------------------------------------- #

    async def publish_video_from_payload(  # pragma: no cover - browser E2E
        self,
        payload_path: str | Path,
        mode: str = "draft",
        smoke_label: str = "ep1",
        force: bool = False,
        no_open: bool = False,
        **kwargs,
    ) -> dict:
        _ = kwargs
        _ = no_open  # `open <url>` handled by CLI layer.
        data = load_payload(payload_path)
        title = data["title"]
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
                    "bvid": rec.get("bvid"),
                    "published_json": str(get_published_path(payload_path)),
                    "title": title,
                }

        await self.init_browser()
        # NOTE: on BLOCKED (captcha/risk) we intentionally LEAVE the browser
        # open + visible so the owner can see/manual-handle; only draft/error
        # paths close it here. Publish-success also closes after screenshots.
        blocked_open = False
        try:
            logged_in, login_needed = await self.ensure_login()
            if not logged_in:
                blocked_open = True
                return {"status": "blocked", "reason": "login", "error": "BLOCKED: login"}
            if not await self.wait_captcha_if_present():
                blocked_open = True
                return {"status": "blocked", "reason": "verification", "error": "BLOCKED: verification"}

            await self.goto_upload_page()
            if not await self.wait_captcha_if_present():
                blocked_open = True
                return {"status": "blocked", "reason": "verification", "error": "BLOCKED: verification"}

            if not await self.upload_video_file(data["video_path"]):
                return {"status": "error", "error": "video upload control not found"}
            ok_upload = await self.wait_for_upload_complete(timeout_s=900)
            if not ok_upload:
                if await self.detect_captcha():
                    blocked_open = True
                    return {"status": "blocked", "reason": "verification", "error": "BLOCKED: verification"}
                return {"status": "error", "error": "video upload did not complete in time"}

            # Dismiss batch-upload popup before filling (single part => usually absent).
            await self.dismiss_batch_popup()

            title_ok = await self.fill_title(title)
            desc_ok = await self.fill_description(data["description"])
            part_res = await self.select_partition()
            decl_res = await self.set_creation_declaration()
            orig_ok = bool(decl_res.get("self"))
            ai_res = {
                "offered": True,
                "on": bool(decl_res.get("ai") and decl_res.get("self")),
                "note": f"input={decl_res.get('input')!r} self={decl_res.get('self')}",
            }
            tags_res = await self.set_tags(data["tags"])
            cover_res = await self.upload_cover(data["cover_path"])
            cover_ok = bool(cover_res.get("ok"))
            more_ok = await self.expand_more_settings()

            # Dismiss any overlay again before screenshots.
            await self.dismiss_batch_popup()

            async def _shot(path, locator_css: str | None = None) -> str | None:
                try:
                    if locator_css:
                        loc = self.page.locator(locator_css).first
                        if await loc.count() > 0:
                            try:
                                await loc.scroll_into_view_if_needed(timeout=5000)
                                await asyncio.sleep(0.5)
                            except Exception:  # noqa: BLE001
                                pass
                            await loc.screenshot(path=str(path), timeout=20000)
                            return str(path)
                    await self.page.screenshot(path=str(path), full_page=True, timeout=20000)
                    return str(path)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"screenshot {path.name} failed: {e}")
                    return None

            shot_form = self.smoke_dir / f"{smoke_label}_filled_form.png"
            try:
                await self.page.screenshot(path=str(shot_form), full_page=True, timeout=20000)
                shot_form_s: str | None = str(shot_form)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"form screenshot failed: {e}")
                shot_form_s = None
            shot_cover = await _shot(self.smoke_dir / f"{smoke_label}_cover.png", ".cover-slot")
            shot_tags = await _shot(self.smoke_dir / f"{smoke_label}_tags.png", "#tag-container")
            # More-settings block: the title div[data-v-fecbea4e] .title.
            shot_more = await _shot(self.smoke_dir / f"{smoke_label}_more_settings.png", ".form-item:has-text('添加水印')")

            check = await self.verify_form(
                title,
                expected_description=data["description"],
                expected_tags=data["tags"],
                expected_cover=True,
            )
            # Hard fail loudly: surface individual fill failures too.
            if not title_ok:
                check.issues.append("fill_title reported failure")
                check.ok = False
            if not desc_ok:
                check.issues.append("fill_description reported failure")
                check.ok = False
            if not part_res.get("ok"):
                check.issues.append(f"select_partition failed: {part_res}")
                check.ok = False
            if not decl_res.get("ok"):
                check.issues.append(f"creation declaration failed: {decl_res}")
                check.ok = False
            if (tags_res.get("final") or []) != normalize_bili_tags(data["tags"]):
                check.issues.append(f"tags final mismatch: {tags_res}")
                check.ok = False
            if not cover_ok:
                check.issues.append(f"cover failed: {cover_res}")
                check.ok = False
            if not more_ok:
                check.issues.append("expand_more_settings failed")
                check.ok = False
            result: dict = {
                "status": "draft",
                "mode": mode,
                "title": title,
                "login_needed": login_needed,
                "headless_started": bool(getattr(self, "_started_headless", True)),
                "headless_used": bool(self.headless and not getattr(self, "_fell_back_to_headed", False)),
                "fallback_to_headed": bool(getattr(self, "_fell_back_to_headed", False)),
                "partition": {"wanted": BILI_PARTITION_NAME, "tid": BILI_TID, **part_res},
                "copyright_original": bool(orig_ok),
                "creation_declaration": decl_res,
                "tags": tags_res,
                "cover": {"ok": bool(cover_ok), "path": data["cover_path"], "detail": cover_res},
                "ai_declaration": ai_res,
                "more_settings_expanded": bool(more_ok),
                "description": {
                    "ok": desc_ok,
                    "len": len(data["description"] or ""),
                },
                "verification": {
                    "ok": check.ok,
                    "title_match": check.title_match,
                    "upload_done": check.upload_done,
                    "issues": check.issues,
                },
                "screenshots": [str(s) for s in (shot_form_s, shot_cover, shot_tags, shot_more) if s],
                "upload_page": self.page.url if self.page else "",
            }
            if mode == "draft":
                if not check.ok:
                    result["status"] = "error"
                    result["error"] = f"draft verification failed: {check.issues}"
                return result
            if not check.ok:
                result["status"] = "error"
                result["error"] = f"draft verification failed: {check.issues}"
                return result

            # mode == publish: click publish (max 3 attempts).
            # Never double-submit: after ANY click error, re-check the
            # manuscript manager for this title before retrying. Success is
            # confirmed via BV in URL/body or the success page
            # (稿件投递成功/投稿成功/发布成功/审核中/转码中) or the manager list.
            published_url: str | None = None
            bvid: str | None = None
            last_err: str | None = None
            clicked_text: str = ""
            for attempt in range(1, 4):
                try:
                    # Re-check before retrying (attempts 2-3): maybe the
                    # previous click actually submitted despite the error.
                    if attempt > 1:
                        try:
                            recheck = await self.search_title_in_manager(title)
                        except Exception:  # noqa: BLE001
                            recheck = {"found": False}
                        if recheck.get("found"):
                            bvid = str(recheck.get("bvid") or "") or None
                            published_url = (
                                f"https://www.bilibili.com/video/{bvid}"
                                if bvid
                                else "submitted (found in manuscript manager)"
                            )
                            logger.info(f"publish recheck: title already submitted (attempt {attempt})")
                            break
                    clicked_text = await self._click_publish_button_once()
                    await self._human_pause(1.5, 2.5)
                    try:
                        await self.page.wait_for_load_state("networkidle", timeout=20000)
                    except Exception:  # noqa: BLE001
                        pass
                    await asyncio.sleep(5)
                    url = self.page.url or ""
                    found_bvid = extract_bvid(url)
                    if found_bvid:
                        bvid = found_bvid
                        published_url = url
                    else:
                        try:
                            body = await self.page.evaluate("() => document.body.innerText || ''")
                        except Exception:  # noqa: BLE001
                            body = ""
                        found_bvid = extract_bvid(body or "")
                        if found_bvid:
                            bvid = found_bvid
                            published_url = f"https://www.bilibili.com/video/{bvid}"
                        elif is_publish_success_body(body or ""):
                            published_url = url or "submitted (URL pending review state)"
                    # Captcha after click -> blocked, keep visible.
                    if await self.detect_captcha():
                        blocked_open = True
                        return {"status": "blocked", "reason": "verification", "error": "BLOCKED: verification"}
                    if published_url:
                        break
                    # Click went through but no success marker yet: confirm
                    # via the manager before declaring failure (covers the
                    # redirect-to-manager success path).
                    try:
                        confirm = await self.search_title_in_manager(title)
                    except Exception:  # noqa: BLE001
                        confirm = {"found": False}
                    if confirm.get("found"):
                        bvid = str(confirm.get("bvid") or "") or bvid
                        published_url = (
                            f"https://www.bilibili.com/video/{bvid}"
                            if bvid
                            else "submitted (found in manuscript manager)"
                        )
                        break
                    last_err = f"attempt {attempt} (clicked {clicked_text!r}): no BV/URL yet (url={url[:120]})"
                    await self._human_pause(2.0, 3.0)
                except Exception as e:  # noqa: BLE001
                    last_err = str(e)
                    logger.warning(f"publish attempt {attempt}/3 failed: {e}")
                    # After ANY click error, re-check the list before the
                    # next retry so a half-submitted click never double-posts.
                    try:
                        recheck = await self.search_title_in_manager(title)
                    except Exception:  # noqa: BLE001
                        recheck = {"found": False}
                    if recheck.get("found"):
                        bvid = str(recheck.get("bvid") or "") or None
                        published_url = (
                            f"https://www.bilibili.com/video/{bvid}"
                            if bvid
                            else "submitted (found in manuscript manager after error)"
                        )
                        break
                    await self._human_pause(2.0, 3.0)
            if not published_url:
                result["status"] = "error"
                result["error"] = f"publish click failed after 3 tries: {last_err}"
                return result

            # Wait for transcode/review state + screenshot result.
            await asyncio.sleep(3)
            shot_result = self.smoke_dir / f"{smoke_label}_result.png"
            try:
                await self.page.screenshot(path=str(shot_result), full_page=True, timeout=20000)
                result["screenshots"].append(str(shot_result))
            except Exception as e:  # noqa: BLE001
                logger.warning(f"result screenshot failed: {e}")
            try:
                body = await self.page.evaluate("() => document.body.innerText || ''")
            except Exception:  # noqa: BLE001
                body = ""
            review_state = ""
            for key in PUBLISH_SUCCESS_TEXTS:
                if key in (body or ""):
                    review_state = key
                    break
            result["status"] = "published"
            result["public_url"] = published_url
            result["bvid"] = bvid or ""
            result["review_state"] = review_state
            try:
                record = build_published_record(
                    published_url,
                    screenshots=list(result.get("screenshots", [])),
                    title=title,
                    bvid=bvid or "",
                    status=review_state,
                )
                out_path = save_published_record(payload_path, record)
                result["published_json"] = str(out_path)
                result["published_at"] = record["published_at"]
            except Exception as e:  # noqa: BLE001
                logger.warning(f"save published.json failed: {e}")
            return result
        finally:
            if blocked_open:
                # Keep the window visible per task; do NOT close/cleanup.
                try:
                    bring_chrome_front()
                except Exception:  # noqa: BLE001
                    pass
                notify_owner(NOTIFY_CAPTCHA_MSG if "verification" in str(blocked_open) else NOTIFY_LOGIN_MSG)
            else:
                try:
                    await self.close_browser()
                except Exception:  # noqa: BLE001
                    pass
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
        ctx = await browser.new_context(viewport={"width": 1280, "height": 860}, locale="zh-CN")
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
        return {"ok": False, "status": status, "reason": f"thin/review page (chars={len(text)})", "screenshot": str(out_path)}
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
