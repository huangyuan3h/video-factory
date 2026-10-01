# 每日自动财经 / 政治 / 科技新闻视频方案（调研 + 设计）

> 频道笔名：`躺平的老黄`（全片只用笔名，不出现真名）。
> 目标：每天自动生成财经、政治、科技新闻视频，发布到 YouTube，每个主题一个播放列表。
> 本文只写文档，不改任何代码，不提交，不安装全局软件，不上传任何东西。
> 调研方式：只读方式查看 `~/Projects/karios-desktop`（分支 `db-enhance`，有未提交改动，未做任何修改、未做任何 git 操作）与 `~/Projects/video-factory` 现有代码；条款与 API 均附链接。
> 日期：2026-09-26。无人值守假设见文末 §13。

---

## 1. 目标与范围

### 1.1 做什么

- 每天从 Karios 取当天 2–3 个“核心矛盾点 / 主线”，生成 1–3 集新闻视频。
- 每集以“真实相关视频为主 + 图片为辅 + Karios 图表 / 数据卡片点缀”，配云健中文配音 + 字幕，质检后以 `unlisted` 或定时公开方式进对应播放列表。
- 全链路可重跑、可审计：选题依据、脚本事实来源、每段素材来源与授权、质检报告、上传回读，全部落盘。

### 1.2 不做什么（v1 边界）

- 不做 24 小时滚动快讯、不做直播切片、不做突发 5 分钟内抢发。
- 不下载第三方新闻台成片做二创主素材（Content ID / reused content 风险，见 §5）。
- 不碰 Karios 工作树，不在 Mac 上同时跑多个重任务（见 §8）。

---

## 2. Karios 现状：产出什么、存在哪里、怎么读

### 2.1 新闻相关模块一览（只读结论）

| 模块 | 文件 | 产出 |
|---|---|---|
| 新闻摘要 API | `apps/ai-service/src/routes/news.ts` | 输入 `items[{title,…}] + hours`，输出 300–400 字中文财经摘要（数字列表）。提示词强制“只用标题事实”，`temperature=0`。无持久化。 |
| 主线解释 API | `apps/ai-service/src/routes/mainline.ts` | 输入 `{date, themes[{kind,name,…}]}`，输出每主题 `logicScore/logicGrade(S/A/B)/logicSummary(英文≤3句)/catalysts`。失败兜底全 B/50 分。无持久化。 |
| 投研日报 API | `apps/ai-service/src/routes/report.ts` + `apps/ai-service/src/investmentDailyReportNormalize.ts` | 输入 Dashboard Markdown，输出严格 JSON：`trafficLightPositionAndSentiment / marketEnvironmentHighlights(恰好5条) / hotIndustriesFormalAnalysis(≥300字) / capitalFlowAndMainline(3–6段) / topStocks(恰好3) / topNews(恰好5)`。归一化层会自动补齐缺失数组、截断超长。无持久化（调用方决定存哪）。 |
| RSS 抓取 | `services/data-sync-service/src/data_sync_service/service/news.py` | 5 个默认源（财联社电报、华尔街见闻全球快讯、金十快讯、财联社深度、证监会要闻，经 RSSHub），跨源标题去重（归一化精确 + 字符集 Jaccard >0.8），72 小时滚动删除。 |
| LLM 富化 | `services/data-sync-service/src/data_sync_service/service/news_enrich.py` | Tier0 预过滤（噪音词 + Tier-A 白名单 + INCLUDE 正则）→ Tier1 小批量 LLM 抽 `tickers/sectors/eventType/importance(0–5)/aiSummary(≤25字)/actionability` → Python 本地算 `relevance = importance*15 + watchlistBoost(每 ticker +30，上限60)`。失败只 mark 单条。 |
| 早报选择器 | `services/data-sync-service/src/data_sync_service/service/morning_brief.py` | 公式 `importance*0.3 + relevance*0.3 + freshness*0.2 + watchlistBoost*0.2 + actionable(+5)`，`BRIEF_SIZE=7`，分类 `watchlist/risk/macro/sector`，排除回顾/月报/年报与 `historical`。产出 `morning(08:30) / midday(12:30)` 两档。 |
| 早报卡 | `apps/desktop-ui/src/components/dashboard/MorningBriefCard.tsx` + `apps/desktop-ui/src/lib/queries/news.ts` | 读 `GET /api/news/brief/latest?brief_type=morning`，分组展示 + AI 摘要 + tickers/importance/relevance 角标。 |
| 行业主线分数 | `services/data-sync-service/src/data_sync_service/service/mainline.py` | 资金面（20d/5d 排名 + 10d 胜率）40 分 + 广度（涨停数/连板/大涨占比）40 分 + 趋势（MA20/RPS）20 分；连续 3 天 `total>80` 即 `isMainline`。供“核心矛盾点”使用。 |

### 2.2 数据存在哪里（Postgres 真值）

| 表 | 定义文件 | 关键字段（video-factory 只需读） |
|---|---|---|
| `news_sources` | `services/data-sync-service/src/data_sync_service/db/news.py` | `id/name/url/enabled/tier/category/last_fetch` |
| `news_items` | 同上 | `id/source_id/title/link/summary/published_at/fetched_at/tickers/sectors/event_type/importance/relevance_score/ai_summary/actionability/enrichment_status/enriched_at/enrichment_model`。注意标题/摘要入库时已 strip HTML。 |
| `morning_briefs` | `services/data-sync-service/src/data_sync_service/db/morning_brief.py` | `id(=YYYY-MM-DD-morning/midday/trading-*) / brief_date/brief_type/items(JSONB)/macro_overview/model_version/source_item_ids/markdown/created_at`。`items` 每条含 `score/category/link`。 |
| 行业主线 | `db/industry_mainline_scores.py`、`db/industry_mainline_metrics.py`、`db/industry_fund_flow.py`、`db/daily.py` | `asOfDate/dates/allScores[{industryName,flowScore,breadthScore,trendScore,totalScore,isMainline,flags}] / currentMainline`（经 `get_cn_industry_mainline()` 组装）。 |
| 市场环境/情绪 | `service/market_environment_zh.py`、`service/market_sentiment.py`、`service/macro_snapshot.py` | 日报 Markdown 的上游事实表，video-factory 不必直读，先读日报 JSON 即可。 |

保留期注意：`news_items` 默认只保留 72 小时（`delete_old_items(hours=72)`）。日报/主线分数保留更久。video-factory 必须当天取、当天快照，不要指望回翻一周前的 `news_items`。

### 2.3 video-factory 怎么读（推荐顺序）

首选 HTTP（不直连 DB 就能跑通 MVP）：

1. `GET /api/news/items?limit=100&hours=24` → 当天候选池（含富化字段）。
2. `GET /api/news/brief/latest?brief_type=morning`（午间再取 `brief_type=midday`）→ Top7 + `score/category`，直接当选题输入。
3. `POST /investment-daily`（ai-service）或复用已生成的日报 JSON → `topNews(5) + capitalFlowAndMainline + marketEnvironmentHighlights(5)` 当脚本事实基座。
4. `GET /market/.../mainline`（`get_cn_industry_mainline` 的 HTTP 封装）→ 当天 `currentMainline` + `allScores`，对应“核心矛盾点”。

备选只读 SQL（Karios DB 只读用户，`default_transaction_read_only=on`，只 `SELECT`）：

- `SELECT … FROM news_items WHERE fetched_at >= now()-interval '24h' ORDER BY COALESCE(published_at,fetched_at) DESC LIMIT 200`
- `SELECT * FROM morning_briefs WHERE brief_date=current_date ORDER BY created_at DESC LIMIT 5`
- 主线分数表按 `date` 取最新一天。

约束（必须遵守）：

- 绝不写 Karios DB，绝不改 `~/Projects/karios-desktop` 任何文件，绝不在该仓库做任何 git 操作。
- 每次拉取后在 video-factory 任务目录存一份快照（`karios_snapshot.json`：brief + items + mainline + 拉取时间），后续脚本/审计只认快照，保证可复现。
- Karios 富化偏 A 股（财联社/金十/证监会 + 自选相关度）。政治/科技国际新闻不能只靠它，见 §6.1。

---

## 3. video-factory 现状：能复用什么、缺什么

### 3.1 能复用（均已在代码中验证）

- `type=news` 专链：`apps/worker/src/services/news_service.py`（`is_news_request` 按 `content_type==news` 触发）+ `apps/worker/src/sources/news_api.py`（`NewsAPISource`，GNews 用 `image/max/apikey`，NewsAPI 用 `urlToImage/pageSize/X-Api-Key`，`source` 兼容对象/字符串）+ `apps/worker/src/config.py`（`news_provider=gnews`，`news_lang=zh`，`news_country=cn`，`news_max_articles=5`，`news_cache_ttl_s=900`）。任务侧产物：`news_images/`、`news_articles.json`、`task_logger` 的 `source_name/source_url/news_articles`。
- 图文素材栈：`apps/worker/src/services/material/material_fetcher.py`（`MaterialFetcher`，中→英 `KEYWORD_TRANSLATIONS` + 新闻安全 `FALLBACK_KEYWORDS`，全任务去重 `seen_*`）+ `pexels_service.py`（`GET /videos/search`、`GET /search`，横屏 1080p 选片、去重 `exclude_ids`、alt 过滤）+ `pixabay_service.py`（`GET https://pixabay.com/api` 图片兜底）+ `local_assets_service.py`（本地库）。合成（ComfyUI 图/视频）默认关闭，news 链路明确禁用合成。
- indicator 系列版式：`apps/worker/src/services/indicator/manifest.py + script.py`（`manifest.json → 一图一段 → 数字原样校验 → 缺失追加 key_point`）+ `apps/worker/src/services/compose_service.py`（`fullframe` 白底 1920x950 图区 0–949 + 130px 字幕带，`letterbox` 深色底；字体 `/System/Library/Fonts/STHeiti Medium.ttc`）+ `docs/indicator-episodes.md` + `docs/indicator-episode-runbook.md`（边框/分离/字幕同步/Whisper/关键帧的现成质检脚本与阈值）。
- 配音字幕：`config.py::DEFAULT_TYPE_PRESETS`（`news` 预设：云健 `zh-CN-YunjianNeural`、`+0%`、`images_first`、`presenter_intro=True`、BGM 0.2；`indicator` 是 `+2%/fullframe/BGM0.1`）+ `core/tts/*`（`resolve_voice` 按 `language` 自动切 `zh→Yunjian / en→Aria`）+ `core/subtitle_gen.py`（边界对齐、长句拆行、上限 landscape 26 字、SRT/ASS 双出）+ `services/presenter.py`（`大家好，我是躺平的老黄。`确定性问候、封面署名）。
- 调度上传：`apps/worker/src/scheduler.py`（APScheduler cron，已有 `Task/Run/Source` 模型）+ `apps/worker/src/publishers/youtube.py`（Data API v3 上传 + 播放列表尾插，读 `HTTPS_PROXY/HTTP_PROXY`，日志 `YouTube API using proxy: …`，超时 `external_api_timeout_s`）+ runbook §6 已验证代理 `http://127.0.0.1:7890` 与 `privacy=unlisted`、`default_language=zh-CN` 流程。`config.py` 默认 `youtube_default_privacy=unlisted`、`publish_require_review=1`、`series_output_folders=1`。

### 3.2 缺什么（v1 必须新做，v2 再做）

- v1 必做：① 真正相关的视频主链路（官方/公司/CC 视频检索 + 下载转码 + 相关度打分，§5–§6）；② 授权过滤与署名落盘（白名单 + 描述署名 + sidecar）；③ 事实核对闸（数字必须来自快照，缺失写“依据不足”）；④ Karios 图表/数据卡片渲染（把主线分数/资金表画成 1920x950 白底图，复用 fullframe）；⑤ 播放列表映射 + `unlisted`/定时公开策略 + 失败重试编排。
- v2 再做：视觉模型精排、多语言（英文配音 + `en-US-AriaNeural`）、A/B 封面、评论区置顶来源、自动追更（同一事件第二天增量集）。

---

## 4. 核心难点：真正相关的视频（为主）+ 图片

当前 `type=news` 只有文章配图（GNews/NewsAPI 不给视频文件），Pexels 兜底容易变成“泛泛空镜”（城市/股市/握手）。v1 立规矩：

- 每集必须至少 60% 时长是“事件级相关视频”（官方发布会、公司财报会、央行发布会、国会/白宫公开画面、交易所开市敲钟、CC 新闻现场），其余才允许主题级空镜（行业/城市/工厂/交易大厅）。
- 每段素材必须有 `relevance_score`（0–100）与 `license_tier`（见 §5），低于阈值不许上主轨，宁可降级为数据卡片 + 配音解说。
- 相关度判断三件套（按成本从低到高）：
  1. 文本先验：标题/实体/时间三对齐（关键词命中 + 同一主体 + ±3 天内发布）。
  2. Whisper 核对：对候选视频抽音轨 → `faster-whisper small(int8)` 转写 → 与本段脚本做实体/数字交集（人名/机构/数字命中≥2 才算强相关）。Mac 上一次只跑一个 Whisper，见 §8。
  3. 视觉模型精排（v2）：抽帧 2fps → VLM 打分“画面主体是否=新闻主体”（如美联储主席/财报会/发射场/工厂），分数进 `relevance_score`，低分淘汰。

---

## 5. 版权与合规（重点，分级 + 程序化）

> 原则：Content ID 只认“是否匹配”，不认“你觉得是不是 fair use”。先保频道不被认领/警告，再谈二创。YouTube 对“reused content”（无实质原创评论的剪辑/合集）会直接影响变现资格，申诉成本极高。

- YouTube reused content（变现资格）：`https://support.google.com/youtube/community-guide/271248162/faq-reused-content-youtube%E2%80%99s-partner-program?hl=en`
- Content ID 与 fair use 的鸿沟：`https://blog.youtube/news-and-events/content-id-and-fair-use`；EFF 白皮书：`https://www.eff.org/wp/unfiltered-how-youtubes-content-id-discourages-fair-use-and-dictates-what-we-see-online`
- GNews 条款（第三方内容版权仍归原主，图片需自行确保权利）：`https://gnews.io/legal/terms-of-service`；文档：`https://docs.gnews.io/`
- NewsAPI 条款（不得复制/再发布受版权保护材料）：`https://newsapi.org/terms`
- Pexels 许可：`https://www.pexels.com/license/`；完整条款：`https://www.pexels.com/terms-of-service`
- Pixabay 许可摘要：`https://pixabay.com/service/license-summary/`；完整条款：`https://pixabay.com/service/terms`
- Wikimedia Commons 许可：`https://commons.wikimedia.org/wiki/Commons:Licensing`；站外复用：`https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia`；API：`https://commons.wikimedia.org/wiki/Commons:API`
- 美国联邦政府作品公有领域（17 USC §105）：`https://www.law.cornell.edu/uscode/text/17/105`
- 美联储直播/回放：`https://www.federalreserve.gov/live-broadcast.htm`；欧央行发布会（含 footage 下载）：`https://www.ecb.europa.eu/press/press_conference/html/index.en.html`
- YouTube Data API `search.list`（`videoLicense=creativeCommon` 过滤）：`https://developers.google.com/youtube/v3/docs/search/list`

### 5.1 第一级：可放心用（默认只用这些做主素材）

| 来源 | 为什么放心 | 程序怎么找 | 授权怎么记 |
|---|---|---|---|
| 美国联邦政府作品（白宫、国会、美联储、SEC、交易所监管公告、NASA 等联邦雇员职务作品） | 17 USC §105：联邦政府职务作品无版权、即公有领域。但注意：承包商作品、州政府作品、政府网站上的第三方投稿不在此列。 | 白宫/国会/美联储官网视频页 + 官方 YouTube 频道（频道白名单）按实体检索；`YouTube Data API search.list(q=实体, type=video, channelId=官方频道)` 限定来源。 | `license=US-PD-105`，记 `source_url + agency + 发布日期 + 链接`。 |
| 美联储 / 欧央行 / 国会听证 / 白宫简报的官方直播与回放 | 同上多为公有或官方公开；欧央行明确提供 press footage 下载（见上链接）。 | Fed 官网 live 页 + ECB press 页 `Video footage` + 官方 YT 频道 `FOMC Press Conference` 系列。 | `license=official-public`，记直链与发布会日期。 |
| 公司官方发布会 / 财报会 / press kit / media room（含 TSMC / Nvidia / Apple / Tesla 等 IR 页） | 公司主动公开的 PR 素材默许媒体报道性使用；条款以各 press kit 页为准，一般要求署名、禁断章取义。 | 公司 IR `investors / newsroom / press-kit` 页抓直链（mp4 + 图片），或官方 YT 频道 `channelId` 限定检索。先人工建 30 家白名单域名，程序只从白名单域下载。 | `license=press-kit`，记 `company + press-kit URL + 使用页条款截图/文本`。 |
| Pexels / Pixabay（图 + 视频） | Pexels License / Pixabay Content License 允许免费商用、改编、可进 YouTube（含变现），无需署名（建议署名）。禁：单独售卖原图、冒充代言、商标/可识别人物商用风险自负。 | 已有 `MaterialFetcher`：`GET https://api.pexels.com/v1/videos/search + /search`（`query/orientation/per_page`）与 `GET https://pixabay.com/api`（`q/per_page/orientation/image_type=photo`）。中文先经 `KEYWORD_TRANSLATIONS` 转英文，财经空镜用新闻安全 fallback。 | `license=pexels/pixabay`，记 `photo/video id + photographer + page_url + 下载时间`。这一级也必须落盘（不是“免费就不用记”）。 |
| Wikimedia Commons（图为主，少量视频） | 只收自由许可（CC BY / CC BY-SA / 公有领域），每文件页写明许可；站外复用必须按页署名，BY-SA 衍生需同许可。 | MediaWiki/Commons API：`action=query&generator=search&gsrsearch=实体&prop=imageinfo&iiprop=url|user|extmetadata`，解析 `UsageTerms/LicenseShortName/Artist`，只收 `CC-BY/CC-BY-SA/PD`，拒绝 `NC/ND`。 | `license=CC-BY-x / CC-BY-SA-x / PD`，记 `File:页 + 作者 + 许可链接`，描述区按 Attribution Generator 格式署名。 |
| YouTube 上 CC BY 视频（`videoLicense=creativeCommon`） | 上传者主动选 CC BY，允许复用（含商用），条件是署名。注意：CC-BY 仍可能含第三方插曲（音乐/画面），Content ID 仍可能对其中片段认领。 | `search.list(part=snippet, q=实体+事件, type=video, videoLicense=creativeCommon, videoEmbeddable=true, publishedAfter/Before=事件±7天, order=date)`，再调 `videos.list(part=status,contentDetails)` 复核 `licensedContent`，白名单频道优先。 | `license=CC-BY-YT`，记 `videoId + 标题 + 频道 + 许可 + 下载片段起止`，描述区必须署名（标题+作者+原链接+许可名）。 |

### 5.2 第二级：有条件可用（只能短引用 + 强评论，默认不用）

- 对象：新闻机构片段（路透/AP/彭博/财经电视台的现场/采访）。
- fair use 判断要点（美国法四要素，无 bright-line，Content ID 不认语境）：
  1. 目的：必须 transformative（评论/批评/教学/解释），且配音解说占比显著高于引用（建议引用 ≤8 秒/次，全片引用 ≤15%，绝不整段搬运）。
  2. 性质：事实性新闻比虚构作品更易主张，但不等于免死金牌。
  3. 数量：只用“为讲清观点所必需的最短”，且不用“最精彩的心脏部分”当封面/钩子。
  4. 市场：不得替代原片（不做“浓缩版发布会”），必须导流回原链接。
- 程序闸：默认关闭，需人工在任务里显式 `allow_short_quote=true` + 填写 `quote_reason`；代码层强制 `单段≤8s/全片≤15%/必须有≥3倍时长原创解说覆盖`，否则渲染前 fail-fast；描述区写 `©原版权方，仅作评论性引用，原链接：…`。
- 风险明示：即使满足四要素，仍可能被 Content ID `claim`（分流/限流）或人工 `takedown`（吃警告）。财经号建议全片 0 新闻台引用，政治号更要 0。

### 5.3 第三级：不要用（写进封禁清单，程序直接拒）

- 影视剧/综艺/体育赛事/演唱会/MV/纪录片正片片段（Content ID 重灾区）。
- 其他 YouTube/B 站/抖音/TikTok 创作者的成片（标准许可，无 CC 标记）。
- GNews/NewsAPI 返回的 `image` 直接热链或原样铺满全片当主视觉（条款已声明第三方版权归原主，且 `newsapi.org/terms` 禁止复制再发布受版权保护材料；最多当选题缩略图参考，或经权利人许可才用）。
- 无许可的付费图库水印图、微博/微信截图的他人摄影、AI 冒充真人真事的“伪现场”（另涉平台 AIGC 标注与新闻真实性红线）。
- 任何“去水印”“翻录 Concert”“下载器破解 DRM”路径。

### 5.4 授权记录（自动写进视频描述 + sidecar，缺一不可）

- 每段素材落盘：`{segment, file, source_name, source_url, license_tier, license_name, author, retrieved_at, relevance_score, quote_seconds?}` → `material_attribution.json`。
- 描述区自动生成 `【素材与授权】` 段：官方/PD/CC 逐条署名（作者 + 原链接 + 许可）+ `©引用` 单列 + Karios 数据致谢（“选题/数据来自 Karios 日报快照，解读为本频道原创”）。
- `news_articles.json`（已有）继续保留，但仅当“选题来源”，不当“画面授权”。

### 5.5 相关度判定（防“牛头不对马嘴”）

- 门槛：主轨视频 `relevance_score≥70`，图片 `≥60`，否则降级或换数据卡。
- 打分 = 文本先验 40%（实体命中 + 时间窗 + 来源白名单）+ Whisper/字幕 30%（转写实体交集）+ 视觉/VLM 30%（v1 可先人工抽检，v2 全自动）。
- 政治类额外加“主体一致”硬闸：人物张冠李戴（把 A 认成 B）直接整段废弃重拉。

---

## 6. 每日流程（从选题到上传）

```
06:30 Karios 早报快照 → 08:45 选题会(自动) → 09:00 脚本v1 → 09:20 事实核对闸
→ 09:30 素材检索(视频为主) → 10:00 授权过滤+相关度打分 → 10:30 剪辑合成
→ 11:00 配音字幕 → 11:30 质检(关键帧/四边/字幕同步/Whisper数字) → 12:00 上传unlisted
→ 午间增量(12:30 brief)可选加更 → 晚间定时公开 → 失败进重试队列
```

| 步骤 | 输入 | 动作 | 输出 | 失败处理 |
|---|---|---|---|---|
| S0 快照 | Karios brief/items/mainline/日报 | 存 `karios_snapshot.json`（含拉取时间与 model_version） | 当天唯一真值 | 拉不到则用昨日快照降级 + 标题注明“昨日盘点”，连续 2 天拉不到则停更并告警 |
| S1 选题 | 快照 Top7 + `currentMainline` + 富化分 | 自动挑 2–3 个核心矛盾点（财经≥1，政治/科技轮换；政治必须双源交叉） | `topic.json{title, entities, event_date, evidence_links, angle}` | 候选 <2 则从 `news_items(hours=24, importance≥3)` 补足，仍不足则停更 |
| S2 脚本 | `topic.json` + 日报 `topNews/capitalFlow` | LLM 写 3–8 段口播（钩子→事实→解读→数据→收束），每段带 `keywords + evidence` | `script.json/script.md` | 触发数字校验失败则只重写问题段（复用 indicator 的 number check 思想） |
| S3 事实核对 | 脚本 vs 快照 | 数字/人名/机构/时间逐条对快照原文；无出处数字改“依据不足”或删；政治类加中立词检查 | `factcheck.md{PASS/FAIL}` | FAIL 不许进渲染 |
| S4 素材检索 | 每段 `keywords+entities` | 并行查：①官方/公司白名单 ②CC-YT(`videoLicense=creativeCommon`) ③Commons ④Pexels视频 ⑤Pixabay/配图；视频优先下载 1080p 横屏 | `candidates/` + `search_log.json` | 无强相关视频则该段转数据卡（见 S5），不许硬凑空镜 |
| S5 授权过滤 | 候选池 | 白名单域名 + 许可解析（Commons/YT/CC）+ 第三级直接拒 + 短引用需人工 flag | `material_attribution.json` | 引用超限/许可不明 → 淘汰并重拉 |
| S6 相关度打分 | 候选视频/图 | 文本先验 + Whisper 抽检 +（v2）VLM 抽帧；排序取顶 | 每素材 `relevance_score` | 主轨 <70 则降级 |
| S7 剪辑 | 脚本 + 主轨视频 + 数据卡 | 视频为主（manifes t式一段一主素材，`fit=contain/motion=none` 可复用 indicator 逻辑），Karios 图表/资金卡插 1–3 张（1920x950 白底 fullframe），转场 0.5s | `timeline.json` | 图表缺失则用文字卡兜底，不空屏 |
| S8 配音字幕 | timeline | 云健 `+0%`（财经可 `+2%` 跟 indicator 走），`sentence_gap 0–0.75s`，字幕 landscape ≤26 字，BGM 0.1–0.2 | `segment_*.mp3/subtitles.ass/output.mp4` | TTS 失败单段重试 3 次，仍失败则整集 mark 失败 |
| S9 质检 | 成片 | 复用 runbook：边框四边（meanY>200 且无 Y<50）、图/带分离（图墨 y≤949）、字幕同步 0.15s 100%、文本一致、Whisper 数字全对、关键帧人眼（封面笔名/标题/图表无重叠/字幕单行） | `verify_report.txt{PASS/FAIL}` | 任一 FAIL 不许上传，修完重渲 |
| S10 上传 | `output.mp4 + meta.json` | `privacy=unlisted`（或 `publishAt` 定时），`categoryId=25(新闻)/28(科技)`，进主题播放列表尾部，`defaultLanguage=zh-CN`，走代理 `http://127.0.0.1:7890` | `upload.json{videoId,post_url}` + `yt_verify` 回读 | 上传超时按 5 倍超时重试 1 次；回读 `privacy/upload/playlist pos` 任一不对即 FAIL |
| S11 归档 | 全任务目录 | `script/factcheck/attribution/verify/upload` 全进 `data/output/<series>/<task>/` + DB `Run` | 可复现包 | 缺件不许标 completed |

---

## 7. 单集规格与主题难点

### 7.1 时长与结构（建议）

- 时长：财经 6–8 分钟（讲透 1 个矛盾点 + 2–3 个数字），政治 5–6 分钟（事实密度高、评论收敛），科技 6–8 分钟（发布会/财报会有原片可放，可稍长）。硬上限 10 分钟（GNews 脚本提示词与现 `type=news` 5–10 分钟一致，过长完播崩）。
- 结构（7 段式，每段 40–70 秒）：
  1. 钩子 15s（核心事实一句） 2. 背景 60s 3. 关键进展 90s 4. 数据/图表 60s（Karios 卡） 5. 多方说法 60s（政治类必须多方） 6. 影响与风险 60s（含“不构成投资建议”） 7. 收束 + 落款（`我是躺平的老黄` + 订阅）。
- 每天几集：v1 每天 1 集（财经，跑通再加）；稳定后每天 2 集（财经 + 科技/政治轮换）；重大事件日最多 3 集。不要为凑数把同一事件拆 3 集（reused/重复会被判低质）。

### 7.2 三主题素材难点

- 财经：难点是“数字不能错 + 图表现做”。Karios 主线/资金流可直接画卡（白底 1920x950），美联储/ECB/财报会有官方片可引用；忌用“数钱/握手”空镜撑 3 分钟。所有百分点/点位必须与快照一致，小数位原样。
- 科技：难点是“发布会版权 + 产品画面时效”。优先公司官方 keynote/IR 回放 + press kit 图；CC-YT 只能找独立评测的 CC 片，且避开带原厂 BGM 的片段（音乐 claim 重灾区）。AI 生成“伪发布会现场”一律禁用。
- 政治：难点是“中立 + 事实 + 人物不张冠李戴”。只用官方（白宫/国会/央行/交易所）与 Commons/CC 现场；新闻台片段默认 0 引用；脚本禁预测选举结果、禁站队表述、禁煽动词；多方说法必须给出来源；敏感事件（冲突/选举/制裁）无双源交叉则宁可停更。描述区加“事实截至××时间，后续以官方为准”。

---

## 8. Mac 资源与排期（硬规定）

沿用 `docs/indicator-episode-runbook.md §0.6`：

- 一次只跑一个重任务（渲染 / Whisper / 下载转码三选一）。开工前必跑 `memory_pressure` + `pgrep -fl "python|ffmpeg|whisper"`，有人在跑就等。
- 并行 worker 上限 2；Whisper 只用 `small(int8)`，仅数字听错的个别片段用 `medium` 重听；只杀自己起的进程，不杀其他 opencode/Docker/`:8000`。
- 每日排期（避开 indicator 渲染与 Karios 盘后任务）：
  - `06:40` 拉 Karios morning 快照（轻量，可与早盘前错峰）。
  - `09:00–12:00` 新闻单集链（重任务独占窗口，indicator 不许同时渲染）。
  - `12:40` 午间增量判断（只做轻量选题，不重渲除非加更）。
  - `21:00` 后上传/回读（走代理时再开 `127.0.0.1:7890`，平时不开）。
- 合成（ComfyUI 图/视频）在新闻链路保持关闭（`ENABLE_SYNTHETIC=0`），内存不足时直接走数据卡，不许开合成赌运气。

---

## 9. 分阶段实施（先跑通一条财经新闻）

### P0 — MVP：一条财经新闻跑通（1–2 周）

- 范围：Karios morning brief 取 1 主题 → 脚本 → Pexels视频 + 文章配图 + 1 张 Karios 数据卡 → 云健配音 → 字幕 → 质检 → `unlisted` 进财经列表。
- 验收：① `karios_snapshot/material_attribution/verify_report/upload.json` 齐全；② 边框/同步/Whisper 数字全 PASS；③ 描述区署名完整；④ YT 回读 `unlisted+processed+尾位`；⑤ 全程单重任务、无 OOM。
- 不做：CC-YT 自动下载、Commons 自动许可解析、VLM 精排、定时公开。

### P1 — 视频为主 + 合规（2–3 周）

- 加：官方白名单 30 域 + CC-YT `videoLicense=creativeCommon` 检索 + Commons 许可过滤 + `relevance_score` 门槛 + 短引用人工闸。
- 验收：连续 5 集主轨视频占比 ≥60%，第三方引用 0 claim（7 天观察），政治类触发双源闸 ≥1 次可审计。

### P2 — 日常化（2 周）

- 加：cron 每日 2 集、失败重试队列、播放列表映射（财经/政治/科技三列表）、`publishAt` 定时公开策略、重跑幂等（同 `topic+date` 不重复上传）。
- 验收：连续 7 天按时产出（允许 1 天停更但有告警记录），`publish_require_review=1` 下人工一键可放行。

### P3 — 质量与增长（按需）

- 加：VLM 抽帧精排、英文版（Aria 配音 + 英文描述）、封面 A/B、数据卡模板库。
- 验收：完播/订阅相对 P2 提升或明确写“无提升、回滚”。

---

## 10. API Key 清单（只写名字，不读不打印任何密钥值）

> 本节只列环境变量/凭证名，部署时由用户在系统钥匙串或 `.env` 填值，任何脚本不得 `cat/print` 其值。

- 新闻：`GNEWS_API_KEY`（主）、`NEWS_API_KEY`（备，NewsAPI.org）。
- 素材：`PEXELS_API_KEY`、`PIXABAY_API_KEY`。
- 大模型：`OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL`；`DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL`；`VERCEL_GATEWAY_API_KEY` / `VERCEL_GATEWAY_URL`。
- 配音：`TTS_VOICE`、`TTS_RATE`；本地高质：`VLLM_TTS_URL`、`VLLM_TTS_HQ_URL`（二选一即可，默认云健无需填）。
- YouTube：`YOUTUBE_CLIENT_ID`、`YOUTUBE_CLIENT_SECRET`（OAuth），`PublisherAccount.credentials`（refresh_token JSON，存 DB 不存文件），Data API 配额另需 `YouTube Data API v3` 启用；上传走代理 `HTTPS_PROXY=http://127.0.0.1:7890`（环境变量，非 key）。
- Karios 只读（备选直读时）：`KARIOS_DATABASE_URL`（只读用户）或复用 `DATABASE_URL` 的只读解析（参考 runbook §1.2，绝不打印）。
- 队列/服务：`REDIS_URL`（可选）、`API_TOKEN`（可选）。

---

## 11. 风险与待用户决定的问题

### 风险

1. Content ID / reused content：新闻台成片哪怕 3 秒也可能被 claim；对策只有“不用 + 官方/CC + 强评论”，无技术绕过。
2. GNews 免费额度（约 100 req/天、每 req ≤10 篇、有延迟）与 `news_items` 72 小时滚动：超量或跨天回看会断粮；对策是快照 + 缓存（`news_cache_ttl_s=900`）+ 超量即停更。
3. 事实风险：LLM 易编数字；对策是 S3 事实闸 + 数字原样校验 + “依据不足”兜底。
4. 政治风险：中立失衡、人物认错、单源抢发；对策是双源交叉 + 0 引用 + 宁可停更。
5. Mac OOM：渲染/Whisper/转码撞车；对策是单重任务 + 上限 2 + 合成关闭 + 错峰。
6. 版权“免费≠免责”：Pexels/Pixabay 的商标/可识别人物商用仍需自担；Commons 的 BY-SA 需同许可；CC-YT 片内插曲仍可被 claim。描述区署名是必要非充分条件。

### 待用户决定（默认建议已给，不阻断 P0）

1. 每天几集、几点公开？建议：P0 每天 1 集财经（中午 unlisted，晚 21:00 定时公开）；P2 起每天 2 集。
2. 三个播放列表 ID 现在建还是复用现有？建议：新建 `财经·躺平的老黄 / 政治·躺平的老黄 / 科技·躺平的老黄` 三个 unlisted 列表，P0 先只用财经。
3. 政治类做不做？建议：P0 不做，P1 经 5 集财经 0 claim 后再开，且首月全人工审。
4. 短引用开关默认开还是关？建议：默认关，需逐集人工开。
5. 英文版做不做？建议：P3 再做，P0–P2 只中文。
6. Karios 直读 DB 还是只走 HTTP？建议：P0 只走 HTTP，快照落盘；直读只读用户等 P1 再配。
7. 失败是否自动重传？建议：下载/转码可自动重试 1 次，上传失败只告警不自动公开。

---

## 12. 文件与路径索引（video-factory 侧真实路径）

- 本方案：`~/Projects/video-factory/docs/daily-news-video-design.md`
- 新闻链：`apps/worker/src/services/news_service.py`、`apps/worker/src/sources/news_api.py`、`apps/worker/src/config.py`
- 素材：`apps/worker/src/services/material/material_fetcher.py`、`apps/worker/src/services/material/pexels_service.py`、`apps/worker/src/services/material/pixabay_service.py`
- 版式配音：`apps/worker/src/services/compose_service.py`、`apps/worker/src/services/indicator/*`、`apps/worker/src/core/tts/*`、`apps/worker/src/core/subtitle_gen.py`、`apps/worker/src/services/presenter.py`
- 调度上传：`apps/worker/src/scheduler.py`、`apps/worker/src/publishers/youtube.py`、`docs/indicator-episode-runbook.md`
- Karios（只读）：`apps/ai-service/src/routes/news.ts|mainline.ts|report.ts`、`apps/ai-service/src/investmentDailyReportNormalize.ts`、`services/data-sync-service/src/data_sync_service/service/news.py|news_enrich.py|morning_brief.py|mainline.py`、`services/data-sync-service/src/data_sync_service/db/news.py|morning_brief.py`、`apps/desktop-ui/src/lib/queries/news.ts`

---

## 13. 假设清单（无人值守已按此执行）

1. Karios 未改、未提交改动未碰、未做 git 操作；video-factory 未改代码、未提交。
2. 未读取任何 `.env` 真值；Key 清单只写名字。
3. 默认语言中文、横屏 1080p 30fps、封面与问候用笔名。
4. 代理只在上传时开 `127.0.0.1:7890`；上传默认 `unlisted`，绝不擅自公开。
5. 若官方/CC 实在无强相关视频，允许 P0 用 Pexels 主题空镜 + 数据卡兜底，但必须在 `verify_report` 写明假设。
