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
    """
    lines = md_text.splitlines()
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


def load_payload(payload_path: str | Path) -> dict:
    """Load ``publish_payload.json`` and resolve relative paths to absolute."""
    p = Path(payload_path).resolve()
    data = json.loads(p.read_text(encoding="utf-8"))
    base = p.parent
    body_rel = data.get("body_markdown_path", "article.md")
    body_path = (base / body_rel).resolve()
    cover = data.get("cover_image")
    cover_path = str((base / cover).resolve()) if cover else None
    images = [str((base / rel).resolve()) for rel in data.get("images_in_order", [])]
    md_text = Path(body_path).read_text(encoding="utf-8")
    parsed = parse_zhihu_markdown(md_text)
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

    async def write_image(self, image_path: str, caption: str = "") -> bool:  # pragma: no cover
        """Upload one image at the cursor; returns True on success (max 2 tries)."""
        p = Path(image_path)
        if not p.exists():
            logger.error(f"image missing: {image_path}")
            return False
        for attempt in range(1, 3 + 1):
            try:
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
                # Wait for the image to appear in the editor.
                await self.page.wait_for_function(
                    "() => document.querySelectorAll('[contenteditable] img, .ProseMirror img').length > 0",
                    timeout=60000,
                )
                await self._human_pause(0.8, 1.6)
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

    async def try_cover(self, cover_path: str | None) -> bool:  # pragma: no cover
        if not cover_path or not Path(cover_path).exists():
            logger.info("no cover image; skipping cover step")
            return False
        try:
            for text in COVER_BUTTON_TEXTS:
                try:
                    btn = await self.page.query_selector(f'button:has-text("{text}")')
                    if btn is not None and await btn.is_visible():
                        async with self.page.expect_file_chooser(timeout=8000) as fc:
                            await btn.click(timeout=5000)
                        chooser = await fc.value
                        await chooser.set_files(str(cover_path))
                        await self._human_pause(1.0, 2.0)
                        logger.info("cover uploaded")
                        return True
                except Exception:  # noqa: BLE001, S112
                    continue
            # Fallback: any visible file input on the publish panel.
            logger.info("cover button not found; skipping (non-fatal)")
            return False
        except Exception as e:  # noqa: BLE001
            logger.warning(f"cover step failed (non-fatal): {e}")
            return False

    async def try_topics(self, topics: list[str]) -> int:  # pragma: no cover
        """Add up to 3–5 topics if the UI allows. Returns count added."""
        added = 0
        try:
            btn = None
            for text in TOPIC_BUTTON_TEXTS:
                try:
                    cand = await self.page.query_selector(f'button:has-text("{text}"), div:has-text("{text}")')
                    if cand is not None and await cand.is_visible():
                        btn = cand
                        break
                except Exception:  # noqa: BLE001, S112
                    continue
            if btn is None:
                logger.info("topic UI not found; skipping (non-fatal)")
                return 0
            await btn.click(timeout=5000)
            await asyncio.sleep(1.0)
            for topic in (topics or [])[:5]:
                try:
                    box = await self.page.query_selector('input[placeholder*="话题" i], input[placeholder*="搜索" i]')
                    if box is None:
                        box = await self.page.query_selector('input[type="text"]')
                    if box is None:
                        break
                    await box.fill("", timeout=5000)
                    await box.type(topic, delay=30)
                    await asyncio.sleep(1.2)
                    opt = await self.page.query_selector(f'[role="option"]:has-text("{topic}"), li:has-text("{topic}")')
                    if opt is not None:
                        await opt.click(timeout=5000)
                        added += 1
                    else:
                        await self.page.keyboard.press("Enter")
                        added += 1
                    await self._human_pause(0.5, 1.0)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"topic '{topic}' failed (non-fatal): {e}")
                    continue
            logger.info(f"topics added: {added}")
            return added
        except Exception as e:  # noqa: BLE001
            logger.warning(f"topic step failed (non-fatal): {e}")
            return added

    async def try_ai_declaration(self, declaration: str = "") -> bool:  # pragma: no cover
        """Tick the AI-assisted creation declaration if offered. Non-fatal."""
        try:
            for text in AI_DECL_TEXTS:
                try:
                    el = await self.page.query_selector(
                        f'button:has-text("{text}"), label:has-text("{text}"), span:has-text("{text}")'
                    )
                    if el is not None and await el.is_visible():
                        # Prefer a checkbox inside/near the label.
                        box = await self.page.query_selector(
                            'input[type="checkbox"]'
                        )
                        if box is not None:
                            try:
                                if not await box.is_checked():
                                    await box.check(timeout=5000)
                                logger.info("AI declaration checked")
                                return True
                            except Exception:  # noqa: BLE001
                                pass
                        await el.click(timeout=5000)
                        logger.info(f"AI declaration element clicked: {text}")
                        return True
                except Exception:  # noqa: BLE001, S112
                    continue
            logger.info("AI declaration UI not found; declaration kept in body text (non-fatal)")
            return False
        except Exception as e:  # noqa: BLE001
            logger.warning(f"AI declaration step failed (non-fatal): {e}")
            return False

    async def save_draft(self) -> str | None:  # pragma: no cover - browser
        """Save as draft; returns the draft URL (page.url) or None."""
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
                shot1 = self.smoke_dir / f"{smoke_label}_draft_reused.png"
                try:
                    await self.page.screenshot(path=str(shot1), full_page=True, timeout=20000)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"screenshot failed: {e}")
                    shot1 = None

            # Reload the draft and verify.
            if draft_url:
                try:
                    await self.page.goto(draft_url, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(3)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"reload draft failed: {e}")
            check = await self.verify_draft(title, blocks)
            if reused:
                images_ok = int(check.found_images)
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
                "verification": {
                    "ok": check.ok,
                    "title_match": check.title_match,
                    "expected_paragraphs": check.expected_paragraphs,
                    "found_paragraphs": check.found_paragraphs,
                    "expected_images": check.expected_images,
                    "found_images": check.found_images,
                    "issues": check.issues,
                },
                "screenshots": [str(s) for s in (shot1, shot2) if s],
            }
            if mode == "draft":
                return result
            # mode == publish: only continue when verification passes.
            if not check.ok:
                result["status"] = "error"
                result["error"] = f"draft verification failed: {check.issues}"
                return result

            # Cover / topics / AI declaration (best-effort, non-fatal).
            await self.try_cover(data.get("cover_image"))
            await self.try_topics(data.get("topics", []))
            await self.try_ai_declaration(data.get("declaration", ""))

            # Click publish (max 3 attempts total = initial + 2 retries).
            public_url: str | None = None
            last_err: str | None = None
            for attempt in range(1, 4):
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
                    url = self.page.url or ""
                    if "/zhuanlan.zhihu.com/p/" in url and "/edit" not in url and "/write" not in url:
                        public_url = url
                    else:
                        # Look for a link to the new article.
                        try:
                            link = await self.page.query_selector('a[href*="/zhuanlan.zhihu.com/p/"]')
                            if link is not None:
                                href = await link.get_attribute("href")
                                if href:
                                    public_url = href if href.startswith("http") else f"https:{href}" if href.startswith("//") else href
                        except Exception:  # noqa: BLE001
                            pass
                        if public_url is None:
                            public_url = url or None
                    break
                except Exception as e:  # noqa: BLE001
                    last_err = str(e)
                    logger.warning(f"publish attempt {attempt}/3 failed: {e}")
                    await self._human_pause(2.0, 3.0)
            if not public_url:
                result["status"] = "error"
                result["error"] = f"publish click failed after 3 tries: {last_err}; draft kept at {draft_url}"
                return result

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
