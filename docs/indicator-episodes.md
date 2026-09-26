# Indicator episodes (`type=indicator`)

Indicator episodes are **manifest-driven chart videos**: a research pipeline
produces one 1920x1080 chart image per point plus a `manifest.json`, and the
worker turns that into a narrated landscape video where every script segment is
bound to its own chart. No stock material is searched for bound segments, so the
charts are shown exactly (whole image, letterboxed on the neutral chart
background with a bottom subtitle band).

The flow is **script-only → review → approved script → render**, so a human can
read and safely edit the narration before any TTS/render cost is incurred.

## Manifest schema

The canonical manifest is a JSON **list**, kept in order:

```json
[
  {"file": "00_title_card.png", "section": "intro",        "title": "MACD 是什么", "key_point": "MACD 是趋势指标",   "suggested_seconds": 15},
  {"file": "01_explain.png",    "section": "explain",      "title": "怎么算的",     "key_point": "12 与 26 日均线",   "suggested_seconds": 25},
  {"file": "02_retail.png",     "section": "retail_usage", "title": "散户怎么用",   "key_point": "金叉买入、死叉卖出", "suggested_seconds": 20},
  {"file": "03_history.png",    "section": "history",      "title": "历史表现",     "key_point": "胜率约 45%",        "suggested_seconds": 30},
  {"file": "05_whynot.png",     "section": "why_not",      "title": "为什么不赚钱", "key_point": "震荡市反复打脸",     "suggested_seconds": 25},
  {"file": "06_summary.png",    "section": "summary",      "title": "总结",         "key_point": "只做趋势、控制仓位",  "suggested_seconds": 15}
]
```

| field | required | meaning |
| --- | --- | --- |
| `file` | yes | Chart image, relative to the manifest's directory (absolute allowed). `.png`/`.jpg`/`.jpeg`/`.webp`, must exist. Aliases: `path`, `image`. |
| `section` | no | One of `intro` \| `explain` \| `retail_usage` \| `history` \| `why_not` \| `summary`. Unknown values are kept but logged. |
| `title` | no | Short chart title (context for the model). |
| `key_point` | no | The fact(s) the narration must convey. **Every number here must appear verbatim in the segment.** Aliases: `keypoint`, `point`. |
| `suggested_seconds` | no | Target spoken seconds (typically 10–30). Aliases: `seconds`, `duration`. When absent the total (`target_seconds`, default 300) is split evenly. |

The manifest may also be an object `{"charts": [...]}` or `{"items": [...]}`
with optional top-level `indicator_id`, `title` / `indicator_name`.

**Ordering** matches the research pipeline's narrative: `00` intro →
`01` explain → `02` retail_usage → history (`03,09,04,11,07,08,10`) →
why_not (`05,12,13`) → `06` summary. The loader never re-sorts.

**Title card / cover**: the first item whose `section == "intro"` and whose
filename contains `title` (else the first item) is used as the 3 s cover. The
cover also has its own narration segment (the intro).

Charts should be **1920x1080**. `suggested_seconds` are typically 10–30 s and the
whole episode usually sums to **~240–300 s**. Pass
`"target_seconds": 300` to scale the even-split fallback when some items omit it.

## CLI

Run in-process with the working tree (no API server, no queue):

```bash
cd apps/worker

# 1) Script only -> write script.json / script.md / script_review.md, then stop
uv run python scripts/indicator_episode.py \
  --manifest /path/to/charts/manifest.json [--title "MACD 金叉"] \
  [--context /path/to/summary_zh.md] [--voice zh-CN-YunxiNeural] \
  [--out-dir DIR] --script-only

# 2) Render an approved (possibly hand-edited) script.json
uv run python scripts/indicator_episode.py --approved-script DIR/script.json [--out-dir DIR2]

# 3) Script + render in one go
uv run python scripts/indicator_episode.py --manifest /path/to/charts/manifest.json
```

The script prints `TASK_DIR`, the status and the paths of `script.json`,
`script.md`, `script_review.md` and the final video. Exit code is **0** on
success / `script_ready`, **1** on failure. `uv run python scripts/indicator_episode.py --help`
lists every flag.

A generic sibling for the other pipelines shares the same behaviour:

```bash
uv run python scripts/generate_episode.py --type book \
  --title "第一章" --content-file chapter.txt --script-only

uv run python scripts/generate_episode.py --type general \
  --series-episodes /path/episodes.json --episode-index 2 --out-dir DIR

uv run python scripts/generate_episode.py --type news --title "市场快讯" --script-only
```

## API

`POST /api/videos/generate`:

```json
{"type": "indicator", "custom_visuals_manifest": "/abs/path/charts/manifest.json", "title": "MACD 金叉", "script_only": true}
```

…then render the approved script:

```json
{"type": "indicator", "approved_script": "/abs/path/<task_dir>/script.json"}
```

`custom_visuals_manifest` is required for `type=indicator` (unless an
`approved_script` is given) and the path must exist. `content` and `title` are
optional for indicator requests (they default from the manifest). Indicator
requests default to **landscape** unless a resolution/orientation was set.

## Script-only → review → approved-script workflow

1. Run with `--script-only` (or `"script_only": true`). The worker generates the
   script, runs the review and writes into the task dir:
   - `script.json` — the full script including per-segment images / `section` /
     `chart` / `key_point`, plus `content_type`, `manifest`, `voice`, `created_at`.
   - `script.md` — human-readable: chart file, section, key point, text, char
     count and estimated seconds per segment.
   - `script_review.json` / `script_review.md` — per-segment lint, auto-fixes,
     proofread verdict and the indicator number check (`chart`, `section`,
     `key_point`, `required_numbers`, `numbers_found`,
     `numbers_missing_after_retry`, `key_point_appended`).
   - Task status becomes `script_ready` (message `脚本已生成，等待审核`).
2. Read `script_review.md` and edit **only `segments[i].text`** in `script.json`;
   keep the segment count/order and do not touch `images`/`fit`/`motion`/
   `section`/`chart`/`key_point`. Keep every number in `key_point` in the text.
3. Render with `--approved-script DIR/script.json` (or the `approved_script`
   field). AI generation and the proofread LLM are skipped; lint still runs and
   is reported, but auto-fixes are **not** applied to an approved script. Bound
   images are kept and each chart path is validated.

`script_only` works for **all** types (`general`/`book`/`news` too): it stops
after script + review and writes `script.json` / `script.md`.

## Number check

For every indicator segment, each number token in the item's `key_point` must
appear in the segment text, compared on normalised forms (thousand separators
and spaces stripped). The extractor is shared with the proofread guard
(`src.services.script_review.number_tokens`): Arabic numbers incl. sign,
decimals, `%`, thousands/time separators, and Chinese numeral runs of length
>= 2.

If numbers are missing, the worker makes **one** focused retry for only those
segments, listing the exact numbers to include verbatim. Anything still missing
gets the `key_point` appended verbatim as a final sentence (guaranteed to end
with `。`). The per-segment report is stored in the script review.

## Type presets

`get_type_preset(type)` merges the type's overrides over `general`; unknown
fields fall back to neutral defaults. Override any field with the `TYPE_PRESETS`
env JSON, or per request with `voice` / `voice_rate` (an explicit voice or a
non-default `voice_rate` wins over the preset).

| field | general | news | book | indicator |
| --- | --- | --- | --- | --- |
| `voice` | `zh-CN-YunjianNeural` | `zh-CN-YunjianNeural` | `zh-CN-YunjianNeural` | `zh-CN-YunjianNeural` |
| `tts_rate` | `+0%` | `+0%` | `-8%` | `+2%` |
| `sentence_pause_seconds` | `0` | `0` | `0.38` | `0` |
| `sentence_gap_seconds` | `0` | `0` | `0` | `0.75` |
| `segment_pause_seconds` | `0` | `0` | `0.5` | `0.5` |
| `image_hold_seconds` | `4.0` | `4.0` | `5.0` | `5.0` |
| `orientation` | `landscape` | `landscape` | `landscape` | `landscape` |
| `footage` | `video_first` | `images_first` | `video_first` | `video_first` |
| `proofread` | `false` | `false` | `true` | `true` |
| `presenter_intro` | `false` | `true` | `true` | `true` |
| `chart_layout` | `letterbox` | `letterbox` | `letterbox` | `fullframe` |

```bash
TYPE_PRESETS='{"indicator":{"voice":"zh-CN-YunyangNeural"}}' uv run python -m src.worker
```

### Sentence gap: target, not extra silence

edge-tts already leaves ~0.7 s of silence between sentences (its
`SentenceBoundary` durations include that trailing silence). The old
`sentence_pause_seconds=0.38` was **added on top** of it, so indicator episodes
had ~1.1 s sentence gaps. The indicator preset now sets
`sentence_gap_seconds=0.75`: the worker measures the silence that is already
there at each sentence boundary and only tops it up (or trims an over-long pause
down) to 0.75 s, shifting the subtitle boundaries by the real delta. The rate is
`+2%` (~11% faster than the old `-8%`). `sentence_pause_seconds` is the legacy
additive mode and still applies to `book` (and `general` with `segment_images`);
when `sentence_gap_seconds` > 0 it takes precedence.

Probe the real gap of a clip through the actual synthesis + alignment path:

```bash
cd apps/worker
uv run python scripts/tts_gap_probe.py --type indicator \
  --text "第一句。第二句。" --out /tmp/clip.mp3 [--rate +2%] [--gap 0.75]
uv run python scripts/tts_gap_probe.py --measure /tmp/clip.mp3
```

It prints the voice, rate, gap setting, duration, the detected speech runs and
the measured sentence gaps (silences >= 0.45 s) with mean/min/max. Always exits 0.

## Full-frame chart layout (default for indicator)

Indicator episodes default to the **full-frame** chart layout: the whole
1920x1080 frame is light and the chart is shown whole (contained, never cropped,
never stretched). Author charts at **1920x950** (matplotlib
`figsize=(19.2, 9.5)` at `dpi=100`) and they fill the chart box edge-to-edge. A
16:9 chart (1920x1080) still works: it is contained (~1689x950) and the side
margins are filled with the chart's own background colour, sampled from the
image border. Nothing ever shows black — including crossfades, gaps between
clips and the subtitle band.

- Canvas colour: the per-channel median of the chart's outermost 4-pixel border;
  a dark border (mean < 128) falls back to `chart_canvas_color`
  (default `#ffffff`).
- Subtitle band at the bottom, height `chart_fullframe_band_px`
  (default `130` at 1080p, scaled by `H / 1080`), using the same canvas colour.
  Subtitles are dark (`chart_subtitle_dark_color`, default `#1f2329`),
  **strokeless**, and vertically centred in the band, so they never overlap the
  chart box.
- The title-card cover uses the whole frame (`band=0`); a 1920x1080 cover fills
  it exactly.

| name | meaning |
| --- | --- |
| preset key `chart_layout` | `"fullframe"` (indicator default) or `"letterbox"` (old dark layout: dark background, `_subtitle_band_height`, white text + black stroke, gentle motion) |
| `chart_canvas_color` | frame fallback colour (default `#ffffff`) |
| `chart_fullframe_band_px` | subtitle band height at 1080p (default `130`) |
| `chart_subtitle_dark_color` | fullframe subtitle text colour (default `#1f2329`) |
| `_fit_fullframe`, `_fullframe_band_height`, `_image_border_color` | compose helpers |
| `chart_layout` | `compose_video(...)` kwarg threaded from the preset |

Opt out and keep the old dark letterbox look:

```bash
TYPE_PRESETS='{"indicator":{"chart_layout":"letterbox"}}' uv run python -m src.worker
```

## Presenter (pen name)

The channel presenter is the pen name `躺平的老黄` (never a real name). When
active it is the first sentence of segment 0 — exactly `大家好，我是躺平的老黄。`
— immediately followed by the episode intro, and it is labelled on the cover.

- `PRESENTER_NAME` (default `躺平的老黄`) sets the name; `PRESENTER_ENABLED=0`
  switches the feature off globally.
- `presenter_intro` (preset table) enables it for `book`/`news`/`indicator`;
  `general` is off. Non-`zh` narration never gets the presenter.
- Per request, `presenter_name` (aliases `presenterName`/`presenter`): omitted
  uses the default, `""` switches it off for that request, any other value
  overrides the name (JSON and CLI `VideoGenerateRequest`).

The greeting is requested from the LLM and then enforced deterministically
(`src/services/presenter.py`), including again after the proofread review so the
LLM can never change it. An approved script renders verbatim; a missing greeting
is recorded as `presenter_greeting: "missing"` in `script_review.json` with a
warning.

For indicator episodes the manifest title card is copied to
`cover_presenter.png` (source untouched), used as the cover **and** for the
intro segment bound to the title card, so the name stays visible while the title
card is on screen. Generated covers draw the name small under the title.

**Footage**: `video_first` is the default for `book` and `indicator` — Pexels
**videos first, images as fallback**. A fully bound indicator episode never hits
Pexels at all; footage is only fetched for unbound segments (e.g. an approved
script whose segments carry no `images`).

## Output files

Written into `settings.output_dir/<type>/<slug>/<timestamp-uuid>/` (or `--out-dir`):

| file | meaning |
| --- | --- |
| `script.json` | Full script (`GeneratedScript`) + `content_type` / `manifest` / `voice` / `created_at`. |
| `script.md` | Human-readable per-segment script (chart, section, key point, chars, seconds). |
| `script_review.json` / `.md` | Lint/proofread review incl. the indicator number check. |
| `status.json` | Task status (`script_ready` or `completed`) + `files` map. |
| `segment_N.mp3` | Per-segment narration (full renders). |
| `subtitles.ass` | Burn-in subtitles (full renders). |
| `output.mp4` | Final video (full renders). |

The cover is the manifest title card and is shown for
`BOOK_COVER_HOLD_SECONDS` (default `3.0`); narration starts after it.

## Subtitle sync diagnostics

Cue starts are snapped onto the real speech onsets detected in each segment's
audio, and split long sentences are timed by an estimated spoken length so
numbers/percentages no longer drift. To check a render:

```bash
cd apps/worker
uv run python scripts/subtitle_sync_report.py TASK_DIR [--cover 3.0]
```

It reads `subtitles.ass` and `segment_*.mp3`, detects speech runs, and prints the
per-cue start delta to the nearest onset, the share within 0.15s, the max |delta|
and any mid-phrase pause >= 0.7s. Exit code is always 0.
