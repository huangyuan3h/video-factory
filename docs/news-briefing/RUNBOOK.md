# 世界简报操作手册（给 AI agent 每天照着跑，v1）

> 分支：`feat/world-briefing`（在新版 VF `~/Projects/video-factory-p2` 上开发，不合 main）。
> 笔名：`躺平的老黄`。永不写真名。无人值守，不提问。不用 Crimson 代码或数据。不开可见浏览器。
> 真实发布：只本地产出，不接发布。若需上传测试，只能 unlisted、不进播放列表、标题前缀 `[试片]`。

## 0. 一条命令（每天）

```bash
cd ~/Projects/video-factory-p2
git checkout feat/world-briefing && git pull --ff-only
./scripts/vf briefing --date YYYY-MM-DD --json        # 全量：md + mp4 + 封面 + 描述 + manifest
./scripts/vf briefing --date YYYY-MM-DD --text-only --json  # 只出文稿（先审稿再渲染）
```

- 默认输出：`data/output/world_briefing/<date>/`
  - `briefing_private.md`（含「对你」主人版）、`briefing_public.md`（公开版「这意味着什么」）
  - `script.json` / `script_bound.json` / `script.md`、`description.txt`（全部来源链接）
  - `cover.png`（2560x1440）、`video.mp4`（2560x1440 CRF17）、`subtitles.ass/.srt`
  - `assets_manifest.json`（每段 license+出处+检索词+得分）、`rank_log.json`（打分理由）、`factcheck.md`
- `--resume`：`status.json` 已完成则跳过。`--voice` 可覆盖配音（默认 `zh-CN-YunjianNeural`，见 `config/world_briefing.yaml`）。
- worker 侧直调：`cd apps/worker && uv run python scripts/run_briefing.py --date YYYY-MM-DD [--text-only]`

## 1. 流水线（搜集→核实→排序→写稿→素材→成片→质检）

1. **搜集**：`src/services/world_briefing/pipeline.collect` 读策展快照（v1 仅 `2026-10-03` 策展，
   对齐金样；其余日期回退模板并标注 `fallback:true`）。
   正式接 RSS 时按 `config/news_sources.yaml`（官方博客/RSS + 主流媒体 + arXiv/HN/GitHub + 市场公开页，
   可选 NewsAPI/GNews 仅有 key 才启用）拉取过去约 24 小时（上海时区）。
2. **去重聚类**：`scoring.dedupe_cluster`（标题归一化 + 同板块合并，保留多源）。
3. **排序**：`scoring.rank_items`（重要性×0.5＋新颖性×0.25＋相关度×0.25，保留理由到 `rank_log.json`），
   板块顺序 AI→科技→经济与市场→地缘与冲突，取 6–10 条。
4. **写稿**：`script_builder` 同一次产出两版（私人版「对你」依据 `config/reader_profile.yaml`；
   公开版「这意味着什么」，严禁私人项目/仓位/健康/真名）。市场快照必有指数点位/涨跌幅/汇率/油价（标约）。
   结尾恰好 2 个可视频选题。禁止编造数字。
5. **核实**：`factcheck.factcheck`（数字溯源快照、来源数、真名、隐私、问候+免责）。FAIL 则停更，不进渲染。
6. **素材**（`assets.build_assets`，合法优先）：
   1.官方press kit → 2.政府公有领域 → 3.自绘（市场图表/要点卡 2560x1440）→ 4.大学/机构配图 → 5.Pexels。
   禁止路透/AP/Getty 版权照片。禁止泛财经空镜兜底（`business/city` 等泛词直接拒）。
   Pexels（有 key 才启用）：视频优先、≥1080p（优先 4K/1440p）、相关度≥70（标题/标签/描述打分）、
   单集不重复、记录检索词与得分。低于阈值改用自绘。全记录到 `assets_manifest.json`。
   规则：不得用 read 工具打开 png/jpg（用 `ffprobe`/`identify` 检查，见 §3）。
7. **成片**：`type=world_briefing`（预设见 `src/config.py` + `config/series.d/world_briefing.json`，
   配音默认档、停顿沿 daily_news gap）。整段一集（约 6–10 分钟），每条一段，
   片头日期+目录、片尾 2 选题，字幕 1440p，封面 2560x1440。
8. **质检**：文稿对照 `docs/news-briefing/STYLE.md` 自评（覆盖面/数字密度/来源质量/对你相关度/可视频化，
   <90 说明差在哪）；视频 `ffprobe` 时长/分辨率/音轨、字幕行数、manifest license 全覆盖、无版权照片；
   `vf check` 全绿。

## 2. 文稿标准（STYLE 速查）

- 6–10 条，过去约 24 小时（上海时区）。每条：粗体一句话标题；3–6 句事实（数字/日期/主体）；
  「对你」一句贴读者画像；来源=官方优先+≥1 主流交叉，Markdown 链接。
- 单来源条目 ≤1 个且需注明 `single_source_reason`；无来源 0 个；编造数字直接 0 分。
- 语言：简体短句，笔名 `躺平的老黄`，视频口播必有免责声明。

## 3. 质检命令（每天贴到报告）

```bash
./scripts/vf briefing --date 2026-10-03 --text-only --json
ffprobe -v error -select_streams v:0 -show_entries stream=width,height,duration,codec_name -of default=noprint_wrappers=1 data/output/world_briefing/2026-10-03/video.mp4
ffprobe -v error -show_entries stream=index,codec_type -of default=noprint_wrappers=1 data/output/world_briefing/2026-10-03/video.mp4
identify data/output/world_briefing/2026-10-03/cards/econ-market-snapshot.png  # 不用 read 工具开图
./scripts/vf check --json && ./scripts/vf doctor --json
```

- 通过线：`factcheck PASS`、`2560x1440`、`duration≈360–600s（约6–10分钟，±5%容差）`、
  音视频双轨、`assets_manifest` 段数==视频段数且 license 全有、`vf check` 全绿。

## 4. 投资线索规则

- 若发现扣费后正收益的投资线索，按 `~/Projects/wealth-ideas/profit-leads.md` 规则追加（日期/指标/数字/来源集数/下一步）。
- 世界简报为新闻流，非回测筛选：无 backtest 数字时不追加，不硬凑。本集（2026-10-03）无此类线索，未追加。

## 5. 提交与报告

```bash
git add -A && git commit -m "feat(briefing): ..." && git push origin feat/world-briefing  # 不合 main
```

- 报告写 `.opencode-runs/news_briefing_v1_report.md`（成片路径、文稿路径、自评、未解决项），最后一行 `NEWS BRIEFING V1 DONE`。
- 上传测试（如需）：YouTube 只能 unlisted、不进播放列表、标题前缀 `[试片]`（本集未上传，仅本地）。
