# Zhihu publisher (知乎专栏, headless-by-default)

Playwright semi-auto publisher for one 专栏 article per run.
Research background: `docs/zhihu-publishing-research.md` §1.3 (no official
write API — Playwright is the only realistic path), §4 (content guardrails),
§6 (platform differences), §7 (owner checklist).

## Publish an episode in one command

```bash
# Dry run: write + save draft + reload + verify + screenshots. Never publishes.
~/Projects/video-factory-zhihu/scripts/zhihu_publish.sh \
  ~/Projects/karios-series-output/zhihu/ep9_ma5_20_golden_cross/publish_payload.json --draft-only
# Real publish: same as draft, then clicks 发布 only if verification passes.
# On success: prints URL, saves published.json, `open <url>` (unless --no-open).
~/Projects/video-factory-zhihu/scripts/zhihu_publish.sh \
  ~/Projects/karios-series-output/zhihu/ep<N>_<id>/publish_payload.json --mode publish
# Equivalent module entry (run from apps/worker):
# uv run python -m src.publishers.zhihu_publish --payload <path> [--draft-only] [--headed] [--force] [--no-open]
# uv run python scripts/zhihu_publish.py --payload <path> --mode draft|publish
```

Flags: `--payload` (required), `--mode draft|publish` (default `draft`),
`--draft-only` (forces draft, overrides `--mode`), `--headed` (visible Chrome;
default is headless), `--headless` (force headless), `--force` (republish even
when `published.json` has a URL), `--no-open` (don't `open <url>`),
`--profile`, `--smoke-dir`, `--smoke-label`, `--login-timeout-s` (default
1200), `--skip-logged-out-check`, `--draft-url` (reuse an existing draft).

Payload (`publish_payload.json`): `title`, `body_markdown_path` (relative to
the payload dir), `images_in_order`, `cover_image`, `topics` (3–5),
`column`, `declaration`. Markdown supports `#` title, `##` headings,
paragraphs, `**bold**`, `> quote`, `![alt](rel/path)` + following `*caption*`
line, `---` divider. Parser: `src/publishers/zhihu.py::parse_zhihu_markdown`
(tested in `tests/test_zhihu_markdown.py`); login/idempotency helpers tested in
`tests/test_zhihu_headless.py`.

## Headless by default, headed only when needed

- Default `headless=True` with the persistent profile
  `~/.video-factory/zhihu-profile`. Never reads/exports cookies from the
  owner's normal browsers; no credentials in the repo. Never delete/reset the
  profile.
- First a cheap login check runs headless (`https://www.zhihu.com/creator`,
  then home, avatar/`提问` = in). If logged-out, QR, captcha, blank page,
  detection, or forced verification appears: the headless context is closed,
  the SAME profile is relaunched headed (visible), Chrome is brought to front,
  an `osascript` notification fires ("请在弹出的浏览器里扫码登录知乎"),
  `~/Projects/karios-series-output/zhihu/NEED_LOGIN` is written, and the tool
  waits up to 20 min (re-notify every 5 min), then continues automatically in
  that headed session. Captchas are never solved automatically.
- When headless is blocked but login is still valid, the fallback is still
  automatic headed (normal visible window; it only steals focus when manual
  login/verification is actually needed — minimized/offscreen is not reliably
  possible for Chrome on macOS, so this is documented honestly).
- Result JSON reports `headless_started`, `headless_used`,
  `fallback_to_headed`, `login_needed` so the headless finding is auditable.

## What happens when login expires

- A visible Chrome window pops up + macOS notification + `NEED_LOGIN` file.
- Scan QR / manually finish verification in that window within 20 min.
- The flag is deleted after login; the run continues by itself.
- Timeout → exit 2 / `BLOCKED: login` (or `BLOCKED: verification`).

## Where logs, screenshots and outputs go

- Stdout JSON per run (`verification.ok`, `draft_url`/`public_url`,
  `headless_used`, `fallback_to_headed`); final line `DRAFT DONE`,
  `PUBLISH DONE` (+ `PUBLISHED URL: …`), or `BLOCKED: <reason>`.
- Screenshots: `~/Projects/karios-series-output/zhihu/smoke/`
  (`<label>_draft_editor.png`, `<label>_draft_reloaded.png`,
  `<label>_published.png`, `<label>_logged_out.png`).
- On publish success: `published.json` (url + timestamp + screenshots) is
  saved next to the payload; the URL is also `open`ed unless `--no-open`.
- Idempotency: publish mode refuses when `published.json` already has a URL
  (unless `--force`); draft mode always runs.
- Clean shutdown: the browser context is always closed; only leftover Chrome
  processes holding OUR profile dir are swept — Docker, the :8000 worker,
  and the user's apps are never touched.
- Pre-run guard: `pgrep -fl "ffmpeg|whisper|render"` must be empty (limited
  RAM — never run alongside a render/Whisper job).

## Limits / guardrails

- Exactly ONE article per run (the payload given). No 回答/想法/follow/
  like/comment/settings actions.
- Draft-first: save draft → reload draft URL → verify (title present,
  char-count primary + block-count advisory, all images present, no raw
  `**`/`![` leaking) → publish only on pass.
- Publish clicks retry max 3 total (initial + 2); on failure the draft is left
  in place and the error reported.
- Human pacing: per-block pauses, chunked typing (12–35 ms/char), 1–2 s after
  uploads. Single browser instance; closed at the end; only own processes.
- Every Playwright wait has an explicit timeout; login/captcha loops have hard
  20-minute deadlines — the script never hangs forever.

## Known fragile selectors

Zhihu markup changes often; all lookups try several candidates
(see `*_SELECTORS` in `src/publishers/zhihu.py`):

- Title: `textarea[placeholder*="标题"]` → `.Write-titleInput textarea` → …
- Editor: `.ProseMirror` → `[role="textbox"]` → `[contenteditable]` → …
- Images: hidden `input[type=file][accept*=image]` first, else toolbar
  image button + `expect_file_chooser`.
- Cover (`设置封面/添加封面/上传封面`), topics (`添加话题`), AI declaration
  (`创作声明/AI 辅助`) are best-effort: missing UI logs a warning and the run
  continues (declaration + 免责 already live in the body text).
- Login: avatar/`提问` button = in; `/signin` URL or `登录` button = out
  (pure helper `classify_login_state`, unit-tested).
- Captcha: `*captcha*`/`yidun`/`NECaptcha` selectors + `验证码/安全验证/滑动`
  text scan. Logged-out automated-Chrome 40362 (`请求存在异常`) is Zhihu 风控,
  treated as headless-blocked → automatic headed fallback.
