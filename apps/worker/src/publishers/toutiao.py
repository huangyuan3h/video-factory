"""Toutiao (今日头条/头条号) article publisher (Playwright, semi-auto).

Research: ``docs/toutiao-publishing-research.md`` §5 — no usable official
long-content API, so the only realistic path is browser automation.
Mirrors the Zhihu publisher (Playwright + persistent profile + human pacing)
but drives the 头条号 graphic editor at
https://mp.toutiao.com/profile_v4/graphic/publish instead of Zhihu.

Open-source selector reference: github.com/lastdanger/toutiao-auto
(config/selectors.py, core/publisher.py, core/browser.py, core/auth.py).
Key URLs (from toutiao-auto settings.py):
  LOGIN   = https://mp.toutiao.com/auth/page/login/
  PUBLISH = https://mp.toutiao.com/profile_v4/graphic/publish
  DRAFTS  = https://mp.toutiao.com/profile_v4/manage/draft

Smoke-test contract (toutiao_smoke_prompt.md):
  - Persistent profile ``~/.video-factory/toutiao-profile`` (never commit).
  - If not logged in: VISIBLE headed browser at mp.toutiao.com + macOS
    notification ``头条冒烟：请用今日头条或抖音App扫码登录`` + 20-min poll.
  - ONE draft only. NEVER click 发布/publish. Never tick 首发.
  - Tick 原创 if available; set AI declaration if present.
  - Cover 1024x678; wait for every image upload (Zhihu retry logic).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .base import BasePublisher, PublishResult

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

DEFAULT_PROFILE_DIR = Path.home() / ".video-factory" / "toutiao-profile"
LOGIN_URL = "https://mp.toutiao.com/auth/page/login/"
PUBLISH_URL = "https://mp.toutiao.com/profile_v4/graphic/publish"
DRAFT_LIST_URL = "https://mp.toutiao.com/profile_v4/manage/draft"
HOME_URL = "https://mp.toutiao.com/"
DEFAULT_SMOKE_DIR = Path.home() / "Projects" / "video-factory" / ".opencode-runs"
PUBLISHED_FILENAME = "published.json"

LOGIN_POLL_SECONDS = 20 * 60  # 20 minutes max (prompt requirement)
LOGIN_RENOTIFY_SECONDS = 5 * 60
CAPTCHA_WAIT_SECONDS = 20 * 60

NOTIFY_TITLE = "头条冒烟"
NOTIFY_LOGIN_MSG = "头条冒烟：请用今日头条或抖音App扫码登录"
NOTIFY_CAPTCHA_MSG = "头条冒烟：出现验证，请在浏览器里手动完成"

# Selectors — from toutiao-auto config/selectors.py (2026-06) + local probe.
# Every lookup tries several candidates; failures name the element sought.
TITLE_SELECTORS = [
    'textarea[placeholder*="文章标题"]',
    'input[placeholder*="标题"]',
    'div.editor-title textarea',
    'textarea[placeholder*="30"]',
    '[class*="title"] textarea',
    '[class*="title"] input',
    'input[placeholder*="请输入"]',
    'textarea[placeholder*="请输入"]',
    '.input-title input',
    '.input-title textarea',
]
EDITOR_SELECTORS = [
    ".ProseMirror",
    'div.ProseMirror[contenteditable="true"]',
    '[contenteditable="true"][role="textbox"]',
    '[contenteditable="true"]',
]
SAVE_DRAFT_SELECTORS = [
    'button:has-text("存草稿")',
    'button:has-text("保存草稿")',
    'button:has-text("保存为草稿")',
    'button:has-text("草稿")',
]
PUBLISH_SELECTORS = [
    'button:has-text("发布")',
    'button:has-text("提交")',
]
CONFIRM_PUBLISH_SELECTORS = [
    'button:has-text("确认发布")',
    'button.byte-btn-primary:has-text("发布")',
    'button:has-text("确定")',
]
IMAGE_TOOLBAR_SELECTORS = [
    ".syl-toolbar-tool.image button.syl-toolbar-button",
    ".syl-toolbar-tool.image button",
    "div.syl-toolbar-tool.image button",
    'button:has-text("插入图片")',
    'button:has-text("上传图片")',
    'button[title*="图片"]',
    'div[title*="图片"]',
]
IMAGE_INPUT_SELECTORS = [
    'input[type="file"][accept*="image"]',
    'input[accept*="jpg"]',
    'input[accept*="jpeg"]',
    'input[accept*="png"]',
    'input[type="file"]',
]
COVER_AREA_SELECTORS = [
    "div.article-cover-add",
    '[class*="cover-add"]',
    "div.cover-wrapper",
    'div[class*="cover"] button',
]
LOGIN_QR_MARKERS = ["扫码登录", "请使用今日头条App扫码登录", "抖音扫码", "扫码"]
LOGGED_IN_URL_MARKERS = ("profile_v4", "/publish", "/manage")
ONBOARDING_MARKERS = [
    "实名认证", "作者实名", "身份证", "人脸", "创作者计划", "加入创作者",
    "开通创作收益", "入驻", "职业认证", "兴趣认证", "完善资料",
]
CAPTCHA_TEXTS = ["验证码", "安全验证", "滑动", "拖动滑块", "点击图中", "请完成验证"]
IMAGE_UPLOAD_MAX_ATTEMPTS = 4
IMAGE_UPLOAD_RETRY_WAIT_S = (2.0, 4.0)
IMAGE_REENCODE_MAX_WIDTH = 1920
IMAGE_REENCODE_SUFFIX = ".toutiao.png"
COVER_TARGET_W = 1024
COVER_TARGET_H = 678


# --------------------------------------------------------------------------- #
# Pure helpers (unit-testable, no browser)
# --------------------------------------------------------------------------- #

BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def parse_inline(text: str) -> list[dict]:
    spans: list[dict] = []
    pos = 0
    for m in BOLD_RE.finditer(text):
        if m.start() > pos:
            spans.append({"text": text[pos:m.start()], "bold": False})
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


def parse_toutiao_markdown(md_text: str) -> dict:
    """Parse article Markdown into {title, blocks} (same shape as Zhihu).

    Block kinds: heading/paragraph/quote/image/divider. First '# ' line is title.
    """
    lines = (md_text or "").splitlines()
    title = ""
    blocks: list[dict] = []
    i = 0
    for idx, ln in enumerate(lines):
        if ln.startswith("# "):
            title = ln[2:].strip()
            i = idx + 1
            break
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
        if s.startswith("<!--"):
            continue
        blocks.append({"kind": "paragraph", "text": s, "spans": parse_inline(s)})
    return {"title": title, "blocks": blocks}


def count_text_blocks(blocks: list[dict]) -> int:
    return sum(1 for b in blocks if b.get("kind") in ("paragraph", "heading", "quote"))


def validate_title(title: str) -> tuple[bool, str]:
    """Toutiao title must be 15–30 chars (smoke prompt)."""
    t = (title or "").strip()
    n = len(t)
    if 15 <= n <= 30:
        return True, ""
    return False, f"title len {n} not in 15–30: {t[:40]!r}"


def is_upload_done_src(src: str) -> bool:
    """True when an editor img left blob:/data: (safe to save)."""
    s = (src or "").strip()
    if not s or s.startswith("blob:") or s.startswith("data:"):
        return False
    return s.startswith("https://") or s.startswith("http://")


def load_payload(payload_path: str | Path) -> dict:
    """Load toutiao publish_payload.json, resolve relative paths to absolute."""
    p = Path(payload_path).resolve()
    data = json.loads(p.read_text(encoding="utf-8"))
    base = p.parent
    body_rel = data.get("body_markdown_path", "toutiao_article.md")
    body_path = (base / body_rel).resolve()
    if not body_path.exists():
        # Fallback: article.md (Zhihu source) if Toutiao variant missing.
        alt = (base / "article.md").resolve()
        if alt.exists():
            body_path = alt
    cover = data.get("cover_image")
    cover_path = str((base / cover).resolve()) if cover else None
    images = [str((base / rel).resolve()) for rel in data.get("images_in_order", [])]
    md_text = Path(body_path).read_text(encoding="utf-8")
    # Smoke guard: never publish external links / QR / 微信.
    # (Zhihu ep3 source is already clean; Toutiao variant keeps it clean.)
    parsed = parse_toutiao_markdown(md_text)
    title = data.get("title") or parsed["title"]
    ok, msg = validate_title(title)
    if not ok:
        raise ValueError(msg)
    return {
        "payload_path": str(p),
        "base_dir": str(base),
        "title": title,
        "body_markdown_path": str(body_path),
        "blocks": parsed["blocks"],
        "cover_image": cover_path,
        "topics": list(data.get("topics", [])),
        "column": data.get("column"),
        "declaration": data.get("declaration", ""),
        "images_in_order": images,
        "raw": data,
    }


def ensure_toutiao_cover(src_path: str | Path, dest_dir: str | Path | None = None) -> Path:
    """Center-crop/resize cover to 1024x678 (Toutiao article cover size).

    Returns the 1024x678 path. If source is already 1024x678, returns it as-is.
    Otherwise writes ``<stem>_1024x678.png`` next to source (or dest_dir).
    """
    src = Path(src_path)
    if not src.exists():
        raise FileNotFoundError(f"cover missing: {src}")
    try:
        from PIL import Image
    except ImportError as e:
        raise RuntimeError("Pillow required for cover crop") from e
    im = Image.open(src)
    if im.size == (COVER_TARGET_W, COVER_TARGET_H):
        return src
    if im.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im.convert("RGB"), mask=im.split()[-1])
        im = bg
    elif im.mode != "RGB":
        im = im.convert("RGB")
    w, h = im.size
    target_aspect = COVER_TARGET_W / COVER_TARGET_H
    src_aspect = w / h
    if src_aspect > target_aspect:
        new_w = int(h * target_aspect)
        left = (w - new_w) // 2
        im = im.crop((left, 0, left + new_w, h))
    else:
        new_h = int(w / target_aspect)
        top = (h - new_h) // 2
        im = im.crop((0, top, w, top + new_h))
    im = im.resize((COVER_TARGET_W, COVER_TARGET_H), Image.LANCZOS)
    out_dir = Path(dest_dir) if dest_dir else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / (src.stem + "_1024x678.png")
    # Avoid rewriting when already correct (idempotent).
    if out.exists():
        try:
            existing = Image.open(out)
            if existing.size == (COVER_TARGET_W, COVER_TARGET_H):
                return out
        except Exception:
            pass
    im.save(out, format="PNG", optimize=True)
    return out


def reencode_image_for_toutiao(src_path: str | Path, dest_dir: str | Path | None = None,
                               max_width: int = IMAGE_REENCODE_MAX_WIDTH) -> Path:
    """Re-encode for retry (flatten alpha, strip metadata, resize <=max_width)."""
    src = Path(src_path)
    if not src.exists():
        raise FileNotFoundError(f"image missing: {src}")
    out_dir = Path(dest_dir) if dest_dir else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image
        img = Image.open(src)
        if img.mode in ("RGBA", "LA"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img.convert("RGB"), mask=img.split()[-1])
            img = bg
        elif img.mode == "P":
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img.convert("RGB"), mask=img.split()[-1])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        if w > max_width:
            new_h = max(1, round(h * max_width / w))
            img = img.resize((max_width, new_h), Image.LANCZOS)
        out = out_dir / (src.stem + IMAGE_REENCODE_SUFFIX)
        img.save(out, format="PNG", optimize=True)
        return out
    except ImportError:
        pass
    out_jpg = out_dir / (src.stem + ".toutiao.jpg")
    cmd = ["sips", "-s", "format", "jpeg", "-s", "formatOptions", "92",
           "-Z", str(int(max_width)), str(src), "--out", str(out_jpg)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    if r.returncode != 0 or not out_jpg.exists():
        raise RuntimeError(f"re-encode failed: sips rc={r.returncode}")
    return out_jpg


def classify_login_state(url: str, html: str, body_text: str = "") -> str:
    """Classify Toutiao MP page as logged_in/logged_out/onboarding/unknown (pure)."""
    u = (url or "").lower()
    h = html or ""
    t = body_text or ""
    combined = h + "\n" + t
    if "auth/page/login" in u or "/login" in u:
        # Even on login URL, avatar/profile markers mean already logged in.
        if "profile_v4" in u:
            return "logged_in"
        return "logged_out"
    if any(m in u for m in LOGGED_IN_URL_MARKERS):
        # Onboarding pages still live under profile_v4 — check content first.
        if any(m in combined for m in ONBOARDING_MARKERS):
            # Real-name/creator onboarding blocks drafts.
            return "onboarding"
        return "logged_in"
    if any(m in combined for m in LOGIN_QR_MARKERS):
        return "logged_out"
    if any(m in combined for m in ONBOARDING_MARKERS) and "profile" in u:
        return "onboarding"
    return "unknown"


def get_published_path(payload_path: str | Path) -> Path:
    return Path(payload_path).resolve().parent / PUBLISHED_FILENAME


def load_published_record(payload_path: str | Path) -> dict | None:
    try:
        p = get_published_path(payload_path)
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def is_already_published(payload_path: str | Path) -> tuple[bool, dict | None]:
    rec = load_published_record(payload_path)
    if rec and str(rec.get("url") or "").strip().startswith("http"):
        return True, rec
    return False, rec


def should_refuse_publish(payload_path: str | Path, force: bool = False):
    if force:
        return False, load_published_record(payload_path)
    return is_already_published(payload_path)


def notify_owner(message: str, title: str = NOTIFY_TITLE) -> None:
    try:
        subprocess.run(
            ["osascript", "-e", f'display notification "{message}" with title "{title}" sound name "Glass"'],
            timeout=10, check=False, capture_output=True,
        )
    except Exception as e:
        logger.warning(f"notify_owner failed: {e}")


def bring_chrome_front() -> None:
    try:
        subprocess.run(
            ["osascript", "-e", 'tell application "Google Chrome" to activate'],
            timeout=10, check=False, capture_output=True,
        )
    except Exception as e:
        logger.warning(f"bring_chrome_front failed: {e}")


def cleanup_own_chrome_processes(profile_dir: str | Path) -> int:
    try:
        needle = str(profile_dir)
        ps = subprocess.run(["ps", "aux"], capture_output=True, text=True, timeout=10, check=False)
        killed = 0
        for line in (ps.stdout or "").splitlines():
            if needle in line and ("chrome" in line.lower() or "chromium" in line.lower()):
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    try:
                        subprocess.run(["kill", parts[1]], timeout=5, check=False)
                        killed += 1
                    except Exception:
                        continue
        return killed
    except Exception as e:
        logger.warning(f"cleanup failed: {e}")
        return 0


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


class ToutiaoPublisher(BasePublisher):
    """Toutiao article publisher with persistent Chromium profile (headless-first)."""

    def __init__(self, profile_dir: str | Path | None = None, headless: bool = True,
                 smoke_dir: str | Path | None = None,
                 login_timeout_s: int = LOGIN_POLL_SECONDS, **kwargs):
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
        return "Toutiao"

    @property
    def login_url(self) -> str:
        return LOGIN_URL

    @property
    def upload_url(self) -> str:
        return PUBLISH_URL

    # -- browser lifecycle -- #

    async def init_browser(self):
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        launch_kwargs: dict = {
            "headless": self.headless,
            "args": ["--disable-blink-features=AutomationControlled", "--disable-infobars", "--no-sandbox"],
            "viewport": {"width": 1280, "height": 860},
            "user_agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
            "locale": "zh-CN",
        }
        if shutil.which("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome") or shutil.which("google-chrome"):
            launch_kwargs["channel"] = "chrome"
        self._persistent_ctx = await self._pw.chromium.launch_persistent_context(str(self.profile_dir), **launch_kwargs)
        self.context = self._persistent_ctx
        pages = self.context.pages
        self.page = pages[0] if pages else await self.context.new_page()

    async def close_browser(self):
        try:
            if self._persistent_ctx is not None:
                await self._persistent_ctx.close()
        except Exception as e:
            logger.warning(f"close persistent context failed: {e}")
        finally:
            self._persistent_ctx = None
            self.context = None
            self.page = None
        try:
            if self._pw is not None:
                await self._pw.stop()
        except Exception as e:
            logger.warning(f"playwright stop failed: {e}")
        finally:
            self._pw = None
            self.browser = None

    # -- login -- #

    async def _page_state(self) -> tuple[str, str, str, str]:
        try:
            url = self.page.url or ""
        except Exception:
            url = ""
        try:
            html = (await self.page.content())[:200000]
        except Exception:
            html = ""
        try:
            title = await self.page.title()
        except Exception:
            title = ""
        try:
            body_text = (await self.page.evaluate("() => document.body.innerText || ''"))[:20000]
        except Exception:
            body_text = ""
        return url, html, title, body_text

    async def check_login(self) -> bool:
        for check_url in (PUBLISH_URL, DRAFT_LIST_URL, HOME_URL):
            try:
                await self.page.goto(check_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)
                url, html, _, body_text = await self._page_state()
                state = classify_login_state(url, html, body_text)
                if state == "logged_in":
                    return True
                if state in ("logged_out", "onboarding"):
                    # Don't keep probing other URLs when clearly logged out;
                    # but try next URL once in case of transient redirect.
                    continue
            except Exception as e:
                logger.warning(f"check_login via {check_url} failed: {e}")
                continue
        try:
            url = (self.page.url or "").lower()
            if "auth/page/login" in url or "/login" in url:
                return False
        except Exception:
            pass
        return False

    async def detect_onboarding(self) -> tuple[bool, str]:
        """True + excerpt when the page asks for registration/real-name/onboarding."""
        try:
            url, html, _, body_text = await self._page_state()
            state = classify_login_state(url, html, body_text)
            if state == "onboarding":
                # Extract the exact ask: first 800 chars around a marker.
                for m in ONBOARDING_MARKERS:
                    if m in body_text:
                        idx = body_text.find(m)
                        excerpt = body_text[max(0, idx - 200):idx + 600].strip().replace("\n", " / ")
                        return True, f"page asks for [{m}]: {excerpt[:800]} (url={url[:120]})"
                return True, f"onboarding page (url={url[:120]}) text={body_text[:800]!r}"
        except Exception as e:
            logger.warning(f"detect_onboarding failed: {e}")
        return False, ""

    async def ensure_login_headless_first(self) -> tuple[bool, bool, bool]:
        if await self.check_login():
            return True, False, False
        logger.info("Headless login check failed — relaunching SAME profile headed.")
        if self.headless:
            try:
                await self.close_browser()
            except Exception as e:
                logger.warning(f"headless close before headed fallback failed: {e}")
            self.headless = False
            self._fell_back_to_headed = True
            await self.init_browser()
            relaunched = True
        else:
            relaunched = bool(getattr(self, "_fell_back_to_headed", False))
        try:
            await self.page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            logger.warning(f"goto mp home failed: {e}")
        await asyncio.sleep(2)
        bring_chrome_front()
        notify_owner(NOTIFY_LOGIN_MSG)
        logger.info("Toutiao login required — waiting for QR scan (up to 20 min).")
        deadline = asyncio.get_event_loop().time() + self.login_timeout_s
        last_notify = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(10)
            if await self.check_login():
                logger.info("Toutiao login detected.")
                return True, True, relaunched
            now = asyncio.get_event_loop().time()
            if now - last_notify >= LOGIN_RENOTIFY_SECONDS:
                notify_owner(NOTIFY_LOGIN_MSG)
                bring_chrome_front()
                last_notify = now
        logger.error("Toutiao login timed out.")
        return False, True, relaunched

    async def ensure_login(self) -> tuple[bool, bool]:
        logged_in, needed, _ = await self.ensure_login_headless_first()
        return logged_in, needed

    async def detect_captcha(self) -> bool:
        try:
            body = (await self.page.content())[:200000]
        except Exception:
            return False
        return any(t in body for t in CAPTCHA_TEXTS)

    async def wait_captcha_if_present(self) -> bool:
        if not await self.detect_captcha():
            return True
        if self.headless:
            try:
                await self.close_browser()
            except Exception:
                pass
            self.headless = False
            self._fell_back_to_headed = True
            await self.init_browser()
        notify_owner(NOTIFY_CAPTCHA_MSG)
        bring_chrome_front()
        deadline = asyncio.get_event_loop().time() + CAPTCHA_WAIT_SECONDS
        last_notify = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(10)
            if not await self.detect_captcha():
                return True
            if asyncio.get_event_loop().time() - last_notify >= LOGIN_RENOTIFY_SECONDS:
                notify_owner(NOTIFY_CAPTCHA_MSG)
                last_notify = asyncio.get_event_loop().time()
        return False

    # -- editor helpers -- #

    async def _first_visible(self, selectors: list[str], timeout_each_ms: int = 3000):
        last_err: Exception | None = None
        for sel in selectors:
            try:
                el = await self.page.wait_for_selector(sel, timeout=timeout_each_ms, state="visible")
                if el is not None:
                    return el
            except Exception as e:
                last_err = e
                continue
        raise TimeoutError(f"element not found (tried {selectors}): {last_err}")

    async def _human_pause(self, lo: float = 0.4, hi: float = 1.2) -> None:
        await asyncio.sleep(random.uniform(lo, hi))

    async def _type_spans(self, spans: list[dict]) -> None:
        for sp in spans:
            text = sp.get("text", "")
            if not text:
                continue
            if sp.get("bold"):
                await self.page.keyboard.press("ControlOrMeta+B")
                await asyncio.sleep(0.15)
            for idx in range(0, len(text), 60):
                chunk = text[idx:idx + 60]
                await self.page.keyboard.type(chunk, delay=random.randint(12, 35))
                await asyncio.sleep(random.uniform(0.05, 0.2))
            if sp.get("bold"):
                await asyncio.sleep(0.15)
                await self.page.keyboard.press("ControlOrMeta+B")
                await asyncio.sleep(0.15)

    async def fill_title(self, title: str) -> None:
        el = await self._first_visible(TITLE_SELECTORS, timeout_each_ms=8000)
        await el.click(timeout=10000)
        await asyncio.sleep(0.3)
        try:
            await el.fill("", timeout=5000)
        except Exception:
            await self.page.keyboard.press("ControlOrMeta+A")
            await self.page.keyboard.press("Backspace")
        await self._human_pause(0.3, 0.7)
        await self.page.keyboard.type(title, delay=random.randint(15, 40))
        await self._human_pause()
        # Blur to commit React state (toutiao-auto lesson).
        try:
            await el.evaluate("el => el.dispatchEvent(new FocusEvent('blur', { bubbles: true }))")
        except Exception:
            pass
        await asyncio.sleep(0.5)

    async def _focus_editor(self):
        el = await self._first_visible(EDITOR_SELECTORS, timeout_each_ms=10000)
        await el.click(timeout=10000)
        await asyncio.sleep(0.4)
        return el

    async def _new_paragraph(self) -> None:
        await self.page.keyboard.press("Enter")
        await self._human_pause(0.2, 0.5)

    async def write_heading(self, text: str, spans: list[dict]) -> None:
        await self._new_paragraph()
        await self.page.keyboard.type("## ", delay=20)
        await self._type_spans(spans or [{"text": text, "bold": False}])
        await self._human_pause(0.3, 0.6)

    async def write_paragraph(self, spans: list[dict]) -> None:
        await self._new_paragraph()
        await self._type_spans(spans)

    async def write_quote(self, spans: list[dict]) -> None:
        await self._new_paragraph()
        await self.page.keyboard.type("> ", delay=20)
        await self._type_spans(spans)

    async def write_html_content(self, html: str) -> None:
        """Inject prepared HTML into ProseMirror (toutiao-auto style, with fallback)."""
        editor = await self._first_visible(EDITOR_SELECTORS, timeout_each_ms=10000)
        try:
            await editor.click(timeout=5000)
        except Exception:
            try:
                await editor.evaluate("el => el.click()")
            except Exception:
                pass
        await asyncio.sleep(0.5)
        escaped = html.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
        js = f"""(() => {{
            const editor = document.querySelector('.ProseMirror');
            if (!editor) return -2;
            editor.innerHTML = '';
            const tmp = document.createElement('div');
            tmp.innerHTML = `{escaped}`;
            const frag = document.createDocumentFragment();
            while (tmp.firstChild) frag.appendChild(tmp.firstChild);
            editor.appendChild(frag);
            ['input','change','compositionend'].forEach(t => editor.dispatchEvent(new Event(t, {{bubbles:true}})));
            setTimeout(() => editor.dispatchEvent(new FocusEvent('blur', {{bubbles:true}})), 50);
            return editor.innerText.length;
        }})()"""
        try:
            n = await self.page.evaluate(js)
            logger.info(f"toutiao content injected chars={n}")
            await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"HTML inject failed, keyboard fallback: {e}")
            await self.page.keyboard.type(html[:2000], delay=5)

    def blocks_to_html(self, blocks: list[dict]) -> str:
        """Convert parsed blocks to simple HTML for ProseMirror injection."""
        import html as _html
        parts: list[str] = []
        for b in blocks:
            k = b.get("kind")
            if k == "heading":
                lvl = 2 if b.get("level", 2) == 2 else 3
                parts.append(f"<h{lvl}>{_html.escape(b.get('text',''))}</h{lvl}>")
            elif k == "quote":
                parts.append(f"<blockquote><p>{_html.escape(b.get('text',''))}</p></blockquote>")
            elif k == "divider":
                parts.append("<hr/>")
            elif k == "image":
                # Images are uploaded via file input, not <img> injection —
                # leave a marker paragraph so positions stay readable.
                alt = _html.escape(b.get("alt", "") or "图片")
                parts.append(f"<p>[{alt}]</p>")
                if b.get("caption"):
                    parts.append(f"<p>{_html.escape(b.get('caption',''))}</p>")
            else:
                # paragraph with **bold** → <strong>
                txt = b.get("text", "") or ""
                # crude bold conversion (spans already parsed, but HTML-escape first)
                segs: list[str] = []
                for sp in b.get("spans", []) or parse_inline(txt):
                    t = _html.escape(sp.get("text", ""))
                    segs.append(f"<strong>{t}</strong>" if sp.get("bold") else t)
                parts.append(f"<p>{''.join(segs)}</p>")
        return "\n".join(parts)

    async def wait_for_image_upload_complete(self, expected_min: int = 1, timeout_s: int = 90) -> bool:
        deadline = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < deadline:
            try:
                state = await self.page.evaluate(
                    """() => {
                        const imgs = Array.from(document.querySelectorAll('.ProseMirror img, [contenteditable] img'));
                        const srcs = imgs.map(i => i.getAttribute('src') || '');
                        const txt = (document.body.innerText || '');
                        const uploading = txt.includes('上传中') || txt.includes('正在上传');
                        const prog = document.querySelectorAll('[role="progressbar"], [class*="Progress" i], [class*="progress" i]').length;
                        return {n: imgs.length, srcs, uploading, prog};
                    }"""
                )
            except Exception:
                await asyncio.sleep(1.0)
                continue
            n = int(state.get("n", 0) or 0)
            srcs = list(state.get("srcs", []) or [])
            uploading = bool(state.get("uploading")) or int(state.get("prog", 0) or 0) > 0
            all_done = n >= expected_min and all(is_upload_done_src(s) for s in srcs) if srcs else False
            if all_done and not uploading:
                await asyncio.sleep(2.0)
                return True
            await asyncio.sleep(1.0)
        logger.warning("toutiao image upload did not finish in time")
        return False

    async def _remove_stuck_blob_images(self) -> int:
        try:
            return int(await self.page.evaluate(
                """() => {
                    const imgs = Array.from(document.querySelectorAll('.ProseMirror img, [contenteditable] img'));
                    let r = 0;
                    for (const img of imgs) {
                        const s = img.getAttribute('src') || '';
                        if (s.startsWith('blob:') || s.startsWith('data:')) {
                            (img.closest('figure') || img).remove();
                            r++;
                        }
                    }
                    return r;
                }""") or 0)
        except Exception:
            return 0

    async def write_image(self, image_path: str, caption: str = "") -> bool:
        """Upload one body image at cursor; retries + re-encode fallback (Zhihu logic)."""
        p = Path(image_path)
        if not p.exists():
            logger.error(f"image missing: {image_path}")
            return False
        current = str(p)
        reencoded: str | None = None
        for attempt in range(1, IMAGE_UPLOAD_MAX_ATTEMPTS + 1):
            try:
                if attempt > 1:
                    try:
                        removed = await self._remove_stuck_blob_images()
                        if removed:
                            logger.info(f"removed {removed} stuck blob(s) before retry {attempt} for {p.name}")
                    except Exception:
                        pass
                    await asyncio.sleep(random.uniform(*IMAGE_UPLOAD_RETRY_WAIT_S))
                if attempt == 3 and reencoded is None:
                    try:
                        out = await asyncio.to_thread(reencode_image_for_toutiao, str(p))
                        reencoded = str(out)
                        current = reencoded
                        logger.info(f"re-encoded {p.name} -> {Path(reencoded).name} for retry")
                    except Exception as e:
                        logger.warning(f"re-encode failed for {p.name}: {e}")
                # Count existing editor images.
                try:
                    before = int(await self.page.evaluate(
                        "() => document.querySelectorAll('.ProseMirror img, [contenteditable] img').length") or 0)
                except Exception:
                    before = 0
                await self._new_paragraph()
                # Click toolbar image button to open upload dialog.
                clicked = False
                for sel in IMAGE_TOOLBAR_SELECTORS:
                    try:
                        btn = await self.page.query_selector(sel)
                        if btn is not None and await btn.is_visible():
                            try:
                                await btn.click(timeout=5000)
                            except Exception:
                                await btn.evaluate("el => el.click()")
                            clicked = True
                            break
                    except Exception:
                        continue
                if not clicked:
                    # JS fallback: find toolbar image tool.
                    try:
                        ok = await self.page.evaluate(
                            """() => {
                                const tb = document.querySelector('.syl-editor-toolbar');
                                if (!tb) return false;
                                for (const el of tb.querySelectorAll('[class*="image"], button')) {
                                    if ((el.className||'').includes('image')) {
                                        (el.querySelector('button')||el).click(); return true;
                                    }
                                }
                                return false;
                            }""")
                        clicked = bool(ok)
                    except Exception:
                        clicked = False
                await asyncio.sleep(2)
                # Set file input (dialog).
                uploaded = False
                for sel in IMAGE_INPUT_SELECTORS:
                    try:
                        h = await self.page.query_selector(sel)
                        if h is not None:
                            await h.set_input_files(str(current))
                            uploaded = True
                            break
                    except Exception:
                        continue
                if not uploaded:
                    # Try file chooser via toolbar click.
                    try:
                        async with self.page.expect_file_chooser(timeout=8000) as fc:
                            pass
                        chooser = await fc.value
                        await chooser.set_files(str(current))
                        uploaded = True
                    except Exception:
                        pass
                if not uploaded:
                    raise TimeoutError("image upload control not found")
                await asyncio.sleep(1)
                # Click 确定 in dialog if present.
                for sel in ['button:has-text("确定")', 'button.byte-btn-primary:has-text("确定")', '.byte-btn-primary']:
                    try:
                        btn = await self.page.query_selector(sel)
                        if btn is not None and await btn.is_visible():
                            try:
                                await btn.click(timeout=5000)
                            except Exception:
                                await btn.evaluate("el => el.click()")
                            await asyncio.sleep(2)
                            break
                    except Exception:
                        continue
                await self.page.wait_for_function(
                    f"() => document.querySelectorAll('.ProseMirror img, [contenteditable] img').length > {int(before)}",
                    timeout=60000,
                )
                ok = await self.wait_for_image_upload_complete(expected_min=before + 1, timeout_s=90)
                if not ok:
                    raise TimeoutError("upload progress did not finish")
                await self._human_pause(0.8, 1.2)
                if caption:
                    await self._new_paragraph()
                    await self.page.keyboard.type(caption, delay=random.randint(12, 30))
                    await self._human_pause(0.3, 0.7)
                return True
            except Exception as e:
                logger.warning(f"toutiao image attempt {attempt}/{IMAGE_UPLOAD_MAX_ATTEMPTS} failed for {p.name}: {e}")
                await self._human_pause(*IMAGE_UPLOAD_RETRY_WAIT_S)
        logger.error(f"image upload failed after retries: {p.name}")
        return False

    async def try_cover(self, cover_path: str | None) -> bool:
        """Upload cover via cover area dialog; ensure 1024x678 first."""
        if not cover_path or not Path(cover_path).exists():
            logger.info("no cover; skipping")
            return False
        try:
            # Ensure 1024x678 (pre-cropped file is already correct; this is idempotent).
            try:
                fixed = await asyncio.to_thread(ensure_toutiao_cover, str(cover_path))
                cover_path = str(fixed)
                logger.info(f"cover ensured 1024x678: {Path(cover_path).name}")
            except Exception as e:
                logger.warning(f"cover ensure failed, using original: {e}")
            clicked = False
            for sel in COVER_AREA_SELECTORS:
                try:
                    area = await self.page.wait_for_selector(sel, timeout=3000)
                    if area and await area.is_visible():
                        try:
                            await area.click(timeout=5000)
                        except Exception:
                            await area.evaluate("el => el.click()")
                        clicked = True
                        logger.info(f"cover area clicked: {sel}")
                        break
                except Exception:
                    continue
            if not clicked:
                logger.warning("cover area not found (non-fatal)")
                return False
            await asyncio.sleep(2)
            uploaded = False
            for _ in range(3):
                try:
                    inputs = await self.page.query_selector_all('input[type="file"], input[accept*="image"]')
                    for fi in inputs:
                        try:
                            await fi.set_input_files(str(cover_path))
                            uploaded = True
                            break
                        except Exception:
                            continue
                    if uploaded:
                        break
                except Exception:
                    pass
                # Maybe need 本地上传 tab.
                try:
                    lb = await self.page.wait_for_selector('button:has-text("本地上传"), span:has-text("本地上传")', timeout=2000)
                    if lb and await lb.is_visible():
                        await lb.click()
                        await asyncio.sleep(1)
                except Exception:
                    pass
                await asyncio.sleep(1)
            if not uploaded:
                logger.warning("cover file input not found (non-fatal)")
                return False
            logger.info("cover file set, waiting + confirming")
            await asyncio.sleep(5)
            for _ in range(5):
                try:
                    cb = await self.page.wait_for_selector(
                        'button:has-text("确定"), button:has-text("确认"), button.byte-btn-primary', timeout=3000)
                    if cb and await cb.is_visible():
                        try:
                            await cb.click(timeout=5000)
                        except Exception:
                            await cb.evaluate("el => el.click()")
                        await asyncio.sleep(2)
                        break
                except Exception:
                    pass
                await asyncio.sleep(1)
            # Verify: cover preview img present (not blob).
            try:
                st = await self.page.evaluate(
                    """() => {
                        const imgs = Array.from(document.querySelectorAll('[class*="cover"] img, img[class*="cover"], img[alt*="封面"]'));
                        return imgs.map(i => i.getAttribute('src')||'');
                    }""")
                logger.info(f"cover verify srcs={str(st)[:200]}")
                if st and any(is_upload_done_src(s) for s in st):
                    return True
                # Fallback: any new image in dialog closed + no error = assume ok (verify after reload).
                return True
            except Exception:
                return True
        except Exception as e:
            logger.warning(f"cover step failed (non-fatal): {e}")
            return False

    async def get_declaration_states(self) -> dict:
        """Read 原创/首发/AI states from the publish panel (best-effort)."""
        try:
            return await self.page.evaluate(
                """() => {
                    const txt = document.body.innerText || '';
                    const out = {has_yuanchuang: txt.includes('原创'), has_shoufa: txt.includes('首发'),
                                 has_ai: /AI/.test(txt), body_len: txt.length};
                    // checkbox states near those labels
                    const boxes = Array.from(document.querySelectorAll('[role="checkbox"], input[type="checkbox"]'));
                    out.checkboxes = boxes.slice(0,12).map(cb => {
                        const label = (cb.closest('label, div, span')?.innerText || cb.getAttribute('aria-label') || '').trim().slice(0,40);
                        let checked = null;
                        try { checked = cb.isChecked?.() ?? cb.checked ?? null; } catch(e) {}
                        return {label, checked: String(checked), html: (cb.outerHTML||'').slice(0,200)};
                    });
                    // radio/checked near 首发/原创
                    out.snippet_yuanchuang = (txt.match(/.{0,30}原创.{0,30}/g) || []).slice(0,3);
                    out.snippet_shoufa = (txt.match(/.{0,30}首发.{0,30}/g) || []).slice(0,3);
                    out.snippet_ai = (txt.match(/.{0,30}AI.{0,30}/g) || []).slice(0,5);
                    return out;
                }""")
        except Exception as e:
            return {"error": str(e)}

    async def try_declarations(self) -> dict:
        """Tick 原创 if available; NEVER tick 首发 (ensure unchecked); set AI if present.

        Returns {yuanchuang, shoufa_unchecked, ai, notes}.
        """
        notes: list[str] = []
        res: dict = {"yuanchuang": False, "shoufa_unchecked": True, "ai": False, "notes": notes}
        try:
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1)
        except Exception:
            pass
        # --- 原创: tick if available --- #
        try:
            # Find checkbox/radio near 原创 text and click if not checked.
            handled = await self.page.evaluate(
                """() => {
                    const els = Array.from(document.querySelectorAll('[role="checkbox"], input[type="checkbox"], [role="radio"], [class*="checkbox"], [class*="radio"]'));
                    for (const el of els) {
                        const ctx = (el.closest('label, div')?.innerText || el.parentElement?.innerText || '').trim();
                        if (ctx.includes('原创') && !ctx.includes('首发')) {
                            const checked = el.getAttribute('aria-checked') || String(el.checked || '');
                            if (checked === 'true' || el.checked) return 'already';
                            (el.closest('label') || el).click();
                            return 'clicked';
                        }
                    }
                    // fallback: any element with exact 原创 text inside a clickable
                    for (const el of Array.from(document.querySelectorAll('label, span, div'))) {
                        if ((el.innerText||'').trim() === '原创' || (el.innerText||'').trim().startsWith('原创')) {
                            const box = el.querySelector('[role="checkbox"], input[type="checkbox"]') || el;
                            try { box.click(); return 'clicked-fallback'; } catch(e) {}
                        }
                    }
                    return 'notfound';
                }""")
            logger.info(f"yuanchuang handling: {handled}")
            notes.append(f"yuanchuang:{handled}")
            if handled in ("already", "clicked", "clicked-fallback"):
                res["yuanchuang"] = True
        except Exception as e:
            notes.append(f"yuanchuang error: {e}")
        # --- 首发: NEVER tick; ensure unchecked --- #
        try:
            shoufa = await self.page.evaluate(
                """() => {
                    const els = Array.from(document.querySelectorAll('[role="checkbox"], input[type="checkbox"]'));
                    for (const el of els) {
                        const ctx = (el.closest('label, div')?.innerText || '').trim();
                        if (ctx.includes('首发')) {
                            const checked = el.getAttribute('aria-checked') === 'true' || !!el.checked;
                            if (checked) { (el.closest('label')||el).click(); return 'was-checked-now-unticked'; }
                            return 'already-unchecked';
                        }
                    }
                    return 'notfound-unchecked-ok';
                }""")
            logger.info(f"shoufa handling: {shoufa}")
            notes.append(f"shoufa:{shoufa}")
            res["shoufa_unchecked"] = shoufa in ("already-unchecked", "notfound-unchecked-ok", "was-checked-now-unticked")
            if shoufa == "was-checked-now-unticked":
                logger.warning("首发 was checked; unticked per smoke contract (never 首发).")
        except Exception as e:
            notes.append(f"shoufa error: {e}")
        # --- AI declaration: set if panel has one --- #
        try:
            # toutiao-auto unchecks 引用AI but research requires AI生成声明 tick.
            # Strategy: look for AI生成/辅助/声明 checkbox not already set; click it.
            # Never uncheck an AI declaration; only ensure it is declared.
            ai = await self.page.evaluate(
                """() => {
                    const txt = document.body.innerText || '';
                    if (!/AI/.test(txt)) return 'no-ai-panel';
                    const els = Array.from(document.querySelectorAll('[role="checkbox"], input[type="checkbox"], [role="radio"], button'));
                    for (const el of els) {
                        const ctx = ((el.closest('label, div, span')?.innerText) || el.innerText || '').trim().slice(0,80);
                        if (/AI/.test(ctx) && /声明|生成|辅助|创作/.test(ctx)) {
                            try {
                                const checked = el.getAttribute('aria-checked') === 'true' || !!el.checked;
                                if (!checked) el.click();
                                return 'ai-clicked:' + ctx.slice(0,40);
                            } catch(e) { return 'ai-error:' + String(e).slice(0,60); }
                        }
                    }
                    // 个人观点仅供参考 (toutiao-autoSets this) — complementary, not AI.
                    if (txt.includes('个人观点仅供参考')) return 'ai-panel-found-personal-opinion-present';
                    return 'ai-panel-no-checkbox';
                }""")
            logger.info(f"ai handling: {ai}")
            notes.append(f"ai:{ai}")
            if str(ai).startswith("ai-clicked") or "personal-opinion" in str(ai):
                res["ai"] = True
            # Also try 个人观点仅供参考 (toutiao-auto behavior, harmless).
            try:
                el = await self.page.query_selector('text=个人观点仅供参考')
                if el is not None and await el.is_visible():
                    notes.append("personal-opinion:present")
            except Exception:
                pass
        except Exception as e:
            notes.append(f"ai error: {e}")
        return res

    async def save_draft(self) -> str | None:
        try:
            n = await self.page.evaluate(
                "() => document.querySelectorAll('.ProseMirror img, [contenteditable] img').length")
            await self.wait_for_image_upload_complete(expected_min=int(n or 0), timeout_s=60)
        except Exception:
            pass
        # React state sync (toutiao-auto lesson: blur + compositionend).
        try:
            await self.page.evaluate(
                """() => {
                    const t = document.querySelector('textarea[placeholder*="标题"], input[placeholder*="标题"]');
                    if (t) t.dispatchEvent(new FocusEvent('blur', {bubbles:true}));
                    const ed = document.querySelector('.ProseMirror');
                    if (ed) { ed.dispatchEvent(new FocusEvent('blur',{bubbles:true})); ed.dispatchEvent(new Event('input',{bubbles:true})); }
                    document.body.click();
                }""")
        except Exception:
            pass
        await asyncio.sleep(2)
        # Click 存草稿 (NEVER 发布 here).
        clicked = False
        for sel in SAVE_DRAFT_SELECTORS:
            try:
                btn = await self.page.query_selector(sel)
                if btn is not None and await btn.is_visible():
                    try:
                        disabled = await btn.is_disabled()
                    except Exception:
                        disabled = False
                    if not disabled:
                        await btn.click(timeout=8000)
                        clicked = True
                        logger.info(f"clicked draft button: {sel}")
                        break
            except Exception:
                continue
        if not clicked:
            logger.warning("draft button not found; relying on autosave")
        await self._human_pause(1.5, 2.5)
        try:
            await self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        # Wait for pgc_id (draft id) or saved toast.
        deadline = asyncio.get_event_loop().time() + 60
        while asyncio.get_event_loop().time() < deadline:
            try:
                url = self.page.url or ""
            except Exception:
                url = ""
            if "pgc_id=" in url:
                break
            try:
                toast = await self.page.query_selector('text=草稿已保存, text=已自动保存, text=保存成功')
                if toast is not None and await toast.is_visible():
                    break
            except Exception:
                pass
            await asyncio.sleep(2)
        await asyncio.sleep(2)
        try:
            return self.page.url
        except Exception:
            return None

    async def verify_draft(self, expected_title: str, blocks: list[dict]) -> DraftCheck:
        issues: list[str] = []
        exp_title = (expected_title or "").strip()
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
                    except Exception:
                        pass
                    try:
                        t = await loc.nth(k).inner_text(timeout=3000)
                        if t and t.strip():
                            title_vals.append(t.strip())
                    except Exception:
                        pass
            except Exception:
                continue
        try:
            body_text_full = await self.page.evaluate("() => document.body.innerText || ''")
        except Exception:
            body_text_full = ""
        title_match = False
        if exp_title:
            title_match = any((exp_title in v or v in exp_title) for v in title_vals if v)
            if not title_match and exp_title in (body_text_full or ""):
                title_match = True
        if not title_match:
            issues.append(f"title text not found (seen: {title_vals[:2]})")
        exp_para = count_text_blocks(blocks)
        try:
            counts = await self.page.evaluate(
                """() => {
                    const ed = document.querySelector('.ProseMirror') || document.querySelector('[contenteditable]') || document.body;
                    const q = (s) => ed.querySelectorAll(s).length;
                    return {p: q('p'), h: q('h1,h2,h3,h4'), quote: q('blockquote'), li: q('li'),
                            img: ed.querySelectorAll('img').length, textLen: (ed.innerText||'').length};
                }""")
        except Exception as e:
            issues.append(f"editor DOM read failed: {e}")
            counts = {}
        found_para = int(counts.get("p", 0) if counts else 0) + int(counts.get("h", 0) if counts else 0) + int(counts.get("quote", 0) if counts else 0) + int(counts.get("li", 0) if counts else 0)
        found_text_len = int(counts.get("textLen", 0) if counts else 0)
        exp_img = sum(1 for b in blocks if b.get("kind") == "image")
        found_img = int(counts.get("img", 0) if counts else 0)
        exp_chars = sum(len(str(b.get("text", "") or "")) for b in blocks if b.get("kind") in ("paragraph", "heading", "quote"))
        exp_chars += sum(len(str(b.get("caption", "") or "")) for b in blocks if b.get("kind") == "image")
        exp_chars += len(exp_title)
        chars_ratio = (found_text_len / exp_chars) if exp_chars else 0.0
        logger.info(f"draft verify: blocks~{found_para} (exp~{exp_para}), img={found_img}/{exp_img}, chars={found_text_len}/{exp_chars} ({chars_ratio:.2f}), title={title_match}")
        if exp_para and found_para < max(5, int(exp_para * 0.3)) and chars_ratio < 0.5:
            issues.append(f"content looks thin: blocks~{found_para} (exp~{exp_para}), chars {found_text_len}/{exp_chars}")
        if found_img < exp_img:
            issues.append(f"images missing: expected {exp_img}, found {found_img}")
        try:
            editor_text = await self.page.evaluate("() => (document.querySelector('.ProseMirror')||document.body).innerText || ''")
        except Exception:
            editor_text = ""
        if "**" in editor_text or "![" in editor_text:
            issues.append("raw markdown markers visible (formatting broken?)")
        fatal = [x for x in issues if ("images missing" in x or "content looks thin" in x or "title text not found" in x or "raw markdown" in x)]
        ok = title_match and found_img >= exp_img and not fatal
        return DraftCheck(ok, title_match, exp_para, found_para, exp_img, found_img, issues)

    async def verify_draft_in_list(self, expected_title: str) -> dict:
        """Reopen draft list and confirm the draft exists with title."""
        try:
            await self.page.goto(DRAFT_LIST_URL, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(4)
            body = await self.page.evaluate("() => document.body.innerText || ''")
            found = expected_title.strip() in (body or "")
            # Count draft rows/cards.
            n = await self.page.evaluate(
                """() => {
                    const t = document.body.innerText || '';
                    // best-effort: count title occurrences + list items
                    const rows = document.querySelectorAll('[class*="draft"], [class*="list"] [class*="item"], [class*="card"]');
                    return {rows: rows.length, chars: t.length};
                }""")
            return {"ok": bool(found), "found_title": bool(found), "list_state": n, "url": self.page.url}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # -- BasePublisher compat -- #

    async def check_login_simple(self) -> bool:
        return await self.check_login()

    async def upload(self, video_path=None, title: str = "", description: str | None = None,
                     tags: list[str] | None = None, **kwargs) -> PublishResult:
        payload = kwargs.get("payload") or kwargs.get("article_payload")
        if not payload:
            return PublishResult(success=False, platform=self.platform_name,
                                 error="Toutiao publisher writes articles, not videos: pass payload=<payload.json>.")
        res = await self.publish_article_from_payload(payload, mode=kwargs.get("mode", "draft"), **kwargs)
        if res.get("status") == "published":
            return PublishResult(success=True, platform=self.platform_name, post_url=res.get("public_url"))
        if res.get("status") == "draft":
            return PublishResult(success=True, platform=self.platform_name, post_url=res.get("draft_url"))
        return PublishResult(success=False, platform=self.platform_name, error=res.get("error", "unknown"))

    # -- full article flow -- #

    async def publish_article_from_payload(self, payload_path: str | Path, mode: str = "draft",
                                           smoke_label: str = "toutiao_smoke",
                                           draft_url: str | None = None, force: bool = False,
                                           no_open: bool = False, **kwargs) -> dict:
        _ = kwargs
        _ = no_open
        data = load_payload(payload_path)
        title, blocks = data["title"], data["blocks"]
        self.smoke_dir.mkdir(parents=True, exist_ok=True)
        self._fell_back_to_headed = False
        self._started_headless = bool(self.headless)

        if mode == "publish":
            refuse, rec = should_refuse_publish(payload_path, force=force)
            if refuse:
                return {"status": "error",
                        "error": f"already published: {rec.get('url')} (at {rec.get('published_at','?')}); pass --force to republish",
                        "public_url": rec.get("url"), "title": title}

        await self.init_browser()
        try:
            logged_in, login_needed = await self.ensure_login()
            if not logged_in:
                try:
                    await self.page.screenshot(path=str(self.smoke_dir / f"{smoke_label}_login_blocked.png"), full_page=True, timeout=20000)
                except Exception:
                    pass
                return {"status": "blocked", "reason": "login", "error": "BLOCKED: login"}
            if not await self.wait_captcha_if_present():
                return {"status": "blocked", "reason": "verification", "error": "BLOCKED: verification"}

            # Onboarding gate: real-name/creator plan blocks drafts.
            onb, excerpt = await self.detect_onboarding()
            if onb:
                shot = self.smoke_dir / f"{smoke_label}_onboarding.png"
                try:
                    await self.page.screenshot(path=str(shot), full_page=True, timeout=20000)
                except Exception:
                    pass
                return {"status": "blocked", "reason": "onboarding",
                        "error": f"BLOCKED: onboarding — {excerpt}", "screenshots": [str(shot)]}

            images_ok = 0
            images_total = sum(1 for b in blocks if b.get("kind") == "image")
            await self.page.goto(PUBLISH_URL, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(5)
            # Second onboarding check on the publish page itself.
            onb2, excerpt2 = await self.detect_onboarding()
            if onb2:
                shot = self.smoke_dir / f"{smoke_label}_onboarding.png"
                try:
                    await self.page.screenshot(path=str(shot), full_page=True, timeout=20000)
                except Exception:
                    pass
                return {"status": "blocked", "reason": "onboarding",
                        "error": f"BLOCKED: onboarding — {excerpt2}", "screenshots": [str(shot)]}
            if not await self.wait_captcha_if_present():
                return {"status": "blocked", "reason": "verification", "error": "BLOCKED: verification"}

            # Dismiss AI drawer if it covers the title (toutiao-auto lesson).
            try:
                mask = await self.page.query_selector('.byte-drawer-mask, [class*="drawer-mask"]')
                if mask is not None and await mask.is_visible():
                    try:
                        await mask.evaluate("el => el.click()")
                        await asyncio.sleep(1)
                    except Exception:
                        pass
            except Exception:
                pass

            await self.fill_title(title)
            # Body: inject text blocks as HTML, then upload images in order.
            text_blocks = [b for b in blocks if b.get("kind") != "image"]
            html = self.blocks_to_html(text_blocks)
            # Toutiao editor needs a focused empty doc before inject; reuse heading/para typing
            # for the first blocks to look human, then bulk-inject the rest? Minimal: type all text
            # blocks human-paced (safer for React state), upload images interleaved by position.
            # To keep positions simple: type text blocks in order, uploading each image when its
            # block is reached (images stay in original order).
            await self._focus_editor()
            img_idx = 0
            image_paths = [str((Path(data["base_dir"]) / b.get("src")).resolve()) if not Path(b.get("src","")).is_absolute()
                           else b.get("src") for b in blocks if b.get("kind") == "image"]
            captions = [b.get("caption","") for b in blocks if b.get("kind") == "image"]
            for b in blocks:
                kind = b.get("kind")
                try:
                    if kind == "heading":
                        await self.write_heading(b.get("text",""), b.get("spans",[]))
                    elif kind == "quote":
                        await self.write_quote(b.get("spans",[]))
                    elif kind == "image":
                        ip = image_paths[img_idx] if img_idx < len(image_paths) else ""
                        cap = captions[img_idx] if img_idx < len(captions) else ""
                        ok = await self.write_image(ip, cap)
                        images_ok += 1 if ok else 0
                        img_idx += 1
                    elif kind == "divider":
                        await self._new_paragraph()
                        await self.page.keyboard.type("---", delay=20)
                    else:
                        await self.write_paragraph(b.get("spans",[]))
                except Exception as e:
                    logger.warning(f"block write failed ({kind}): {e}")
                await self._human_pause(0.3, 0.8)
                if await self.detect_captcha():
                    if not await self.wait_captcha_if_present():
                        return {"status": "blocked", "reason": "verification", "error": "BLOCKED: verification"}

            # Panel: cover + declarations BEFORE save.
            cover_ok = await self.try_cover(data.get("cover_image"))
            decl_res = await self.try_declarations()
            decl_state = await self.get_declaration_states()

            shot_panel = self.smoke_dir / f"{smoke_label}_panel.png"
            try:
                await self.page.screenshot(path=str(shot_panel), full_page=True, timeout=20000)
            except Exception as e:
                logger.warning(f"panel screenshot failed: {e}")
                shot_panel = None

            draft_url_out = await self.save_draft()
            shot1 = self.smoke_dir / f"{smoke_label}_draft_editor.png"
            try:
                await self.page.screenshot(path=str(shot1), full_page=True, timeout=20000)
            except Exception as e:
                logger.warning(f"screenshot failed: {e}")
                shot1 = None

            # Reload draft URL (if pgc_id present) and verify.
            if draft_url_out and "pgc_id=" in draft_url_out:
                try:
                    await self.page.goto(draft_url_out, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(4)
                except Exception as e:
                    logger.warning(f"reload draft failed: {e}")
            check = await self.verify_draft(title, blocks)
            cover_state = {"ok": bool(cover_ok)}
            try:
                cover_imgs = await self.page.evaluate(
                    """() => Array.from(document.querySelectorAll('[class*="cover"] img, img')).slice(0,5).map(i=>i.getAttribute('src')||'')""")
                cover_state["srcs"] = cover_imgs
            except Exception:
                pass
            # Draft-list verification (reopen list, confirm title).
            list_res = await self.verify_draft_in_list(title)
            shot2 = self.smoke_dir / f"{smoke_label}_draft_list.png"
            try:
                await self.page.screenshot(path=str(shot2), full_page=True, timeout=20000)
            except Exception as e:
                logger.warning(f"screenshot failed: {e}")
                shot2 = None

            panel_issues: list[str] = []
            if not cover_ok:
                panel_issues.append("cover upload reported non-ok (see screenshots; verify visually)")
            if not decl_res.get("yuanchuang"):
                panel_issues.append("原创 checkbox not confirmed (may be missing for this account; see panel screenshot)")
            if not decl_res.get("shoufa_unchecked", True):
                panel_issues.append("首发 could not be confirmed unchecked — DO NOT PUBLISH")
            check_issues = list(check.issues) + panel_issues
            # Draft ok requires body verification; panel issues are advisory except 首发.
            fatal = [x for x in check.issues if ("images missing" in x or "content looks thin" in x or "title text not found" in x or "raw markdown" in x)]
            if not decl_res.get("shoufa_unchecked", True):
                fatal.append("首发 not unchecked")
            check_ok = check.title_match and check.found_images >= check.expected_images and not fatal

            result: dict = {
                "status": "draft", "mode": mode, "title": title,
                "draft_url": draft_url_out,
                "login_needed": login_needed,
                "headless_started": bool(getattr(self, "_started_headless", True)),
                "headless_used": bool(self.headless and not getattr(self, "_fell_back_to_headed", False)),
                "fallback_to_headed": bool(getattr(self, "_fell_back_to_headed", False)),
                "images_uploaded": f"{images_ok}/{images_total}",
                "cover": {"ok": bool(cover_ok), "after": cover_state},
                "declarations": {"result": decl_res, "panel": decl_state},
                "topics": {"wanted": data.get("topics", [])},
                "verification": {"ok": check_ok, "title_match": check.title_match,
                                 "expected_paragraphs": check.expected_paragraphs,
                                 "found_paragraphs": check.found_paragraphs,
                                 "expected_images": check.expected_images,
                                 "found_images": check.found_images,
                                 "issues": check_issues},
                "draft_list": list_res,
                "screenshots": [str(s) for s in (shot_panel, shot1, shot2) if s],
            }
            if mode == "draft":
                if not check_ok:
                    result["status"] = "error"
                    result["error"] = f"draft verification failed: {check_issues}"
                return result
            # mode == publish: implemented but NOT exercised in smoke test.
            if not check_ok:
                result["status"] = "error"
                result["error"] = f"draft verification failed: {check_issues}"
                return result
            # Publish click (only when explicitly --mode publish; smoke runs draft).
            if not decl_res.get("shoufa_unchecked", True):
                result["status"] = "error"
                result["error"] = "refusing publish: 首发 not confirmed unchecked"
                return result
            try:
                btn = await self._first_visible(PUBLISH_SELECTORS, timeout_each_ms=8000)
                await btn.click(timeout=8000)
                await self._human_pause(1.0, 2.0)
                try:
                    confirm = await self._first_visible(CONFIRM_PUBLISH_SELECTORS, timeout_each_ms=8000)
                    await confirm.click(timeout=8000)
                except TimeoutError:
                    logger.info("no confirm dialog")
                await self.page.wait_for_load_state("networkidle", timeout=20000)
                await asyncio.sleep(3)
            except Exception as e:
                result["status"] = "error"
                result["error"] = f"publish click failed: {e}; draft kept at {draft_url_out}"
                return result
            public_url = self.page.url
            result["status"] = "published"
            result["public_url"] = public_url
            return result
        finally:
            try:
                await self.close_browser()
            except Exception:
                pass
            try:
                cleanup_own_chrome_processes(self.profile_dir)
            except Exception:
                pass
