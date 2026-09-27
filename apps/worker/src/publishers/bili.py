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
    'input[placeholder*="标题"]',
    'input[maxlength="80"]',
    ".video-title input",
    ".title-input input",
    '[class*="title"] input',
]
DESC_SELECTORS = [
    'textarea[placeholder*="简介"]',
    'textarea[placeholder*="描述"]',
    ".video-desc textarea",
    ".desc-input textarea",
    '[class*="desc"] textarea',
]
TAG_INPUT_SELECTORS = [
    'input[placeholder*="标签"]',
    ".tag-input input",
    '[class*="tag"] input',
]
VIDEO_INPUT_SELECTORS = [
    'input[type="file"][accept*="video"]',
    'input[type="file"][accept*="mp4"]',
    'input[type="file"]',
]
COVER_INPUT_SELECTORS = [
    'input[type="file"][accept*="image"]',
    'input[type="file"][accept*=".jpg"]',
    'input[type="file"]',
]
PUBLISH_BUTTON_TEXTS = ["立即投稿", "投稿", "发布", "提交", "上传"]
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
) -> str:
    """Build the Bilibili description from the YouTube description.

    - Strips external links (Bilibili rule for this smoke test).
    - Keeps the data/method + key-numbers body.
    - Ensures the AI-content sentence is present when the panel switch is
      NOT available (task: turn the switch ON if offered, else state the
      sentence in the description).
    - Always appends the finance disclaimer + presenter branding.
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
) -> dict:
    """Build a Bilibili payload dict from a YouTube ``ep/yt/ep<N>.json`` meta.

    Pure (no browser, no file reads beyond the passed meta dict).
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
    description = build_bili_description(yt_desc, ai_declared_on_panel=False)
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

    async def goto_upload_page(self) -> str:  # pragma: no cover
        last_err: Exception | None = None
        for url in UPLOAD_URLS:
            try:
                await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)
                return url
            except Exception as e:  # noqa: BLE001
                last_err = e
                continue
        raise TimeoutError(f"upload page unreachable: {last_err}")

    async def upload_video_file(self, video_path: str) -> bool:  # pragma: no cover
        p = Path(video_path)
        if not p.exists():
            logger.error(f"video missing: {video_path}")
            return False
        for sel in VIDEO_INPUT_SELECTORS:
            try:
                handle = await self.page.query_selector(sel)
                if handle is not None:
                    await handle.set_input_files(str(p))
                    logger.info(f"video file set: {p.name}")
                    return True
            except Exception:  # noqa: BLE001, S112
                continue
        # Fallback: click upload button + file chooser.
        for btn_sel in [
            'button:has-text("上传")',
            'div:has-text("拖拽")',
            '[class*="upload"]',
        ]:
            try:
                btn = await self.page.query_selector(btn_sel)
                if btn is not None and await btn.is_visible():
                    async with self.page.expect_file_chooser(timeout=8000) as fc:
                        await btn.click(timeout=5000)
                    chooser = await fc.value
                    await chooser.set_files(str(p))
                    return True
            except Exception:  # noqa: BLE001, S112
                continue
        logger.error("video upload control not found")
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
        try:
            el = await self._first_visible(TITLE_SELECTORS, timeout_each_ms=10000)
            await el.click(timeout=10000)
            await asyncio.sleep(0.3)
            try:
                await el.fill("", timeout=5000)
            except Exception:  # noqa: BLE001
                await self.page.keyboard.press("ControlOrMeta+A")
                await self.page.keyboard.press("Backspace")
            await self._human_pause(0.3, 0.7)
            await self.page.keyboard.type(title[:BILI_TITLE_MAX_LEN], delay=random.randint(15, 40))
            await self._human_pause()
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"fill_title failed: {e}")
            return False

    async def fill_description(self, description: str) -> bool:  # pragma: no cover
        try:
            el = await self._first_visible(DESC_SELECTORS, timeout_each_ms=10000)
            await el.click(timeout=10000)
            await asyncio.sleep(0.3)
            try:
                await el.fill("", timeout=5000)
            except Exception:  # noqa: BLE001
                await self.page.keyboard.press("ControlOrMeta+A")
                await self.page.keyboard.press("Backspace")
            # Chunked typing for long descriptions.
            for idx in range(0, len(description), 80):
                chunk = description[idx : idx + 80]
                await self.page.keyboard.type(chunk, delay=random.randint(8, 25))
                await asyncio.sleep(random.uniform(0.05, 0.2))
            await self._human_pause()
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"fill_description failed: {e}")
            return False

    async def set_tags(self, tags: list[str]) -> dict:  # pragma: no cover
        wanted = normalize_bili_tags(tags)
        added: list[str] = []
        try:
            box = None
            for sel in TAG_INPUT_SELECTORS:
                try:
                    loc = self.page.locator(sel)
                    if await loc.count() > 0:
                        box = loc.first
                        break
                except Exception:  # noqa: BLE001, S112
                    continue
            if box is None:
                return {"added": [], "wanted": wanted, "missing": wanted, "note": "tag input not found"}
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
            return {"added": added, "wanted": wanted, "missing": [t for t in wanted if t not in added]}
        except Exception as e:  # noqa: BLE001
            return {"added": added, "wanted": wanted, "missing": wanted, "note": str(e)}

    async def select_partition(self) -> dict:  # pragma: no cover
        """Best-effort partition selection: 知识 > 财经商业 (tid 207)."""
        try:
            # Strategy 1: click 分区 selector, then 知识, then 财经商业.
            for trigger in ['*:has-text("分区")', '[class*="partition"]', '[class*="type"]']:
                try:
                    el = await self.page.query_selector(trigger)
                    if el is not None and await el.is_visible():
                        await el.click(timeout=5000)
                        await asyncio.sleep(1.5)
                        break
                except Exception:  # noqa: BLE001, S112
                    continue
            await asyncio.sleep(1.0)
            # Click 知识 then 财经商业 if visible.
            clicked_main = False
            for name in ["知识", "财经商业", "财经"]:
                try:
                    cand = self.page.get_by_text(name, exact=False)
                    if await cand.count() > 0:
                        try:
                            await cand.first.click(timeout=4000)
                            await asyncio.sleep(1.2)
                            clicked_main = True
                        except Exception:  # noqa: BLE001, S112
                            continue
                except Exception:  # noqa: BLE001
                    continue
            # Read back selected partition text.
            try:
                body = await self.page.evaluate("() => document.body.innerText || ''")
            except Exception:  # noqa: BLE001
                body = ""
            ok = ("财经" in (body or "")) and ("知识" in (body or "") or "207" in (body or ""))
            return {"ok": bool(ok or clicked_main), "note": "best-effort; verify in screenshot"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "note": str(e)}

    async def set_original(self) -> bool:  # pragma: no cover
        """Select 自制/原创 (copyright=1). Best-effort."""
        for name in ORIGINAL_TEXTS:
            try:
                cand = self.page.get_by_text(name, exact=False)
                if await cand.count() > 0:
                    try:
                        await cand.first.click(timeout=5000)
                        await asyncio.sleep(1.0)
                        return True
                    except Exception:  # noqa: BLE001, S112
                        continue
            except Exception:  # noqa: BLE001
                continue
        # Fallback: radio inputs.
        try:
            radios = await self.page.query_selector_all('input[type="radio"]')
            if radios:
                await radios[0].click(timeout=5000)
                return True
        except Exception:  # noqa: BLE001
            pass
        return False

    async def upload_cover(self, cover_path: str | None) -> bool:  # pragma: no cover
        if not cover_path or not Path(cover_path).exists():
            logger.info("no cover image; skipping cover step")
            return False
        try:
            for sel in COVER_INPUT_SELECTORS:
                try:
                    handle = await self.page.query_selector(sel)
                    if handle is not None:
                        await handle.set_input_files(str(cover_path))
                        await asyncio.sleep(3.0)
                        logger.info(f"cover file set: {Path(cover_path).name}")
                        return True
                except Exception:  # noqa: BLE001, S112
                    continue
            # Fallback: click 封面 button + file chooser.
            for name in ["上传封面", "更换封面", "封面"]:
                try:
                    btn = self.page.get_by_text(name, exact=False)
                    if await btn.count() > 0:
                        async with self.page.expect_file_chooser(timeout=8000) as fc:
                            await btn.first.click(timeout=5000)
                        chooser = await fc.value
                        await chooser.set_files(str(cover_path))
                        await asyncio.sleep(3.0)
                        return True
                except Exception:  # noqa: BLE001, S112
                    continue
            logger.warning("cover input not found (non-fatal)")
            return False
        except Exception as e:  # noqa: BLE001
            logger.warning(f"cover step failed (non-fatal): {e}")
            return False

    async def try_ai_declaration(self) -> dict:  # pragma: no cover
        """Turn the AI-content declaration switch ON if the panel offers it.

        Returns {offered, on}. When not offered, the caller must ensure the
        description already carries the AI sentence (built by default).
        """
        try:
            body = await self.page.evaluate("() => document.body.innerText || ''")
        except Exception:  # noqa: BLE001
            body = ""
        offered = any(k in (body or "") for k in AI_DECL_TEXTS)
        if not offered:
            return {"offered": False, "on": False, "note": "no AI panel; description carries the sentence"}
        # Try switch/checkbox/radio near AI text.
        for sel in [
            'input[type="checkbox"]',
            'input[type="switch"]',
            '[role="switch"]',
            ".switch",
            '[class*="switch"]',
        ]:
            try:
                els = await self.page.query_selector_all(sel)
                for el in els[:6]:
                    try:
                        # Check proximity to AI text via parent text.
                        parent_text = await self.page.evaluate(
                            "(el) => (el.closest('div')?.innerText || '').slice(0,200)", el
                        )
                        if any(k in (parent_text or "") for k in AI_DECL_TEXTS):
                            await el.click(timeout=4000)
                            await asyncio.sleep(1.0)
                            return {"offered": True, "on": True, "note": "switch clicked"}
                    except Exception:  # noqa: BLE001, S112
                        continue
            except Exception:  # noqa: BLE001
                continue
        # Fallback: click AI text itself.
        for name in AI_DECL_TEXTS:
            try:
                cand = self.page.get_by_text(name, exact=False)
                if await cand.count() > 0:
                    try:
                        await cand.first.click(timeout=4000)
                        await asyncio.sleep(1.0)
                        return {"offered": True, "on": True, "note": f"clicked {name}"}
                    except Exception:  # noqa: BLE001, S112
                        continue
            except Exception:  # noqa: BLE001
                continue
        return {"offered": True, "on": False, "note": "panel seen but switch not toggled; description carries the sentence"}

    async def verify_form(self, expected_title: str) -> DraftCheck:  # pragma: no cover
        issues: list[str] = []
        try:
            body = await self.page.evaluate("() => document.body.innerText || ''")
        except Exception:  # noqa: BLE001
            body = ""
        title_match = bool(expected_title and expected_title[:10] in (body or ""))
        if not title_match:
            # Try input values directly.
            for sel in TITLE_SELECTORS:
                try:
                    loc = self.page.locator(sel)
                    if await loc.count() > 0:
                        v = await loc.first.input_value(timeout=3000)
                        if v and (expected_title[:10] in v or v[:10] in expected_title):
                            title_match = True
                            break
                except Exception:  # noqa: BLE001, S112
                    continue
        if not title_match:
            issues.append("title text not found in upload form")
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

            await self.fill_title(title)
            await self.fill_description(data["description"])
            part_res = await self.select_partition()
            orig_ok = await self.set_original()
            tags_res = await self.set_tags(data["tags"])
            cover_ok = await self.upload_cover(data["cover_path"])
            ai_res = await self.try_ai_declaration()

            shot_form = self.smoke_dir / f"{smoke_label}_filled_form.png"
            try:
                await self.page.screenshot(path=str(shot_form), full_page=True, timeout=20000)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"form screenshot failed: {e}")
                shot_form = None  # type: ignore[assignment]

            check = await self.verify_form(title)
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
                "tags": tags_res,
                "cover": {"ok": bool(cover_ok), "path": data["cover_path"]},
                "ai_declaration": ai_res,
                "verification": {
                    "ok": check.ok,
                    "title_match": check.title_match,
                    "upload_done": check.upload_done,
                    "issues": check.issues,
                },
                "screenshots": [str(s) for s in (shot_form,) if s],
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
            published_url: str | None = None
            bvid: str | None = None
            last_err: str | None = None
            for attempt in range(1, 4):
                try:
                    clicked = False
                    for text in PUBLISH_BUTTON_TEXTS:
                        try:
                            btn = self.page.get_by_role("button", name=text)
                            if await btn.count() > 0:
                                await btn.first.click(timeout=8000)
                                clicked = True
                                break
                        except Exception:  # noqa: BLE001, S112
                            continue
                    if not clicked:
                        # Fallback substring locator.
                        for text in PUBLISH_BUTTON_TEXTS:
                            try:
                                loc = self.page.locator(f'button:has-text("{text}")')
                                if await loc.count() > 0:
                                    await loc.first.click(timeout=8000)
                                    clicked = True
                                    break
                            except Exception:  # noqa: BLE001, S112
                                continue
                    if not clicked:
                        raise TimeoutError("publish button not found")
                    await self._human_pause(1.5, 2.5)
                    try:
                        await self.page.wait_for_load_state("networkidle", timeout=20000)
                    except Exception:  # noqa: BLE001
                        pass
                    await asyncio.sleep(5)
                    url = self.page.url or ""
                    m = re.search(r"(BV[a-zA-Z0-9]+)", url)
                    if m:
                        bvid = m.group(1)
                        published_url = url
                    else:
                        try:
                            body = await self.page.evaluate("() => document.body.innerText || ''")
                        except Exception:  # noqa: BLE001
                            body = ""
                        m2 = re.search(r"(BV[a-zA-Z0-9]+)", body or "")
                        if m2:
                            bvid = m2.group(1)
                            published_url = f"https://www.bilibili.com/video/{bvid}"
                        elif "投稿成功" in (body or "") or "发布成功" in (body or "") or "审核中" in (
                            body or ""
                        ):
                            published_url = url or "submitted (URL pending review state)"
                    # Captcha after click -> blocked, keep visible.
                    if await self.detect_captcha():
                        blocked_open = True
                        return {"status": "blocked", "reason": "verification", "error": "BLOCKED: verification"}
                    if published_url:
                        break
                    last_err = f"attempt {attempt}: no BV/URL yet (url={url[:120]})"
                    await self._human_pause(2.0, 3.0)
                except Exception as e:  # noqa: BLE001
                    last_err = str(e)
                    logger.warning(f"publish attempt {attempt}/3 failed: {e}")
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
            for key in ["审核中", "转码中", "发布成功", "投稿成功", "审核", "转码"]:
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
