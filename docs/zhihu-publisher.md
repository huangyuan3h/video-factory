# Zhihu publisher (知乎专栏)

Playwright semi-auto publisher for one 专栏 article per run (ep9 smoke test).
Research background: `docs/zhihu-publishing-research.md` §1.3 (no official
write API — Playwright is the only realistic path), §4 (content guardrails),
§6 (platform differences), §7 (owner checklist).

## Usage

```bash
cd apps/worker
# Dry run: write + save draft + reload + verify + screenshots. Never publishes.
uv run python scripts/zhihu_publish.py --payload ~/Projects/karios-series-output/zhihu/ep9_ma5_20_golden_cross/publish_payload.json --mode draft
# Real publish: same as draft, then clicks 发布 only if verification passes.
uv run python scripts/zhihu_publish.py --payload <path>/publish_payload.json --mode publish
# Equivalent module entry:
uv run python -m src.publishers.zhihu_publish --payload <path> --mode draft|publish
```

Payload (`publish_payload.json`): `title`, `body_markdown_path` (relative to
the payload dir), `images_in_order`, `cover_image`, `topics` (3–5),
`column`, `declaration`. Markdown supports `#` title, `##` headings,
paragraphs, `**bold**`, `> quote`, `![alt](rel/path)` + following `*caption*`
line, `---` divider. Parser: `src/publishers/zhihu.py::parse_zhihu_markdown`
(tested in `tests/test_zhihu_markdown.py`).

Outputs: full-page screenshots in
`~/Projects/karios-series-output/zhihu/smoke/` (`ep9_draft_editor.png`,
`ep9_draft_reloaded.png`, `ep9_published.png`, `ep9_logged_out.png`).
Final stdout line is `DRAFT DONE`, `PUBLISH DONE`, or `BLOCKED: <reason>`.

## Login flow

- Persistent headed Chromium profile at `~/.video-factory/zhihu-profile`.
  Never reads/exports cookies from the owner's normal browsers; no credentials
  in the repo.
- If not logged in: opens `https://www.zhihu.com/signin` headed, brings Chrome
  to front, fires an `osascript` notification
  ("请在弹出的浏览器里扫码登录知乎"), writes
  `~/Projects/karios-series-output/zhihu/NEED_LOGIN`, polls every 10 s for up
  to 20 min, re-notifying every 5 min. Deletes the flag after login.
  Timeout → exit 2 / `BLOCKED: login`.
- Captcha/verification is never solved automatically: on detection the owner is
  notified the same way and the script waits up to 20 min, then continues;
  otherwise `BLOCKED: verification`.

## Limits / guardrails

- Exactly ONE article per run (the payload given, ep9). No 回答/想法/follow/
  like/comment/settings actions.
- Draft-first: save draft → reload draft URL → verify (title present,
  paragraph count within tolerance, all images present, no raw `**`/`![`
  leaking) → publish only on pass.
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
- Login: avatar/`提问` button = in; `/signin` URL or `登录` button = out.
- Captcha: `*captcha*`/`yidun`/`NECaptcha` selectors + `验证码/安全验证/滑动`
  text scan.
