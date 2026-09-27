# 「什么指标不赚钱」单集生产手册（indicator-episode-runbook）

> 用法：给未来 OpenCode 一句话即可开工，例如：
> `按手册做第 8 集，主题是 RSI 超卖抄底`
> 本手册是唯一真值。质量标准不低于第 4–7 集。
> 参考成片与材料：`apps/worker/data/output/indicator_series/ep4_pin_bar_hammer/`、
> `ep5_bull_ma10_pullback/`、`ep6_bollinger_lower/`、`ep7_limitup_next_open/` 下的
> `ep<N>_script_approved.md`、`verify_report.txt`、成片 `output.mp4`。
> 第 3 集（`ep3_holiday/`）是国庆特辑（分类讨论），结构特殊，只作补充参考。

## 0. 全局硬规定（先读这节）

### 0.1 模型

全程使用：

```bash
opencode run -m opencode-go/muse-spark-1.3-contributor --variant xhigh "…"
```

依据：`~/Projects/video-factory/.opencode-runs/run_ep8_10.sh` 就是这样链式跑 ep8–10 的。
如果该模型不可用：**停下来并报告，不要用别的模型凑合**。

### 0.2 无人值守

不要提问。遇到选择自己合理决定，并在最终报告里写明假设。

### 0.3 代码与提交

- 不要改 Video Factory 的代码（本手册的任务只是“按手册生产一集”）。
- karios-research 只允许动自己的新路径（见 §1.7），分支固定为
  `research/losing-indicators`，**只 commit、不 push**。
- Video Factory 侧的产物（`data/output/indicator_series/ep<N>_*`）**不 commit、不 push**。
- 永远不要碰 `~/Projects/karios-desktop` 工作树。
- YouTube：永远 UNLISTED，永远不公开任何视频，永远不改播放列表隐私。

### 0.4 路径总览（真实路径，不要猜）

```text
video-factory 本体：       ~/Projects/video-factory/
  文档：                   ~/Projects/video-factory/docs/indicator-episodes.md（manifest/预设/fullframe 真值）
  本手册：                 ~/Projects/video-factory/docs/indicator-episode-runbook.md
  worker：                 ~/Projects/video-factory/apps/worker/
  单集输出：               ~/Projects/video-factory/apps/worker/data/output/indicator_series/ep<N>_<id>/
  发布脚本：               ~/Projects/video-factory/.opencode-runs/yt_publish.py
                           ~/Projects/video-factory/.opencode-runs/yt_verify.py

研究侧：                   ~/Projects/karios-research/research/indicator_series/
  信号模块：               ~/Projects/karios-research/research/indicator_series/kseries/specs/<id>.py
  模板：                   ~/Projects/karios-research/research/indicator_series/kseries/specs/_template.py
  配置：                   ~/Projects/karios-research/research/indicator_series/kseries/config.py
  图框：                   ~/Projects/karios-research/research/indicator_series/kseries/frame_size.py
  入口：                   ~/Projects/karios-research/research/indicator_series/run.py（3 行 wrapper，调 kseries.run）
  README：                 ~/Projects/karios-research/research/indicator_series/README.md

产物侧：                   ~/Projects/karios-series-output/<id>/
  例：                     ~/Projects/karios-series-output/limitup_next_open/
                           ~/Projects/karios-series-output/holiday_effect/（唯一有 EXPERIMENT.md 的特例）
```

### 0.5 集号 / id / 标题

- 输入只给“第 N 集 + 主题”。自己定一个稳定的 snake_case `id`（如 `rsi_oversold`）。
- 输出目录：`apps/worker/data/output/indicator_series/ep<N>_<id>/`。
- 审定稿：`ep<N>_script_approved.md`（放在本集目录里，格式照抄 ep7，见 §3.7）。
- 标题格式（和前几集一致）：`……？｜什么指标不赚钱 第N集`
  例：`涨停第二天追进去，真的能赚钱吗？｜什么指标不赚钱 第7集`。
- 开工先读前几集的标题与例子股票，避免重复（已用：MACD、KDJ、锤头线/中国中免、
  多头回踩10日线/长江电力、布林下轨/京东方A、涨停次日/中信证券；禁用：茅台）。

### 0.6 内存（硬规定，每次重任务前都执行）

这台 Mac 很容易爆内存。**一次只跑一个重任务**（回测 / 渲染 / Whisper 三选一）。

```bash
memory_pressure
pgrep -fl "python|ffmpeg|whisper"
```

- 如果有别的重任务在跑，等它结束再开始。
- 并行 worker 上限 2（研究引擎与渲染都不许开更多）。
- Whisper 只用 small（`faster-whisper int8`）；只有个别被 small 听错数字的片段，
  才对那几个片段用 medium 重听（ep7 就是 seg3/seg7/seg9 这样做的）。
- 只杀自己启动的进程；**绝不杀**其他 opencode 进程、Docker、`:8000` worker、
  用户应用。
- 代理（只用于 YouTube 那一步）：`127.0.0.1:7890`，见 §7.1。平时不需要开。

---

## 1. 研究（karios-research）

目标：证明本集主题“明确不赚钱”，否则**不做视频**。

### 1.1 先确认分支与干净状态（只读）

```bash
cd /Users/huangyuan/Projects/karios-research
git branch --show-current
# 必须是 research/losing-indicators
git log --oneline -5
git status --short -- research/indicator_series
```

预期基线（写手册时）：`ec329681`（ep5–7 图表），`5eee902` 是 video-factory 侧。
如果分支不对：停下并报告，不要自己切分支（`opencode.json` 禁止 checkout/switch/stash/reset/merge/push）。

### 1.2 数据库：只读

- 每个连接必须 `psycopg.connect(url, options="-c default_transaction_read_only=on")`，
  只跑 `SELECT` / `COPY TO STDOUT`（见 `kseries/db.py`、`BRIEF.md`、`README.md §(a)`）。
- URL 来源：环境变量 `KARIOS_DATABASE_URL`，否则解析
  `/Users/huangyuan/Projects/karios-desktop/.env` 里 `DATABASE_URL=` 那一行。
- **永远不要打印或记录 URL / 密码。只读 `.env`，不改它。**

### 1.3 加信号模块（唯一允许的新代码）

1. 看已注册列表：

```bash
cd /Users/huangyuan/Projects/karios-research/research/indicator_series
.venv/bin/python -m kseries.run --list
```

2. 复制模板（`_template.py` 以下划线开头所以不会被 registry 发现；
   复制成公开名后自动被发现）：

```bash
cp kseries/specs/_template.py kseries/specs/<id>.py
```

3. 按模板填 `SPEC = IndicatorSpec(...)`：
   - `indicator_id`（=`<id>`）、`name_zh`；
   - 纯的、因果的 `compute(panel)`（复用 `kseries/indicators.py` 里的 sma/ema/macd/kdj/cross_up/down），
     决策在 T 收盘用到的任何数都必须能由 `≤T` 的 K 线算出（no lookahead）；
   - 至少一个 `Variant(variant_id, rule_zh, entry, exit_, max_hold, entry_label_zh, exit_label_zh)`，
     第一个 variant 即主口径（PRIMARY）；
   - `PanelSpec(lines/bars/hlines/ylabel)` 描述 01/02 图的下半部分；
   - 1–3 个 `Myth`，metric 只能选 `kseries/signals.py::MYTH_METRICS` 里的
     `median_and_loss_share | win_rate | vs_benchmark | vs_random | cost | win_small_lose_big`；
   - `example_stock` 固定一只、示例窗口固定（默认 `2024-07-01` 至 `2024-12-31`，
     见 `kseries/config.py:110-111`），**不要自动挑选**最漂亮的例子；
   - `retail_claim_zh` 一句话散户用法；`params` 纯 dict（会原样进 `run_config.json`）。
4. 例子股票：**不用茅台**；也不要用中国中免、长江电力、京东方A、中信证券，
   不要和第 1–7 集重复。

### 1.4 跑回测（一个命令出回测 + 图表）

```bash
cd /Users/huangyuan/Projects/karios-research/research/indicator_series
.venv/bin/python -m kseries.run --indicator <id>
```

- 图表默认就开（`--no-charts` 才关）。常用旗标（见 `README.md §Flags`）：
  `--variant V`、`--episode N`（只写进 00 标题卡）、`--no-mc`、`--mc-n 1000`、
  `--mc-portfolio-n 200`、`--no-random-stocks`、`--sanity`、
  `--chart-size 1920x950`、`--charts-only`（只重画图，不覆写回测口径，写 `charts_run.json`）。
- 只重画 1920x950 图（不动回测数）：

```bash
KSERIES_CHART_SIZE=1920x950 .venv/bin/python -m kseries.run --indicator <id> --charts-only
```

- 冻结口径（`kseries/config.py`，不要改，数字以它为准）：
  `round_trip_cost = 0.0030`（往返 0.30%）、`primary_cost = 0.0030`、
  `cost_levels = (0.0015, 0.0030, 0.0050)`、`num_slots = 10`、
  `mc_seed = 20260925`、`mc_n = 1000`、`mc_portfolio_n = 200`、
  `random_stock_seeds = (20260925, 1, 2)`、信号区间 `2010-01-01` 至 `2026-08-31`、
  组合区间同、基准 `000300.SH / 000905.SH`。
- 引擎语义（和 verify_report / summary 对得上才算对）：
  信号 T 日收盘产生、T+1 开盘成交；一字涨停买不进、一字跌停卖不出、顺延；
  挂单入口最多滚 5 根 bar；每笔 `net = exit_px/entry_px - 1 - cost`；
  组合是 10 份等额、按 20 日均额排序、空闲 0 收益、日内按 qfq 收盘 mtm；
  蒙特卡洛是“同一入场日 + 同一持有 bar、随机换股票、同样成本”，事件层 1000 次、
  组合层 200 次，种子 `20260925`。

### 1.5 必须拿到的数字（缺一不可，否则不算“明确不赚钱”）

到 `~/Projects/karios-series-output/<id>/` 检查：

```bash
ls /Users/huangyuan/Projects/karios-series-output/<id>/
cat /Users/huangyuan/Projects/karios-series-output/<id>/summary_zh.md
cat /Users/huangyuan/Projects/karios-series-output/<id>/<primary_variant>/summary.json | head -n 100
cat /Users/huangyuan/Projects/karios-series-output/<id>/run_config.json | head -n 60
ls /Users/huangyuan/Projects/karios-series-output/<id>/charts/
```

- 事件层（往返 0.30%）：笔数 n、**每笔净均值 mean_net、净中位数 median_net、胜率 win_rate、
  盈亏比**、平均持有、毛均值、费用拖累（参考 `kseries/report.py::event_metrics`）。
- 组合层（10 份）：**组合年化 annualized、最大回撤 MDD**，同期沪深300/中证500年化。
- 随机对照：事件层 1000 次的均值/分位（策略排在什么分位）、组合层 200 次；
  另有 §15A 随机 12 只（种子 20260925/1/2）跑赢“一直拿着”的只数。
- 判定（`kseries/report.py::make_verdict`，Protocol-A：中一条即“不赚钱”）：
  (a) 事件净均值 ≤ 0；(b) 组合年化 < 沪深300 或 < 中证500；(c) ≥3/4 时代毛超额为负。
- 本系列做视频的门比引擎更严（按 ep8 规则与 ep4–7 verify 惯例）：
  **只有“明确不赚钱”（扣费后每笔均值为负、组合年化为负、且不优于随机）才做视频。**
  如果是“赚钱”或“不清楚”：**停下并报告，不要做视频**。

### 1.6 写实验记录

- 在 `~/Projects/karios-series-output/<id>/EXPERIMENT.md` 写一份实验记录，
  体例照抄 `~/Projects/karios-series-output/holiday_effect/EXPERIMENT.md`
  （问题 → 数据与清洗 → 信号与买卖时点 → 成本 → 随机对照 → 结果表 → 复现命令 → 局限）。
- 注意：目前只有 `holiday_effect/` 有 `EXPERIMENT.md`；其他 indicator 的机器产物是
  `summary_zh.md` + `<variant>/summary.json` + `run_config.json`。本节要求的
  `EXPERIMENT.md` 是**人写的**（把上面那些机器产物的口径、命令、commit、种子、
  局限写成一篇可复现记录），不是机器生成的。
- 记录里必须有：精确到（T 收盘信号 → T+1 开盘成交、涨跌停顺延、持有期、0.30%）、
  股票池（主板+创业+科创、含已退市、剔 ST/北交所/成交清淡、上市满 250 天、
  前 20 日均额 ≥ 70000 千元）、复现命令（含 commit）、种子、局限
  （如残余幸存者偏差：DB 快照缺失部分历史退市/合并代码）。

### 1.7 提交（只 commit 自己的新路径，不 push）

```bash
cd /Users/huangyuan/Projects/karios-research
git status --short -- research/indicator_series
git add research/indicator_series/kseries/specs/<id>.py
# 如有模板外的新增口径文件，一并 add，但只限 research/indicator_series/ 内
git commit -m "LI-xx: <id> signal + backtest (<n> trades, verdict 不赚钱)"
# 不要 push。不要 checkout/switch/stash/reset/merge。
```

- `BRIEF.md` 原话：只写 `research/indicator_series/` 下的代码；
  不要跑改分支/stash/reset/push/merge 的 git 命令（manager 负责合）。
- `opencode.json` 同样 deny `git push/checkout/switch/stash/reset/merge/rebase/commit/worktree`；
  本手册的例外只有上面这一条“自己新路径的 commit”，其余一律不碰。

---

## 2. 图表（matplotlib，1920x950，白底）

### 2.1 尺寸是死的

- 研究图表 **exactly 1920x950**（不是 1920x1080）。Video Factory 的 fullframe
  把 1920x950 图填满上半 `0–949` 行，下半 `950–1079` 是 130px 字幕带（见 §4）。
- 实现（三选一，按优先级）：
  1. `KSERIES_CHART_SIZE=1920x950` 环境变量（`kseries/charts.py::resolve_chart_size`）；
  2. `--chart-size 1920x950`；
  3. 代码里 `with chart_frame():`（`kseries/frame_size.py`）：

```python
from kseries.frame_size import chart_frame
with chart_frame():  # 默认 (1920, 950)
    ...build and save charts...
```

原理（`frame_size.py:38-42`）：高保持 10.8in、DPI 只按高度缩放，
`width_in = 10.8*1920/950`，`dpi = 950/10.8`，存出来恰好 1920x950；
退出时恢复 `charts.WIDTH/HEIGHT/DPI`。

- 检查（抽查几张）：

```bash
python3 -c "from PIL import Image; im=Image.open('/Users/huangyuan/Projects/karios-series-output/<id>/charts/03_equity_vs_benchmark.png'); print(im.size)"
# 必须是 (1920, 950)
```

### 2.2 白底、中文、summary 卡

- 白底（`#ffffff` fallback，见 `apps/worker/src/config.py:181` 与
  `compose_service.py::_canvas_color/_fullframe_canvas`；研究侧图表本身就用白底，
  不要出黑底图）。
- 中文字体要清晰可读（worker 渲染用 `/System/Library/Fonts/STHeiti Medium.ttc`；
  研究侧 matplotlib 也必须选一个有中文的字体并全套图统一）。
- summary 卡（`06_summary_card.png`）：实测布局、shrink-to-fit、**不许重叠**
  （ep5 曾因「不赚钱」压住「-99.2%」而重渲染；karios `ec329681` 起是量好再画）。
  每笔类指标保留 2 位小数；四舍五入到 0 的百分数印无符号 `0.00%`（`d8afc7df`）。
- 每张图留清晰边距（`bff05e74`：chart 13 表头、chart 07 y 轴不贴边；
  全套图有 1920x950/1920x1080 边距测试）。
- 信号标注：chart 01 每个信号都要标（含交错防撞）、`买不进 ×` 装框标注 + 图例、
  extras 表的收益列带符号（`9c8cd004`）。

### 2.3 manifest.json

机器生成（`kseries/charts.py::make_chart_set`），14 张（gallery 变体 16 张）。
每条恰好 7 个键（顺序固定）：`order/file/path/section/title/key_point/suggested_seconds`。
例（`limitup_next_open/charts/manifest.json`）：

```json
{"order": 4, "file": "03_equity_vs_benchmark.png", "section": "history",
 "title": "净值 vs 基准", "key_point": "组合年化 -36.2%，最大回撤 -99.98%",
 "suggested_seconds": 24}
```

- `section` 只能是 `intro/explain/retail_usage/history/why_not/summary`
  （未知值会被保留但打日志）。
- `key_point` 里的**每个数字都必须原样出现在配音里**（worker 有 number check，
  见 §3.6）。`suggested_seconds` 一般 10–30s，全集约 240–300s。
- 顺序即叙事顺序（loader 不重排）：`00 intro → 01 explain → 02 retail_usage →
  history(03,09,04,11,07,08,10) → why_not(05,12,13) → 06 summary`。
  第一张 `section==intro` 且文件名含 `title` 的是封面（3s）。

---

## 3. 文案（script-only → 审定 → 渲染）

### 3.1 流程（script-only → review → approved-script）

```bash
cd /Users/huangyuan/Projects/video-factory/apps/worker
# 1) 只写稿（不渲染）：产出 script.json / script.md / script_review.md，状态 script_ready
uv run python scripts/indicator_episode.py \
  --manifest /Users/huangyuan/Projects/karios-series-output/<id>/charts/manifest.json \
  --title "……？｜什么指标不赚钱 第N集" \
  --context /Users/huangyuan/Projects/karios-series-output/<id>/summary_zh.md \
  --out-dir data/output/indicator_series/ep<N>_<id>_script \
  --script-only
```

- 读 `script_review.md`；只改 `script.json` 里 `segments[i].text`，
  不动段数/顺序，不动 `images/fit/motion/section/chart/key_point`；
  `key_point` 里的数字一个不许丢。
- 定稿后把可读稿存为本集目录的 `ep<N>_script_approved.md`（格式见 §3.7），
  并用它覆盖 `script.json`（行数必须与 segments 数一致）：

```bash
uv run python ../../.opencode-runs/ep/mk_approved.py \
  data/output/indicator_series/ep<N>_<id>_script <lines.txt> "……？｜什么指标不赚钱 第N集"
```

`mk_approved.py` 逻辑：读 `script.generated.json`（没有就先拷 `script.json`），
按行替换每段 `text` 并写回 `script.json`。
另有 `mk_md.py`（由 approved 生成 md）、`audit.py/audit2.py`（数字核对，见 §3.6）。

### 3.2 开头与身份

- 第一段第一句必须是：`大家好，我是躺平的老黄。`（`src/services/presenter.py::greeting_for`，
  `PRESENTER_NAME=躺平的老黄`，indicator 预设 `presenter_intro=True`；
  LLM 写完后会被确定性强制纠正，approved 稿渲染时原样用，缺问候只告警）。
- **永远不出现真名**，只用笔名 `躺平的老黄`；封面会打上该名字
  （`cover_presenter.png`，由标题卡复制加字而来，原图不动）。
- 配音：`zh-CN-YunjianNeural`（云健），不要换。

### 3.3 例子与结构（和前几集不一样）

- **永远不用茅台当例子**（verify 有 banned 词检查，ep7 为 `茅台/封板质量`）。
- 也避开已用例子（中国中免、长江电力、京东方A、中信证券）与已用结构。
  ep4 是“先做 4 选 1 小测再揭晓”，ep7 是“追板买不进 vs 买进的两行对比”，
  不要照抄开场方式；每集换一种讲法。
- 每节之间写**承接句**（承接上节 + 预告下节），不要硬切。
  反例：讲完“4 种做法”直接跳“情况 1”而没有一句“先看情况 1”。

### 3.4 结尾（自然口语 + 免责 + 落款）

- 自然口语收束：测了什么、发现了什么、对普通投资者意味着什么；**最多 2–3 个数字**，
  不要把全集数字再背一遍（参考 ep7 结尾：“好板往往不给你上车…没追上反而是运气”）。
- 然后免责：`以上都是历史回测，不构成投资建议。`
- 再落款：`我是躺平的老黄，…点个关注/这个系列还会继续`（措辞可换，身份不可换）。
- 审定稿末尾另起一行：`配音合计 xxx 秒。以上为历史回测，不构成投资建议。`

### 3.5 篇幅与数字

- 成片 **~5 分钟**（ep4 330.5s、ep5 278.9s、ep6 300.0s、ep7 285.3s；ep3 特辑 346.7s）。
  配音合计约 270–320s，加上 3s 封面即成片时长。
- **每个数字都必须和回测产物对得上**（`summary.json` 全变体 + extras +
  `charts/manifest.json` key_point）。小数位数、单位（%/倍/笔/年）、符号（±）
  都要一致；转述（如“10万多笔”对 103,166）只在已核对的前提下用，
  关键结论数字必须精确。

### 3.6 配音前双检（先程序，后模型；只改措辞，不改数字）

1. 程序检查（阈值与 ep4–7 一致）：
   - `pretts.py`（lint/auto-fix）：

```bash
cd /Users/huangyuan/Projects/video-factory/apps/worker
uv run python ../../.opencode-runs/ep/pretts.py <lines.txt>
# 期望：flagged 0，或只有无害项；auto-fix 的改动要人看一眼
```

   - `audit2.py`（每个数字 vs 全变体 summary + manifest key_point）：

```bash
uv run python ../../.opencode-runs/ep/audit2.py \
  /Users/huangyuan/Projects/karios-series-output/<id> <lines.txt> [extra_allowed_comma_list]
# 期望：numbers N, unverified []；若有未命中，必须逐条人肉核对到 trades.csv/期表并写进 verify_report
# ep7 实例：2024（示例窗）、10.8%（-10.78%）、2013/2016/2022（期表）、77.7%（-77.67%）
```

   - 自查清单：杂散标点、数字被拆行/拆句、长句无标点、`+/-` 与正负表述一致
     （“亏 1.12%” vs “-1.12%” vs “负 1.12%”三者只许一种口径并和字幕统计对上）、
     禁词（茅台等）。
2. 模型通读：只修别扭措辞，**不许改任何数字**；改完重跑一遍程序检查。
3. 留 review 记录（审了什么、改了什么、数字核对结果），与 `script_review.md` 一起存档；
   审定稿头部写清数据区间、口径、数字来源（`summary.json / charts/manifest.json`）、
   成片时长（参考 ep7 头部 6 行）。

### 3.7 审定稿格式（照抄 ep7）

`ep<N>_script_approved.md` 结构：标题 `# ……？` + 系列行 + 6 行元信息
（状态/数据/数字来源/成片时长）+ 按 `## 小节` 分段，每段
`**NN** · 图表 \`xx.png\` · 配音 xx.xs` + 正文。全文见
`apps/worker/data/output/indicator_series/ep7_limitup_next_open/ep7_script_approved.md`。

---

## 4. 配音 / 渲染（Video Factory indicator 预设）

### 4.1 预设（不要手改，用预设）

`apps/worker/src/config.py::DEFAULT_TYPE_PRESETS["indicator"]`：

| 项 | 值 |
|---|---|
| `voice` | `zh-CN-YunjianNeural` |
| `tts_rate` | `+2%`（比老 `-8%` 快约 11%） |
| `sentence_gap_seconds` | `0.75`（目标值：量出现有静音只补/修到 0.75，不是额外加 0.75；`sentence_pause_seconds=0.0`） |
| `segment_pause_seconds` | `0.5` |
| `chart_layout` | `fullframe` |
| `chart_canvas_color` | `#ffffff` |
| `chart_fullframe_band_px` | `130`（1080p 下；按 `H/1080` 缩放；图区即 `0–949` 行） |
| `chart_subtitle_dark_color` | `#1f2329`（无描边，带内垂直居中，永不压图） |
| 封面 | 标题卡整帧（`band=0`），hold `3.0s`（`book_cover_hold_seconds`） |
| 字幕字体 | `/System/Library/Fonts/STHeiti Medium.ttc` |
| 背景音乐 | `data/assets/music/Ambiment - The Ambient - Kevin MacLeod.mp3`（ep3 task.log 实测） |
| `background_music_volume` | indicator `0.1`，general/news/book 均为 `0.2`（2026-09-26 起 indicator 降为原来一半，旁白占主导；见 commit `95c6f5f`） |

fullframe 语义（`docs/indicator-episodes.md §Full-frame` + `compose_service.py`）：
白画布、图整幅 contain（不裁不拉）、1920x950 图边对边填满图区、
16:9 图则取自身边框中值色补边、**任何时候不出黑**（含转场/间隙/字幕带）、
字幕深色无描边单行居中。

### 4.2 渲染（in-process CLI，不要起 :8000）

```bash
cd /Users/huangyuan/Projects/video-factory/apps/worker
# 审定稿渲染（跳过 AI 生成与 proofread LLM；lint 只报不改；图按绑定原样用）
uv run python scripts/indicator_episode.py \
  --approved-script data/output/indicator_series/ep<N>_<id>/script.json \
  --out-dir data/output/indicator_series/ep<N>_<id>
# 一遍出（只在不需要人审时用；本系列必须先审后渲，所以一般不用）
uv run python scripts/indicator_episode.py \
  --manifest /Users/huangyuan/Projects/karios-series-output/<id>/charts/manifest.json
```

- 成功打印 `TASK_DIR`、状态与 `script.json/script.md/script_review.md` 与 `output.mp4` 路径；
  退出码 0 成功 / script_ready，1 失败。`--help` 看全旗标。
- `task.log` 应能看到：`使用已审核脚本`、TTS `+2%`、句间 `0.75s`、字幕条数、
  字体、背景音乐、封面 `3.0s`、总音频时长。

---

## 5. 校验（写 verify_report.txt，不过不许上传）

在本集目录写 `verify_report.txt`，章节照抄 ep7（85 行那份）：
头部（标题/commit/音频/ verdict）→ pre-TTS → number cross-check →
VF subtitle_sync → output(md5/时长/分辨率) → segment offsets →
FOUR-EDGE → chart/subtitle separation → subtitle sync →
text/signs/longest → sentence gaps → frames extracted →
Whisper → frames viewed。每项给 PASS/FAIL。

### 5.1 边框检查（2fps 逐帧，四边）

标准（ep4–7 实测）：`fps=2` 抽帧（t=0..时长），四条
`left x0-20 / right x1899-1919 / bottom y1059-1079 / top y0-20`，
PASS = 每条 strip mean Y > 200 且无像素 Y < 50。
ep4 661 帧、ep5 558 帧、ep6 600 帧、ep7 571 帧，全部 0 失败。

```bash
cd /Users/huangyuan/Projects/video-factory/apps/worker/data/output/indicator_series/ep<N>_<id>
ffmpeg -i output.mp4 -vf fps=2 frames/frm%04d.png -y
python3 - <<'PY'
from PIL import Image
import numpy as np, glob
fails = 0; n = 0
for f in sorted(glob.glob("frames/frm*.png")):
    n += 1
    a = np.asarray(Image.open(f).convert("YCbCr"))[:, :, 0].astype(int)
    strips = {"left": a[:, 0:20], "right": a[:, 1899:1919],
              "bottom": a[1059:1079, :], "top": a[0:20, :]}
    for k, s in strips.items():
        if not (s.mean() > 200 and (s < 50).sum() == 0):
            print("FAIL", f, k, s.mean(), (s < 50).sum()); fails += 1
print(f"frames {n} failing {fails} {'PASS' if fails==0 else 'FAIL'}")
PY
```

### 5.2 图 / 字幕带分离

标准：图区 `0–949` 行、带区 `950–1079`；封面后帧的带内墨迹应在 `y≈996–1033`
单行；全帧最低图墨 `y≤949`（ep4–7 实测 917）；`950–959` 溢出 0 帧；
非单行 0 帧。把带墨当“深色像素”（Y < 100）统计即可，阈值与 ep 报告一致即 PASS。

### 5.3 字幕同步（0.15s）

```bash
cd /Users/huangyuan/Projects/video-factory/apps/worker
uv run python scripts/subtitle_sync_report.py \
  data/output/indicator_series/ep<N>_<id> --cover 3.0
```

- 要求：`within 0.15s` 100%（ep4 85/85、ep5 69/69；ep6 78/79、ep7 73/74 各 1 帧例外
  是因为句中短逗号停顿低于静音阈值、包络 dipped 在 cue 后 0.03–0.05s、
  VF 词界 max 0.08s——这种情况要把包络位置写进报告并判 OK，否则必须修到 100%）。
- 另做一次 cue-start vs speech-onset（segment mp3 runs + 互相关 offsets），
  `pauses ≥0.5s inside a cue` 必须 `[]`；`subtitle_sync_report.py` 的
  `mid-phrase pause ≥0.7s` 必须 0。

### 5.4 文本 / 符号 / 最长 cue / 禁词

- `cues` 数与 `subtitles.ass` 一致；字幕文本 == approved 文本（忽略标点）必须 True。
- `+`/`-` 计数：`ass` 里 `+` 数、`-` 数与脚本一致（ep7：`+3/-10`）。
- 最长 cue 上限 26 字（ep4–7 实测最长都是 26 字），超了就拆句重渲。
- 禁词：`茅台` 等（ep7 报 `[]`）。有命中即 FAIL。

### 5.5 句间隙

每段 mp3 内 `≥0.55s` 的静音即句间隙：`n` 个 gaps 均值 ≈0.74（ep 实测 0.71–0.80），
`lead≈0.18s tail≈0.85–0.91s`。明显偏离（如均值 <0.65 或 >0.85）说明 rate/gap
预设被改了，查 `task.log`。

### 5.6 Whisper 数字核对

```bash
cd /Users/huangyuan/Projects/video-factory/apps/worker/data/output/indicator_series/ep<N>_<id>
python3 -m faster_whisper segment_0.mp3 --model small --dtype int8
# 对 segment_*.mp3 逐个跑；只对 small 听错数字的个别片段用 --model medium 重跑
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 segment_N.mp3
```

- 把每段听写贴进 `verify_report.txt`，再写 `numbers heard: all correct (...)`，
  列出所有阿拉伯数字；同音字（中性证券=中信证券、涨厅=涨停、每比=每笔）只备注，
  符号/数字错即 FAIL。
- 已知坑：Whisper 会在沪深300/中证500 的 `+1.7%/+3.6%` 前写 `-`
  （TTS 输入本就没有 `+`，是转写格式问题，备注即可）；`small` 在 ep7 把
  `1.12%→1.2%`、`-0.12%→付0.2%`、`2022年→二年`听错，`medium` 纠正——照此处理。

### 5.7 关键帧（存本集目录，给人眼检）

```bash
ffmpeg -ss 1.5 -i output.mp4 -vframes 1 cover.png -y
ffmpeg -ss <seg_mid> -i output.mp4 -vframes 1 seg01.png -y
# 每个 chart 段中点 1 张 + 最长 cue 处 1 张 + 片尾 1 张
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 output.mp4
md5 output.mp4
```

- ep7 的 `frames extracted` 写法照抄：
  `[('cover',1.5),('seg01',14.05),…('longcue',36.33),('end',284.34)]`。
- 人眼看完写 `frames viewed:` 一行：封面有躺平的老黄、标题卡、每图（红箭头/×标注/
  summary 2 位小数无重叠）、最长 cue、片尾——白底整帧、图满宽、深色单行字幕、
  无重叠、字 legible，否则 FAIL。
- 另记：`output.mp4` md5、时长、`1920x1080 30/1`。
- QA 门禁（ep12/ep14 回归，机器必过，不过不许上传）：
  - 关键帧卡片无溢出：每张 `13_myth_vs_data.png` 源图（及 `seg13.png` 对应帧）
    文字在盒内四边留白 ≥24px、不压边框。跑：
    ```bash
    cd /Users/huangyuan/Projects/video-factory/apps/worker
    uv run python scripts/indicator_qa.py data/output/indicator_series/ep<N>_<id>
    # 期望：QA PASS；FAIL 即溢出（render-time assertion 同样会在合成前抛错）。
    ```
    原理：研究侧 `kseries/charts.py::_chart_13` 按像素量字、按像素宽换行、
    缩到可读最小、盒高不够就长高、仍超就缩短事实（至多两短行），画完断言盒内；
    本侧 `src/services/indicator/card_qa.py` 像素复检，失败即 FAIL。
  - 口播无重复：`script.json` 全片同一6字以上短语只许一次，相邻两段4字以上
    过渡（`换个角度`/`最后留一句话`等）不许首尾重复；`subtitles.ass`/Whisper
    转写同样检查，重复即挡上传（`indicator_qa.py` 同查，`generate_indicator_script`
    生成时单点剥离过渡 + 全片 n-gram 断言，approved 脚本在检时同样断言）。

---

## 6. 上传（YouTube，UNLISTED 进播放列表尾）

### 6.1 代理

```bash
export HTTPS_PROXY=http://127.0.0.1:7890
export HTTP_PROXY=http://127.0.0.1:7890
export NO_PROXY=127.0.0.1,localhost
curl -x http://127.0.0.1:7890 -I https://www.googleapis.com/
```

原理：`apps/worker/src/publishers/youtube.py::_build_http_with_proxy()`
读 `HTTPS_PROXY/https_proxy` 优先，经 `httplib2.Http(proxy_info=…)` 建
`youtube v3` 客户端；上传/建播放列表/校验都走它。日志应有
`YouTube API using proxy: http://127.0.0.1:7890`。

### 6.2 meta.json（照抄 ep1 格式）

参考 `~/Projects/video-factory/.opencode-runs/ep/yt/ep1.json`：

```json
{
  "title": "……？｜什么指标不赚钱 第N集",
  "description": "…【数据与方法】…【关键数字】…\n\n历史回测，不构成投资建议。\n\n主讲：躺平的老黄\n系列「什么指标不赚钱」：用真实数据检验散户常用技术指标。",
  "tags": ["…", "A股", "股票", "回测", "量化回测", "散户", "什么指标不赚钱", "躺平的老黄"]
}
```

- description 必须有：区间（2010-01-01 至 2026-08-31）、T 收盘信号 T+1 开盘成交、
  一字涨跌停顺延、股票池、规则、10 份组合、0.30%、随机对照与基准、
  3–5 个关键数字、结论、免责、主讲。
- 不要在 meta 里写真名、不要写茅台。

### 6.3 上传（playlist 末尾，unlisted）

```bash
cd /Users/huangyuan/Projects/video-factory/apps/worker
uv run python ../../.opencode-runs/yt_publish.py upload \
  /Users/huangyuan/Projects/video-factory/.opencode-runs/ep/yt/ep<N>.json \
  data/output/indicator_series/ep<N>_<id>/output.mp4 \
  PLJ8z9DDMq_Yg
# 期望：UPLOAD {"success": true, "post_url": "https://www.youtube.com/watch?v=…", …}
```

- `yt_publish.py` 把 `privacy="unlisted"`、`folder_id=playlist_id=PLJ8z9DDMq_Yg`、
  `default_language="zh-CN"` 写死；`playlistItems().insert` 不传 `position`，
  YouTube 自动追加到末尾。**不要传 position，不要调 playlists().update。**
- 账号固定 `PUB_ID=e58dcc1f7a1c8c8b`（Yuan YouTube），不要换。

### 6.4 回读（必须是 unlisted + processed + 尾位 + 列表隐私未变）

```bash
uv run python ../../.opencode-runs/yt_verify.py e58dcc1f7a1c8c8b PLJ8z9DDMq_Yg <videoId>
# 期望：
# PLAYLIST … privacy= unlisted items= <old+1>
# ITEM pos <old_max+1> <videoId> <title>
# VIDEO <id> privacy= unlisted upload= processed dur= … title= … lang= zh-CN
```

- 上传前先记一次 `itemCount/max(position)`，上传后再读一次，新视频必须在
  `pos=old_max+1` 且 `itemCount+1`。
- 若 `privacy≠unlisted` 或 `upload≠processed`：不等“以后再看”，直接报告 FAIL
  并写进最终报告的遗留问题；**绝不改成 public，绝不改列表隐私**
  （`yt_make_ep2_public.py/yt_reverify.py` 只是历史一次性脚本，本流程禁用）。

### 6.5 YouTube 授权失效怎么办

- 症状：`yt_publish.py` / `yt_verify.py` 报
  `invalid_grant: Token has been expired or revoked`，但代理正常
 （`curl -x http://127.0.0.1:7890 -I https://www.googleapis.com/` 是 200）。
  这是用户侧 OAuth 凭证问题，不是视频质量问题：不要重渲，不要改播放列表。
- 重授权（一行命令，会自动弹浏览器，选「躺平的老黄」频道并允许）：

```bash
cd /Users/huangyuan/Projects/video-factory/apps/worker
export HTTPS_PROXY=http://127.0.0.1:7890 HTTP_PROXY=http://127.0.0.1:7890 NO_PROXY=127.0.0.1,localhost
uv run python scripts/youtube_reauth.py
# 或：bash scripts/youtube_reauth.sh
```

  脚本用 DB 里存的同一个 client id/secret 和上传要的 scope
 （`youtube` + `youtube.upload`）走 installed-app 流程，旧 token 会带时间戳备份，
  新 token 同时写入 DB（`PublisherAccount.credentials`）和
  `data/secrets/youtube-oauth-token.json`。全程不打印任何 secret/token。
- 验（频道必须是躺平的老黄，列表仍是 unlisted）：

```bash
export HTTPS_PROXY=http://127.0.0.1:7890 HTTP_PROXY=http://127.0.0.1:7890 NO_PROXY=127.0.0.1,localhost
uv run python ../../.opencode-runs/yt_verify.py e58dcc1f7a1c8c8b PLJ8z9DDMq_Yg <videoId>
```

- 补传（和平时一样，UNLISTED 进尾部；ep12 起传完等 ~20s 再回读，`upload=` 从
  `uploaded` 变成 `processed` 才算完）：见 §6.3–6.4。
- 防复发：如果 Google Cloud Console 里 OAuth 同意屏幕还是“测试（Testing）”状态，
  refresh token 约 7 天就过期。让 owner 按报告里的步骤把它切到“正式版（Production）”。
  之后 token 被手动撤销、改密码、换 client secret 仍会失效，届时重跑本节即可。

---

## 7. 最终报告（给 manager 的短报告 + 打开文件夹）

1. 在本集目录写 `ep<N>_final_report.md`（ep8 起的惯例），并把同样内容打印出来。
2. 格式（短）：

```text
标题：……？｜什么指标不赚钱 第N集
链接：https://www.youtube.com/watch?v=…（unlisted）
时长：xxx.x 秒
结论：不赚钱 + 3–5 个关键数字（每笔净均值/中位数/胜率、组合年化/MDD、随机对照分位）
检查：边框 PASS/FAIL、四边分离 PASS/FAIL、字幕同步 x/y (max|d|)、文本一致、Whisper、关键帧、上传回读
关键帧：cover.png / seg*.png / longcue / end 的本集绝对路径
提交：karios-research <commit>（research/indicator_series/kseries/specs/<id>.py 等，branch research/losing-indicators，未 push）
遗留：无 / …（含假设：id 命名、主口径选择、例子股票选择、结构与前几集的差异点）
```

3. 打开文件夹给人看：

```bash
open -R /Users/huangyuan/Projects/video-factory/apps/worker/data/output/indicator_series/ep<N>_<id>
```

---

## 附录 A. 一句话开工检查单

1. `opencode-go/muse-spark-1.3-contributor --variant xhigh` 可用，否则停。
2. `memory_pressure` + `pgrep`，一次一重任务，worker ≤2。
3. karios 分支 `research/losing-indicators`，DB 只读，不碰 desktop。
4. 新信号模块 → 一命令回测 → 数字齐 → verdict 明确不赚钱 → 写 EXPERIMENT.md → commit 不 push。
5. 图 1920x950 白底 + manifest → script-only → 双检 → `ep<N>_script_approved.md`。
6. indicator 预设渲染（云健/+2%/0.75s/fullframe/130px/3s 封面）。
7. `verify_report.txt` 全 PASS（边框/分离/0.15s/文本/Whisper/关键帧）→ 否则修完重渲。
8. 代理 + meta + `yt_publish.py upload … PLJ8z9DDMq_Yg`（unlisted 尾部）→ `yt_verify.py` 回读。
9. `ep<N>_final_report.md` + 打印 + `open -R`。

## 附录 B. 本手册写定时未能完全确定的事（已按现有文件取最可信值）

1. `EXPERIMENT.md`：只有 `holiday_effect/` 有现成文件；其他 indicator 只有机器的
   `summary_zh.md/summary.json/run_config.json`。本手册要求的新 `EXPERIMENT.md`
   是按 `holiday_effect/EXPERIMENT.md` 体例**人写**的可复现记录（§1.6）。
2. 边框/分离/包络偏移/Whisper/关键帧脚本：除 `scripts/subtitle_sync_report.py`
   是正式脚本外，其余都是 ep4–7 `verify_report.txt` 里贴出的 ad-hoc 检查
   （`audit2.py/pretts.py/mk_approved.py` 在 `.opencode-runs/ep/` 下有实物，
   已在正文引用）。本手册 §5 把它们的阈值与命令固化成了可复制步骤；
   未来若有人把它们收进正式脚本，以正式脚本为准但阈值不变。
3. 背景音乐音量：`TypePreset.background_music_volume`（`config.py::DEFAULT_TYPE_PRESETS`），
    indicator `0.1`，general/news/book 均为 `0.2`（2026-09-26 commit `95c6f5f` 起：
    indicator 由全局 `0.2` 降为一半，旁白占主导；其他预设不动）。
    ep3 `task.log` 只有文件名
    (`data/assets/music/Ambiment - The Ambient - Kevin MacLeod.mp3`)，无 dB 值；
    ep8 另在 `verify_report.txt` 加 LUFS/dB 对比（旁白段 vs 纯音乐段，并与 ep7 同位置对比），
    那是 ep8 的一次性额外验证，不属于通用标准。
4. YouTube 已有播放列表名是 `什么指标不赚钱`（`yt_publish.py` 按名复用），
   但本系列生产固定用 ID `PLJ8z9DDMq_Yg` 直传尾部，不再按名查找。
5. commit 号：写手册时 video-factory `5eee902`、karios `ec329681`；
   执行时以 `git rev-parse HEAD` 实测为准并写进 `verify_report.txt` 头部。
