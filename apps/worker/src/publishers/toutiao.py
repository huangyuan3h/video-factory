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
import random
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .base import BasePublisher, PublishResult

logger = logging.getLogger(__name__)

# Fix 2026-10-01: unbuffered timestamped step logging (stdout was empty/buffered).
# Call setup_toutiao_logging() from CLI entry; log_step() prints every step
# with timestamps + flush=True so unattended runs are observable.
_LOGGING_SETUP = False


def setup_toutiao_logging(level: int = logging.INFO) -> None:
    global _LOGGING_SETUP
    if _LOGGING_SETUP:
        return
    handler = logging.StreamHandler(sys.stdout if "sys" in globals() else None)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
    try:
        handler.setFormatter(fmt)
        root = logging.getLogger()
        # Avoid duplicate handlers on re-entry.
        if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
            root.addHandler(handler)
        root.setLevel(level)
        logging.getLogger(__name__).setLevel(level)
    except Exception:
        pass
    _LOGGING_SETUP = True


def log_step(msg: str) -> None:
    """Print one timestamped step line, unbuffered (flush=True)."""
    try:
        import sys as _sys
        ts = datetime.now().isoformat(timespec="seconds")
        print(f"{ts} [STEP] {msg}", file=_sys.stdout, flush=True)
    except Exception:
        pass
    try:
        logger.info(msg)
    except Exception:
        pass

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
# Fix 2026-10-01 (toutiao_fix): hard caps so no loop can run forever.
LOGIN_POLL_INTERVAL_S = 10
LOGIN_MAX_POLLS = 120  # 20 min / 10 s
CAPTCHA_MAX_POLLS = 120
SAVE_DRAFT_MAX_POLLS = 30  # 60 s / 2 s
IMAGE_WAIT_POLL_S = 1.0
RUN_TIMEOUT_S = 15 * 60  # total run cap 15 min per fix prompt
CHECK_LOGIN_URLS = 3  # PUBLISH, DRAFT_LIST, HOME — exactly 3 attempts max
ACCOUNT_NAME = "躺平的老黄"

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
# Blocking onboarding (real-name / creator-plan) — stops drafts.
ONBOARDING_MARKERS = [
    "实名认证", "作者实名", "身份证", "人脸", "创作者计划", "加入创作者",
    "开通创作收益", "入驻", "职业认证", "兴趣认证", "完善资料",
]
# Fix 2026-10-01: onboarding-INCOMPLETE banner (advisory only, drafts may work).
# Observed 07:00 today on https://mp.toutiao.com/profile_v4/index :
#   orange banner 「请完善账号信息，解锁发布文章、视频等权益功能」 + button 「立即完善」.
INCOMPLETE_BANNER_MARKERS = [
    "请完善账号信息", "完善账号信息", "解锁发布文章", "立即完善",
]
ACCOUNT_MARKERS = [ACCOUNT_NAME, "头条号"]
SIDEBAR_MARKERS = ["创作", "草稿箱", "主页", "文章"]
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


def has_account_markers(combined: str) -> bool:
    """True when page shows account name or MP sidebar (fix 2026-10-01).

    Spec: logged in if URL is under mp.toutiao.com and not /auth/page/login,
    AND the page shows the account name or sidebar (创作/草稿箱).
    Observed logged-in home (07:00 today): header 头条号, user 躺平的老黄,
    sidebar 主页/创作/文章/草稿箱.
    """
    c = combined or ""
    if ACCOUNT_NAME in c:
        return True
    # Sidebar: require 创作 + 草稿箱 together (strong), or 头条号 + one of them.
    if "创作" in c and "草稿箱" in c:
        return True
    if "头条号" in c and ("草稿箱" in c or "创作" in c or "主页" in c):
        return True
    return False


def has_incomplete_banner(combined: str) -> bool:
    """True when orange 「请完善账号信息」 banner is present (advisory only)."""
    c = combined or ""
    return any(m in c for m in INCOMPLETE_BANNER_MARKERS)


def has_blocking_onboarding(combined: str) -> bool:
    """True when real-name / creator-plan onboarding blocks drafts."""
    c = combined or ""
    return any(m in c for m in ONBOARDING_MARKERS)


def classify_login_state(url: str, html: str, body_text: str = "") -> str:
    """Classify Toutiao MP page as logged_in/logged_out/onboarding/unknown (pure).

    Fix 2026-10-01 root cause:
    - Old code returned logged_in for ANY profile_v4 URL unless a blocking
      keyword matched, and returned onboarding for any blocking keyword —
      check_login() treated onboarding as NOT logged in, so a logged-in
      homepage with an onboarding-ish string looped on QR forever.
    - Old code never checked for the real logged-in evidence (account name
      躺平的老黄 or sidebar 创作/草稿箱) and never knew the
      「请完善账号信息」 banner (which contains none of the old markers).
    New rule (per fix prompt): logged in iff URL is under mp.toutiao.com
    and not /auth/page/login AND page shows account name or sidebar.
    The incomplete banner is advisory — still logged_in (drafts may work).
    Blocking real-name/creator markers → onboarding (caller decides).
    """
    u = (url or "").lower()
    h = html or ""
    t = body_text or ""
    combined = h + "\n" + t
    is_login_url = ("auth/page/login" in u) or ("/login" in u)
    is_mp = "mp.toutiao.com" in u
    account = has_account_markers(combined)
    qr = any(m in combined for m in LOGIN_QR_MARKERS)
    blocking = has_blocking_onboarding(combined)
    # Login URL: logged_out unless strong account evidence on an mp page.
    if is_login_url:
        if is_mp and account:
            return "logged_in"
        return "logged_out"
    if is_mp:
        # mp.toutiao.com, not login URL — require account/sidebar evidence.
        if account:
            return "logged_in"
        if qr:
            return "logged_out"
        if blocking:
            return "onboarding"
        # Incomplete banner alone without sidebar yet → still likely logged in
        # if URL is a known app page; otherwise unknown (do not guess).
        if has_incomplete_banner(combined) and any(m in u for m in LOGGED_IN_URL_MARKERS):
            return "logged_in"
        if any(m in u for m in LOGGED_IN_URL_MARKERS):
            # URL looks like app but no account/sidebar text yet (slow render
            # or headless thin page) — unknown, caller retries capped times.
            return "unknown"
        return "unknown"
    # Non-mp URL fallbacks.
    if qr:
        return "logged_out"
    if blocking and "profile" in u:
        return "onboarding"
    return "unknown"


def detect_incomplete_banner_state(url: str, html: str, body_text: str = "") -> tuple[bool, str]:
    """Pure helper: (present, excerpt) for the 请完善账号信息 banner."""
    combined = (html or "") + "\n" + (body_text or "")
    if not has_incomplete_banner(combined):
        return False, ""
    body = body_text or html or ""
    for m in INCOMPLETE_BANNER_MARKERS:
        if m in body:
            idx = body.find(m)
            excerpt = body[max(0, idx - 200):idx + 600].strip().replace("\n", " / ")
            return True, f"incomplete banner [{m}]: {excerpt[:800]} (url={(url or '')[:150]})"
    return True, f"incomplete banner present (url={(url or '')[:150]})"


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
                 login_timeout_s: int = LOGIN_POLL_SECONDS,
                 allow_qr_popup: bool = True, **kwargs):
        super().__init__(cookies=None, headless=headless)
        self.profile_dir = Path(profile_dir or DEFAULT_PROFILE_DIR)
        self.smoke_dir = Path(smoke_dir or DEFAULT_SMOKE_DIR)
        self.login_timeout_s = login_timeout_s
        # Fix 2026-10-01: fix-run must NOT pop QR — fail fast with BLOCKED: login.
        self.allow_qr_popup = bool(kwargs.pop("allow_qr", allow_qr_popup))
        if "no_qr_popup" in kwargs:
            self.allow_qr_popup = not bool(kwargs.pop("no_qr_popup"))
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
        """Headless-safe login check with hard cap (max 3 URLs, then fail).

        Fix 2026-10-01: logged in iff URL under mp.toutiao.com and not
        /auth/page/login AND page shows account name or sidebar.
        Every step is logged with timestamps; no infinite retry.
        """
        urls = (PUBLISH_URL, DRAFT_LIST_URL, HOME_URL)
        for attempt, check_url in enumerate(urls, start=1):
            try:
                log_step(f"check_login attempt {attempt}/{len(urls)}: goto {check_url}")
                await self.page.goto(check_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)
                url, html, _, body_text = await self._page_state()
                state = classify_login_state(url, html, body_text)
                has_acct = has_account_markers((html or "") + "\n" + (body_text or ""))
                log_step(f"check_login attempt {attempt}: url={url[:120]} state={state} "
                         f"has_account={has_acct} body_len={len(body_text or '')}")
                if state == "logged_in":
                    log_step(f"check_login OK on attempt {attempt}")
                    return True
                # logged_out/onboarding/unknown → try next URL once (capped).
            except Exception as e:
                log_step(f"check_login attempt {attempt} failed: {e}")
                logger.warning(f"check_login via {check_url} failed: {e}")
                continue
        try:
            url = (self.page.url or "").lower()
            if "auth/page/login" in url or "/login" in url:
                log_step(f"check_login final: still on login URL {url[:120]} → False")
                return False
        except Exception:
            pass
        log_step("check_login final: no logged_in evidence after 3 attempts → False")
        return False

    async def detect_onboarding(self) -> tuple[bool, str]:
        """True + excerpt when BLOCKING registration/real-name/onboarding gates drafts.

        Fix 2026-10-01: the orange 「请完善账号信息」 banner is NOT blocking —
        see detect_incomplete_banner() (advisory, drafts may still work).
        """
        try:
            url, html, _, body_text = await self._page_state()
            state = classify_login_state(url, html, body_text)
            if state == "onboarding":
                for m in ONBOARDING_MARKERS:
                    if m in (body_text or ""):
                        idx = body_text.find(m)
                        excerpt = body_text[max(0, idx - 200):idx + 600].strip().replace("\n", " / ")
                        return True, f"page asks for [{m}]: {excerpt[:800]} (url={url[:120]})"
                return True, f"onboarding page (url={url[:120]}) text={(body_text or '')[:800]!r}"
        except Exception as e:
            logger.warning(f"detect_onboarding failed: {e}")
        return False, ""

    async def detect_incomplete_banner(self) -> tuple[bool, str]:
        """Advisory: orange 请完善账号信息 banner (onboarding-incomplete).

        Logs it and reports it, but caller still tries saving a draft.
        """
        try:
            url, html, _, body_text = await self._page_state()
            present, excerpt = detect_incomplete_banner_state(url, html, body_text or "")
            if present:
                log_step(f"incomplete banner detected: {excerpt[:300]}")
                logger.info(f"incomplete banner: {excerpt[:500]}")
            return present, excerpt
        except Exception as e:
            logger.warning(f"detect_incomplete_banner failed: {e}")
            return False, ""

    async def inspect_onboarding_requirements(self, label: str = "onboarding_detail") -> dict:
        """Open 「立即完善」 read-only, screenshot, record exact ask. NEVER submit.

        Returns {asked, body_excerpt, screenshot}.
        """
        out: dict = {"asked": "", "body_excerpt": "", "screenshot": None}
        try:
            log_step("inspect_onboarding_requirements: looking for 立即完善 (read-only)")
            btn = None
            for sel in ['button:has-text("立即完善")', 'a:has-text("立即完善")',
                        'span:has-text("立即完善")', 'div:has-text("立即完善")']:
                try:
                    cand = await self.page.query_selector(sel)
                    if cand is not None and await cand.is_visible():
                        btn = cand
                        break
                except Exception:
                    continue
            if btn is None:
                log_step("inspect_onboarding_requirements: 立即完善 button not found")
                return out
            try:
                await btn.click(timeout=8000)
            except Exception:
                try:
                    await btn.evaluate("el => el.click()")
                except Exception as e:
                    out["asked"] = f"click failed: {e}"
                    return out
            await asyncio.sleep(4)
            try:
                url = self.page.url or ""
            except Exception:
                url = ""
            try:
                body_text = (await self.page.evaluate("() => document.body.innerText || ''"))[:8000]
            except Exception:
                body_text = ""
            out["body_excerpt"] = (body_text or "")[:3000].replace("\n", " / ")
            out["asked"] = out["body_excerpt"][:1500]
            out["url"] = url[:200]
            shot = self.smoke_dir / f"{label}.png"
            try:
                await self.page.screenshot(path=str(shot), full_page=True, timeout=20000)
                out["screenshot"] = str(shot)
            except Exception:
                pass
            log_step(f"inspect_onboarding_requirements done: url={url[:120]} excerpt={out['body_excerpt'][:200]}")
            # Go back without submitting anything.
            try:
                await self.page.go_back(wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(2)
            except Exception:
                pass
        except Exception as e:
            out["asked"] = f"inspect failed: {e}"
        return out

    async def ensure_login_headless_first(self) -> tuple[bool, bool, bool]:
        """Headless-first login with hard caps (max polls, then BLOCKED).

        Fix 2026-10-01: when allow_qr_popup is False (fix-run), never relaunch
        headed / never pop QR — return (False, True, False) immediately so the
        caller reports BLOCKED: login.
        """
        if await self.check_login():
            return True, False, False
        if not self.allow_qr_popup:
            log_step("ensure_login: headless check failed and QR popup disabled → BLOCKED: login (no QR)")
            logger.error("Toutiao login not detected headless; QR popup disabled per fix-run.")
            return False, True, False
        log_step("ensure_login: headless check failed — relaunching SAME profile headed (QR).")
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
        log_step("ensure_login: waiting for QR scan (capped polls, 10s interval).")
        logger.info("Toutiao login required — waiting for QR scan (up to 20 min).")
        max_polls = max(1, min(LOGIN_MAX_POLLS, int(self.login_timeout_s // LOGIN_POLL_INTERVAL_S)))
        last_notify = asyncio.get_event_loop().time()
        for poll in range(1, max_polls + 1):
            await asyncio.sleep(LOGIN_POLL_INTERVAL_S)
            log_step(f"ensure_login poll {poll}/{max_polls}")
            if await self.check_login():
                log_step("ensure_login: login detected.")
                logger.info("Toutiao login detected.")
                return True, True, relaunched
            now = asyncio.get_event_loop().time()
            if now - last_notify >= LOGIN_RENOTIFY_SECONDS:
                notify_owner(NOTIFY_LOGIN_MSG)
                bring_chrome_front()
                last_notify = now
        log_step(f"ensure_login: timed out after {max_polls} polls → BLOCKED: login")
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
        """Wait for manual captcha solve with hard cap (max polls, then BLOCKED)."""
        if not await self.detect_captcha():
            return True
        if self.headless and self.allow_qr_popup:
            try:
                await self.close_browser()
            except Exception:
                pass
            self.headless = False
            self._fell_back_to_headed = True
            await self.init_browser()
        elif self.headless and not self.allow_qr_popup:
            log_step("wait_captcha: captcha in headless and QR popup disabled → BLOCKED: verification")
            return False
        notify_owner(NOTIFY_CAPTCHA_MSG)
        bring_chrome_front()
        log_step("wait_captcha: verification present, waiting capped polls for manual solve.")
        last_notify = asyncio.get_event_loop().time()
        for poll in range(1, CAPTCHA_MAX_POLLS + 1):
            await asyncio.sleep(10)
            if not await self.detect_captcha():
                log_step(f"wait_captcha: cleared on poll {poll}")
                return True
            log_step(f"wait_captcha: still present poll {poll}/{CAPTCHA_MAX_POLLS}")
            if asyncio.get_event_loop().time() - last_notify >= LOGIN_RENOTIFY_SECONDS:
                notify_owner(NOTIFY_CAPTCHA_MSG)
                last_notify = asyncio.get_event_loop().time()
        log_step("wait_captcha: timed out → BLOCKED: verification")
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
        """Wait for uploads with hard cap (max polls = timeout, then fail).

        Fix 2026-10-01 root cause of the step loop: old code counted ANY
        [class*=progress] element, including the hidden
        <span class="img-loading-progress"> (display:none after upload).
        Headless probe 07:xx showed n=2 https srcs, uploading_txt=False,
        but prog=1 hidden → infinite wait → 15-min timeout.
        Now only VISIBLE progress bars block (offsetParent !== null).
        """
        max_polls = max(1, int(timeout_s // IMAGE_WAIT_POLL_S))
        for poll in range(1, max_polls + 1):
            try:
                state = await self.page.evaluate(
                    """() => {
                        const imgs = Array.from(document.querySelectorAll('.ProseMirror img, [contenteditable] img'));
                        const srcs = imgs.map(i => i.getAttribute('src') || '');
                        const txt = (document.body.innerText || '');
                        const uploadingTxt = txt.includes('上传中') || txt.includes('正在上传');
                        const progEls = Array.from(document.querySelectorAll('[role="progressbar"], [class*="Progress" i], [class*="progress" i]'));
                        const progVisible = progEls.filter(e => {
                            try {
                                const r = e.getBoundingClientRect();
                                const st = window.getComputedStyle(e);
                                return st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0' && r.width > 0 && r.height > 0;
                            } catch (_) { return false; }
                        }).length;
                        return {n: imgs.length, srcs, uploadingTxt, progVisible, progTotal: progEls.length};
                    }"""
                )
            except Exception:
                await asyncio.sleep(IMAGE_WAIT_POLL_S)
                continue
            n = int(state.get("n", 0) or 0)
            srcs = list(state.get("srcs", []) or [])
            uploading = bool(state.get("uploadingTxt")) or int(state.get("progVisible", 0) or 0) > 0
            all_done = n >= expected_min and all(is_upload_done_src(s) for s in srcs) if srcs else False
            if all_done and not uploading:
                await asyncio.sleep(2.0)
                log_step(f"image_upload_complete: n={n} expected>={expected_min} on poll {poll} "
                         f"(progVisible=0, progTotal={state.get('progTotal',0)})")
                return True
            if poll % 15 == 0 or poll <= 3:
                log_step(f"image_upload_wait poll {poll}/{max_polls}: n={n} expected>={expected_min} "
                         f"uploading={uploading} (txt={state.get('uploadingTxt')} progVis={state.get('progVisible')}/{state.get('progTotal')}) "
                         f"srcs={[str(s)[:40] for s in srcs[:3]]}")
            await asyncio.sleep(IMAGE_WAIT_POLL_S)
        log_step(f"image_upload TIMEOUT after {max_polls} polls (expected>={expected_min}) → fail")
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
            # Fix 2026-10-01: panel shows plain 「引用AI」 checkbox (no 声明/生成 in label)
            # while body contains 「文案由 AI 辅助生成」 — tick 引用AI in that case.
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
                    // Fallback 2026-10-01: 引用AI checkbox + AI-assisted body text.
                    if (/AI\\s*辅助生成|文案由\\s*AI/.test(txt)) {
                        for (const el of els) {
                            const ctx = ((el.closest('label, div, span')?.innerText) || el.innerText || '').trim().slice(0,40);
                            if (ctx.includes('引用AI')) {
                                try {
                                    const checked = el.getAttribute('aria-checked') === 'true' || !!el.checked;
                                    if (!checked) el.click();
                                    return 'ai-clicked-yinyong:' + ctx.slice(0,40);
                                } catch(e) { return 'ai-error:' + String(e).slice(0,60); }
                            }
                        }
                    }
                    // 个人观点仅供参考 (toutiao-autoSets this) — complementary, not AI.
                    if (txt.includes('个人观点仅供参考')) return 'ai-panel-found-personal-opinion-present';
                    return 'ai-panel-no-checkbox';
                }""")
            logger.info(f"ai handling: {ai}")
            log_step(f"ai handling: {ai}")
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
        log_step("save_draft: start (NEVER click 发布 here)")
        try:
            n = await self.page.evaluate(
                "() => document.querySelectorAll('.ProseMirror img, [contenteditable] img').length")
            await self.wait_for_image_upload_complete(expected_min=int(n or 0), timeout_s=60)
        except Exception as e:
            log_step(f"save_draft: pre-wait failed: {e}")
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
            log_step("save_draft: draft button not found; relying on autosave")
            logger.warning("draft button not found; relying on autosave")
        else:
            log_step("save_draft: clicked draft button")
        await self._human_pause(1.5, 2.5)
        try:
            await self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        # Wait for pgc_id (draft id) or saved toast — hard cap 30 polls x 2s.
        for poll in range(1, SAVE_DRAFT_MAX_POLLS + 1):
            try:
                url = self.page.url or ""
            except Exception:
                url = ""
            if "pgc_id=" in url:
                log_step(f"save_draft: pgc_id found on poll {poll}: {url[:150]}")
                break
            try:
                toast = await self.page.query_selector('text=草稿已保存, text=已自动保存, text=保存成功')
                if toast is not None and await toast.is_visible():
                    log_step(f"save_draft: saved toast visible on poll {poll}")
                    break
            except Exception:
                pass
            if poll % 10 == 0:
                log_step(f"save_draft: waiting poll {poll}/{SAVE_DRAFT_MAX_POLLS}")
            await asyncio.sleep(2)
        else:
            log_step(f"save_draft: TIMEOUT after {SAVE_DRAFT_MAX_POLLS} polls (no pgc_id/toast)")
        await asyncio.sleep(2)
        try:
            final_url = self.page.url
            log_step(f"save_draft done: url={str(final_url)[:150]}")
            return final_url
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

    async def list_drafts(self, max_cards: int = 30) -> list[dict]:
        """Inspect 草稿箱: list drafts (title, time, url). Capped, read-only.

        Fix 2026-10-01: used first to dedupe ep3 duplicates from the 07:00 run.
        Handles both pgc-link cards and text-only cards (title + time + 编辑/删除,
        as seen 2026-10-01: 「美的，圆通…」 2018-11-27 23:53).
        """
        log_step(f"list_drafts: goto {DRAFT_LIST_URL}")
        await self.page.goto(DRAFT_LIST_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)
        try:
            rows = await self.page.evaluate(
                """(maxCards) => {
                    const out = [];
                    const bodyTxt = document.body.innerText || '';
                    // 1) pgc-link cards.
                    const links = Array.from(document.querySelectorAll('a[href*="pgc_id"], a[href*="draft"], [data-pgc-id]')).slice(0, maxCards);
                    const seen = new Set();
                    for (const a of links) {
                        const href = a.getAttribute('href') || '';
                        const title = (a.innerText || a.textContent || '').trim().slice(0,120);
                        if (!title || seen.has(title+href)) continue;
                        seen.add(title+href);
                        const card = a.closest('[class*="card"], [class*="item"], li, div') ;
                        const ctx = ((card && card.innerText) || document.body.innerText || '').slice(0,2000);
                        const m = ctx.match(/(20\\d{2}[-\\/]\\d{1,2}[-\\/]\\d{1,2}[\\s\\S]{0,12}\\d{1,2}:\\d{1,2}|\\d{1,2}-\\d{1,2}[\\s\\S]{0,12}\\d{1,2}:\\d{1,2}|今天[\\s\\S]{0,6}\\d{1,2}:\\d{1,2}|昨天[\\s\\S]{0,6}\\d{1,2}:\\d{1,2}|\\d+\\s*小时前|\\d+\\s*分钟前)/);
                        out.push({title, time: (m ? m[0] : ''), href: href.slice(0,300)});
                    }
                    // 2) text fallback: lines like "<title>\\nYYYY-MM-DD HH:MM\\n编辑删除".
                    // Observed 2026-10-01: single draft, no pgc href in static DOM.
                    const lines = bodyTxt.split('\\n').map(s=>s.trim()).filter(s=>s);
                    const timeRe = /^(20\\d{2}[-\\/]\\d{1,2}[-\\/]\\d{1,2}\\s+\\d{1,2}:\\d{1,2}|\\d{1,2}-\\d{1,2}\\s+\\d{1,2}:\\d{1,2}|今天\\s*\\d{1,2}:\\d{1,2}|昨天\\s*\\d{1,2}:\\d{1,2})$/;
                    for (let i=0;i<lines.length && out.length<maxCards;i++) {
                        if (timeRe.test(lines[i]) && i>0) {
                            const title = lines[i-1].slice(0,120);
                            if (title.includes('共 ') && title.includes('条内容')) continue;
                            if (title === '编辑删除' || title === '编辑' || title === '删除') continue;
                            if (title.length < 2) continue;
                            if (out.some(r=>r.title===title)) continue;
                            out.push({title, time: lines[i].slice(0,60), href: ''});
                        }
                    }
                    return {rows: out, body_len: bodyTxt.length, body_head: bodyTxt.slice(0,3000)};
                }""",
                max_cards,
            )
        except Exception as e:
            log_step(f"list_drafts DOM read failed: {e}")
            return []
        items: list[dict] = []
        _NAV_TITLES = {"草稿箱", "草稿", "全部", "文章", "视频", "微头条", "音频", "合集"}
        for r in (rows.get("rows") or [])[:max_cards]:
            t = str(r.get("title") or "").strip()[:120]
            href = str(r.get("href") or "")
            # Drop nav links (e.g. sidebar 草稿箱 → /manage/draft itself).
            if t in _NAV_TITLES and (not href or href.endswith("/manage/draft") or href.endswith("manage/draft")):
                continue
            # Resolve relative href to absolute.
            if href.startswith("/"):
                href = "https://mp.toutiao.com" + href
            elif href and not href.startswith("http"):
                href = "https://mp.toutiao.com/" + href.lstrip("/") if href else ""
            if href.rstrip("/").endswith("/manage/draft") and not t:
                continue
            items.append({"title": t,
                          "time": str(r.get("time") or "")[:60],
                          "url": href})
        # Log titles/times with timestamps (no screenshots here).
        for i, d in enumerate(items, start=1):
            log_step(f"draft[{i}]: title={d['title'][:60]!r} time={d['time']!r} url={d['url'][:120]}")
        log_step(f"list_drafts done: {len(items)} rows (body_len={rows.get('body_len')})")
        return items

    async def delete_draft_by_url(self, draft_url: str) -> bool:
        """Delete ONE draft via the draft-list UI. Returns True on success.

        Safety: caller must ensure the URL is an ep3-title draft from 2026-10-01.
        Best-effort: finds the card containing the pgc_id and clicks 删除/更多→删除.
        """
        try:
            m = re.search(r"pgc_id=(\d+)", draft_url or "")
            pgc = m.group(1) if m else ""
            log_step(f"delete_draft: pgc_id={pgc} url={draft_url[:120]}")
            await self.page.goto(DRAFT_LIST_URL, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(4)
            if pgc:
                deleted = await self.page.evaluate(
                    """(pgc) => {
                        const links = Array.from(document.querySelectorAll('a[href*="'+pgc+'"]'));
                        for (const a of links) {
                            const card = a.closest('[class*="card"], [class*="item"], li, tr, div');
                            if (!card) continue;
                            const btns = Array.from(card.querySelectorAll('button, a, span'));
                            for (const b of btns) {
                                const t = (b.innerText||'').trim();
                                if (t === '删除' || t.includes('删除')) { b.click(); return 'clicked-delete:'+t.slice(0,20); }
                            }
                            // fallback: 更多 menu
                            for (const b of btns) {
                                if ((b.innerText||'').includes('更多')) { b.click(); return 'clicked-more'; }
                            }
                        }
                        return 'notfound';
                    }""",
                    pgc,
                )
                log_step(f"delete_draft click1: {deleted}")
                await asyncio.sleep(2)
                # Confirm dialog (确定/确认删除).
                for sel in ['button:has-text("确认")', 'button:has-text("确定")',
                            'button:has-text("删除")', '.byte-modal button.byte-btn-primary']:
                    try:
                        btn = await self.page.query_selector(sel)
                        if btn is not None and await btn.is_visible():
                            # Only click if dialog mentions 删除.
                            try:
                                dlg = await self.page.evaluate("() => (document.body.innerText||'').slice(-2000)")
                            except Exception:
                                dlg = ""
                            if "删除" in (dlg or "") or "确认" in (dlg or ""):
                                await btn.click(timeout=5000)
                                log_step(f"delete_draft confirm clicked: {sel}")
                                await asyncio.sleep(3)
                                break
                    except Exception:
                        continue
                # Verify gone.
                await self.page.goto(DRAFT_LIST_URL, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)
                try:
                    body = await self.page.evaluate("() => document.body.innerText || ''")
                    still = pgc in (await self.page.content()) if pgc else False
                    log_step(f"delete_draft verify: pgc_still_in_dom={still}")
                    return not still
                except Exception:
                    return True
            return False
        except Exception as e:
            log_step(f"delete_draft failed: {e}")
            return False

    async def delete_draft_by_title(self, title: str) -> bool:
        """Delete ONE draft by exact title (text-card fallback, no pgc_id).

        Safety: caller must ensure title is the ep3 title from today.
        Clicks 删除 in the card containing the title, confirms, verifies gone.
        """
        try:
            t = (title or "").strip()
            if not t:
                return False
            log_step(f"delete_draft_by_title: {t[:60]!r}")
            await self.page.goto(DRAFT_LIST_URL, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(4)
            clicked = await self.page.evaluate(
                """(want) => {
                    const all = Array.from(document.querySelectorAll('button, a, span'));
                    // find 删除 button whose card contains want
                    for (const b of all) {
                        const txt = (b.innerText||'').trim();
                        if (txt !== '删除') continue;
                        const card = b.closest('div, li, tr');
                        const ctx = ((card && card.parentElement && card.parentElement.innerText) || document.body.innerText || '');
                        if (ctx.includes(want)) { b.click(); return 'clicked-delete'; }
                    }
                    return 'notfound';
                }""",
                t,
            )
            log_step(f"delete_draft_by_title click: {clicked}")
            if clicked == "notfound":
                return False
            await asyncio.sleep(2)
            for sel in ['button:has-text("确认")', 'button:has-text("确定")',
                        'button:has-text("删除")', '.byte-modal button.byte-btn-primary']:
                try:
                    btn = await self.page.query_selector(sel)
                    if btn is not None and await btn.is_visible():
                        await btn.click(timeout=5000)
                        log_step(f"delete_draft_by_title confirm: {sel}")
                        await asyncio.sleep(3)
                        break
                except Exception:
                    continue
            await self.page.goto(DRAFT_LIST_URL, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)
            try:
                body = await self.page.evaluate("() => document.body.innerText || ''")
                still = t in (body or "")
                log_step(f"delete_draft_by_title verify: still_present={still}")
                return not still
            except Exception:
                return True
        except Exception as e:
            log_step(f"delete_draft_by_title failed: {e}")
            return False

    async def dedupe_ep3_drafts(self, ep3_title: str) -> dict:
        """Keep only ONE ep3 draft (created 2026-10-01); delete today's duplicates.

        Safety: only touches drafts whose title contains the ep3 title AND whose
        time looks like today (2026-10-01 / 10-01 / 今天). Touches nothing else.
        Returns {before, after, removed}.
        """
        before = await self.list_drafts()
        ep3 = (ep3_title or "").strip()
        # Match drafts with ep3 title (exact or contained).
        cands = [d for d in before if ep3 and (ep3 in (d.get("title") or "") or (d.get("title") or "") in ep3)]
        today_markers = ("2026-10-01", "2026/10/01", "10-01", "10/01", "今天")
        todays = [d for d in cands if any(m in (d.get("time") or "") for m in today_markers)
                  or not d.get("time")]  # empty time → include (conservative? no — keep)
        # If time empty for all, fall back to title-only dedupe only when >1 exact matches.
        if all(not d.get("time") for d in cands) and len(cands) > 1:
            todays = cands
        elif all(not d.get("time") for d in cands):
            todays = []
        log_step(f"dedupe: before={len(before)} ep3_matches={len(cands)} today_cands={len(todays)}")
        removed = 0
        # Keep the first, delete the rest (only today's duplicates).
        keep = todays[:1]
        for d in todays[1:]:
            if d.get("url"):
                ok = await self.delete_draft_by_url(d.get("url") or "")
            else:
                ok = await self.delete_draft_by_title(d.get("title") or "")
            log_step(f"dedupe delete {d.get('title','')[:40]!r} → {ok}")
            if ok:
                removed += 1
            await asyncio.sleep(1)
        after = await self.list_drafts() if removed else before
        return {"before": before, "after": after, "removed": removed,
                "kept": keep}

    async def find_existing_draft(self, ep3_title: str) -> dict | None:
        """Return the surviving ep3 draft (title match) or None (idempotent reuse)."""
        drafts = await self.list_drafts()
        ep3 = (ep3_title or "").strip()
        for d in drafts:
            t = (d.get("title") or "").strip()
            if ep3 and (ep3 in t or t in ep3):
                return d
        return None

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
        setup_toutiao_logging()
        run_start = asyncio.get_event_loop().time() if asyncio._get_running_loop() else 0.0
        _ = no_open
        # Reuse profile exactly like Zhihu/Bilibili: persistent dir, never delete/logout.
        log_step(f"run start: mode={mode} payload={payload_path} headless={self.headless} "
                 f"profile={self.profile_dir} allow_qr={self.allow_qr_popup}")
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
        log_step(f"browser init done: headless={self.headless} profile={self.profile_dir}")
        onboarding_status: dict = {"incomplete_banner": False, "incomplete_excerpt": "",
                                   "blocking": False, "blocking_excerpt": "",
                                   "detail": {}}
        drafts_before: list[dict] = []
        drafts_after: list[dict] = []
        dedupe_info: dict = {"removed": 0}
        reused_draft: dict | None = None
        try:
            logged_in, login_needed = await self.ensure_login()
            if not logged_in:
                try:
                    await self.page.screenshot(path=str(self.smoke_dir / f"{smoke_label}_login_blocked.png"), full_page=True, timeout=20000)
                except Exception:
                    pass
                return {"status": "blocked", "reason": "login", "error": "BLOCKED: login",
                        "onboarding": onboarding_status}
            log_step("login OK (persistent profile reused, no logout).")
            if not await self.wait_captcha_if_present():
                return {"status": "blocked", "reason": "verification", "error": "BLOCKED: verification",
                        "onboarding": onboarding_status}

            # Blocking onboarding gate (real-name/creator). Incomplete banner is advisory only.
            onb, excerpt = await self.detect_onboarding()
            if onb:
                shot = self.smoke_dir / f"{smoke_label}_onboarding.png"
                try:
                    await self.page.screenshot(path=str(shot), full_page=True, timeout=20000)
                except Exception:
                    pass
                onboarding_status.update({"blocking": True, "blocking_excerpt": excerpt})
                return {"status": "blocked", "reason": "onboarding",
                        "error": f"BLOCKED: onboarding — {excerpt}", "screenshots": [str(shot)],
                        "onboarding": onboarding_status}
            # Advisory incomplete banner: log + report, but still try saving a draft.
            inc, inc_excerpt = await self.detect_incomplete_banner()
            if inc:
                onboarding_status.update({"incomplete_banner": True, "incomplete_excerpt": inc_excerpt})
                log_step(f"onboarding-incomplete (advisory, continue to draft): {inc_excerpt[:300]}")
            else:
                log_step("onboarding-incomplete banner: not seen")

            # Inspect 草稿箱 first (read-only list), then dedupe today's ep3 duplicates.
            try:
                drafts_before = await self.list_drafts()
            except Exception as e:
                log_step(f"list_drafts (before) failed: {e}")
            try:
                dedupe_info = await self.dedupe_ep3_drafts(title)
                drafts_after_dedupe = dedupe_info.get("after", drafts_before)
                log_step(f"dedupe done: removed={dedupe_info.get('removed',0)}")
            except Exception as e:
                log_step(f"dedupe failed: {e}")
                drafts_after_dedupe = drafts_before
            drafts_after = list(drafts_after_dedupe)
            # Idempotent reuse: if an ep3 draft already exists, update it instead of creating another.
            if not draft_url:
                try:
                    reused_draft = await self.find_existing_draft(title)
                except Exception as e:
                    log_step(f"find_existing_draft failed: {e}")
                    reused_draft = None
                if reused_draft and reused_draft.get("url"):
                    draft_url = reused_draft["url"]
                    log_step(f"idempotent reuse: existing ep3 draft found → update {draft_url[:150]}")
                else:
                    log_step("idempotent reuse: no existing ep3 draft → create new")

            images_ok = 0
            images_total = sum(1 for b in blocks if b.get("kind") == "image")
            target_url = draft_url if draft_url else PUBLISH_URL
            log_step(f"goto editor: {target_url[:150]} (reuse={bool(draft_url)})")
            await self.page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(5)
            # Second onboarding check on the publish page itself.
            onb2, excerpt2 = await self.detect_onboarding()
            if onb2:
                shot = self.smoke_dir / f"{smoke_label}_onboarding.png"
                try:
                    await self.page.screenshot(path=str(shot), full_page=True, timeout=20000)
                except Exception:
                    pass
                onboarding_status.update({"blocking": True, "blocking_excerpt": excerpt2})
                return {"status": "blocked", "reason": "onboarding",
                        "error": f"BLOCKED: onboarding — {excerpt2}", "screenshots": [str(shot)],
                        "onboarding": onboarding_status,
                        "drafts_before": drafts_before, "drafts_after": drafts_after,
                        "dedupe": dedupe_info}
            inc2, inc_excerpt2 = await self.detect_incomplete_banner()
            if inc2:
                onboarding_status.update({"incomplete_banner": True, "incomplete_excerpt": inc_excerpt2})
                log_step(f"editor page incomplete banner (advisory): {inc_excerpt2[:200]}")
            if not await self.wait_captcha_if_present():
                return {"status": "blocked", "reason": "verification", "error": "BLOCKED: verification",
                        "onboarding": onboarding_status}

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

            try:
                log_step(f"fill_title: {title[:40]!r}")
                await self.fill_title(title)
            except Exception as e:
                log_step(f"fill_title FAILED (editor refused?): {e}")
                detail = await self.inspect_onboarding_requirements(label=f"{smoke_label}_onboarding_detail")
                onboarding_status.update({"blocking": True,
                                          "blocking_excerpt": f"editor refused title: {e}",
                                          "detail": detail})
                shot = self.smoke_dir / f"{smoke_label}_onboarding.png"
                try:
                    await self.page.screenshot(path=str(shot), full_page=True, timeout=20000)
                except Exception:
                    pass
                return {"status": "blocked", "reason": "onboarding",
                        "error": f"BLOCKED: onboarding — editor refused (title): {e}; "
                                 f"立即完善 asks: {detail.get('asked','')[:500]}",
                        "screenshots": [str(shot)] + ([detail["screenshot"]] if detail.get("screenshot") else []),
                        "onboarding": onboarding_status,
                        "drafts_before": drafts_before, "drafts_after": drafts_after,
                        "dedupe": dedupe_info}
            # Body: inject text blocks as HTML, then upload images in order.
            text_blocks = [b for b in blocks if b.get("kind") != "image"]
            html = self.blocks_to_html(text_blocks)
            # Toutiao editor needs a focused empty doc before inject; reuse heading/para typing
            # for the first blocks to look human, then bulk-inject the rest? Minimal: type all text
            # blocks human-paced (safer for React state), upload images interleaved by position.
            # To keep positions simple: type text blocks in order, uploading each image when its
            # block is reached (images stay in original order).
            try:
                log_step("focus editor")
                await self._focus_editor()
            except Exception as e:
                log_step(f"focus editor FAILED (editor refused?): {e}")
                detail = await self.inspect_onboarding_requirements(label=f"{smoke_label}_onboarding_detail")
                onboarding_status.update({"blocking": True,
                                          "blocking_excerpt": f"editor refused focus: {e}",
                                          "detail": detail})
                shot = self.smoke_dir / f"{smoke_label}_onboarding.png"
                try:
                    await self.page.screenshot(path=str(shot), full_page=True, timeout=20000)
                except Exception:
                    pass
                return {"status": "blocked", "reason": "onboarding",
                        "error": f"BLOCKED: onboarding — editor refused (focus): {e}; "
                                 f"立即完善 asks: {detail.get('asked','')[:500]}",
                        "screenshots": [str(shot)] + ([detail["screenshot"]] if detail.get("screenshot") else []),
                        "onboarding": onboarding_status,
                        "drafts_before": drafts_before, "drafts_after": drafts_after,
                        "dedupe": dedupe_info}
            log_step(f"editor focused, writing {len(blocks)} blocks ({images_total} images)")
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
                    log_step(f"block write failed ({kind}): {e}")
                    logger.warning(f"block write failed ({kind}): {e}")
                await self._human_pause(0.3, 0.8)
                if await self.detect_captcha():
                    if not await self.wait_captcha_if_present():
                        return {"status": "blocked", "reason": "verification", "error": "BLOCKED: verification",
                                "onboarding": onboarding_status}
            log_step(f"blocks done: images_ok={images_ok}/{images_total}")

            # Panel: cover + declarations BEFORE save. NEVER tick 首发.
            log_step("cover upload start (1024x678 ensured)")
            cover_ok = await self.try_cover(data.get("cover_image"))
            log_step(f"cover done: ok={cover_ok}")
            log_step("declarations start (tick 原创 + AI, NEVER 首发)")
            decl_res = await self.try_declarations()
            log_step(f"declarations done: {decl_res}")
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

            log_step(f"verify done: ok={check_ok} title={check.title_match} "
                     f"img={check.found_images}/{check.expected_images} issues={check_issues}")
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
                "onboarding": onboarding_status,
                "drafts_before": drafts_before,
                "drafts_after": drafts_after,
                "dedupe": dedupe_info,
                "reused_draft": reused_draft,
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
