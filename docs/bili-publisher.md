# B站发布（Bilibili publisher, headless-by-default）

Playwright 半自动投稿工具，一次只投一个视频。只走官方网页
（`member.bilibili.com`），不用任何第三方 credential 工具，
不读取/导出任何浏览器 cookie。

研究背景：`docs/bilibili-publishing-research.md`
（官方开放平台不对个人开放；`bilibili-api-python` 已停更；
推荐半自动 + 人工审核闸）。

## 一句话投稿一集

```bash
# 演练：上传 + 填表 + 截图已填表单，不投稿
scripts/bili_publish.sh ~/Projects/video-factory/.opencode-runs/bili/ep1_publish_payload.json --draft-only
# 真投：同上，校验通过才点投稿；成功后打印 BV/URL，存 published.json 并 open
scripts/bili_publish.sh ~/Projects/video-factory/.opencode-runs/bili/ep1_publish_payload.json --mode publish
# 模块入口（在 apps/worker 下）：
# uv run python -m src.publishers.bili_publish --payload <path> [--draft-only] [--headed] [--force] [--no-open]
```

Flags：`--payload`（必填）、`--mode draft|publish`（默认 `draft`）、
`--draft-only`（只填表，覆盖 `--mode`）、`--headed`（可见窗口；
默认 headless）、`--headless`（强制 headless）、`--force`
（`published.json` 已有 URL/BV 时仍重投）、`--no-open`
（成功后不 `open <url>`）、`--profile`、`--smoke-dir`、
`--smoke-label`、`--login-timeout-s`（默认 600 = 10 分钟）、
`--skip-logged-out-check`。

Payload（`publish_payload.json`）：`title`（≤80 中文）、
`description`（无外链、含免责 + AI 句 + `躺平的老黄`）、
`tags`（≤10）、`tid`（207 知识-财经商业）、`copyright`（1 自制）、
`video_path`、`cover_path`（1920x1080）、`ai_declaration`。
构造器：`src/publishers/bili.py::build_bili_payload_from_yt`
（由 YouTube `ep/yt/ep<N>.json` 适配），校验：
`validate_bili_payload`，单元测试
`tests/test_bili_payload.py`。

## 默认 headless，需要登录时才可见

- 默认 `headless=True`，持久 profile
  `~/.video-factory/bili-profile`。绝不碰用户日常浏览器，
  仓库里无任何凭据，绝不删除/重置 profile。
- 先做便宜的登录检查（`member.bilibili.com/platform/home`，
  avatar-`img`/用户名 = 在；跳到 `passport.bilibili.com/login`
  或只剩登录占位 = 不在）。homepage 的裸「投稿」按钮和
  `header-avatar-unlogin` 占位**不算**登录（2026-09-27 实测
  新 profile 也显示它们）。
- 未登录/QR/验证码/风控时：关闭 headless，用**同一个**
  profile 重开 headed（可见），Chrome 置前，`osascript`
  通知「B站需要扫码登录」，写
  `.opencode-runs/bili/NEED_LOGIN`，等 owner 扫码最多 10 分钟
  （每 3 分钟重通知一次），然后在该 headed 会话里自动继续。
  验证码/风控**永远不自动解**。
- 结果 JSON 带 `headless_started`、`headless_used`、
  `fallback_to_headed`、`login_needed`，可审计。

## 登录过期时

- 弹出可见 Chrome + Mac 通知 + `NEED_LOGIN` 文件。
- 10 分钟内在该窗口扫码/手动过验证。
- 成功后 flag 删除，流程自动继续。
- 超时 → exit 2 / `BLOCKED: login`（或 `BLOCKED: verification`），
  窗口**保持可见**，不自动关，供 owner 手动处理。

## 日志、截图、产物去哪了

- 每次 stdout JSON（`verification.ok`、`bvid`/`public_url`、
  `review_state`、`headless_used`）；最后一行 `DRAFT DONE`、
  `PUBLISH DONE`（+ `PUBLISHED URL:` / `BVID:`）或
  `BLOCKED: <reason>`。
- 截图：`~/Projects/video-factory/.opencode-runs/bili/`
  （`<label>_filled_form.png`、`<label>_result.png`、
  `<label>_logged_out.png`、`ep1_login_qr.png`）。
- 真投成功：`published.json`（url + bvid + status + timestamp +
  screenshots）存 payload 旁边；URL 会被 `open`（除非 `--no-open`）。
- 幂等：publish 模式下 `published.json` 已有 URL/BV 则拒绝
  （除非 `--force`）；draft 模式总跑。
- 干净退出：正常结束关闭 browser，只杀**自己**
  profile 的残留 Chrome（`cleanup_own_chrome_processes`）——
  Docker、`:8000` worker、用户应用绝不动。
  **BLOCKED 时不关窗口**（留给 owner 看）。
- 跑前守则：`memory_pressure` + `pgrep -fl "ffmpeg|whisper|render"`
  看一眼；一次只跑一个重任务（上传本身是轻的，可以和渲染并行，
  见烟测任务约束）；只杀自己起的进程。

## 限制 / 护栏

- 一次 exactly ONE 视频（给的 payload）。不做关注/评论/设置等。
- Draft-first：传视频 → 等传完 → 填标题/简介/分区/标签/封面/
  自制/AI → 截图已填表单 → 校验（标题在、上传完成、无验证码字样）
  → publish 模式才点投稿（最多 3 次）。
  分区目标 知识-财经商业 `tid=207`（best-effort，截图复核）；
  自制必选；AI 开关有就打开，没有则简介里已带
  「本视频文案由 AI 辅助生成」；简介必带财经免责
  「本视频为投资者教育，不构成投资建议，历史回测不代表未来表现。
  投资有风险，入市需谨慎。」只用笔名「躺平的老黄」。
- 投稿后等转码/审核态，记录 BV + URL（审核中也算成功）。
- 人性化 pacing：分段暂停、慢速打字、上传后多等几秒。
  所有 Playwright 等待都有显式超时；登录/验证码循环有硬 10 分钟
  deadline——脚本永远不无限 hang。
- 风控/验证码（`-663`/鉴权失败/滑动/安全验证）→ 立刻停，
  窗口留可见，通知，报 `BLOCKED: verification` 并写清需要什么，
  **绝不绕过**。

## 脆弱选择器（已知）

B 站经常改版，所有定位都多候选（见 `bili.py::*_SELECTORS`）：

- 标题：`input[placeholder*="标题"]` → `.video-title input` → …
- 简介：`textarea[placeholder*="简介"]` → `.video-desc textarea` → …
- 视频：`input[type=file][accept*=video]` → 通用 file input →
  上传按钮 + file chooser。
- 封面：`input[type=file][accept*=image]` → 「上传封面」按钮 +
  file chooser。封面统一用 `ensure_cover_16x9` 垫成 1920x1080。
- 分区/自制/AI/投稿按钮都是文本多候选 + best-effort，
  以截图为准，失败不硬闯。
- 登录：avatar-`img`/用户名 = 在；`passport…/login` 或无用户名
  的登录占位 = 不在（`classify_login_state`，单元测试覆盖）。
- 验证码/风控：`*captcha*`/`yidun`/`geetest`/`risk` + 
  `验证码/安全验证/滑动/风控/-663/鉴权失败` 文本扫描。
