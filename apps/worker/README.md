# Video Factory Worker

FastAPI service + independent queue worker for Video Factory.

## Layout

```
src/
├── main.py            # FastAPI app, lifespan (DB init + scheduler)
├── worker.py          # standalone queue consumer: python -m src.worker
├── scheduler.py       # APScheduler tasks: source -> generate -> publish
├── queue.py           # Redis queue with DB-table fallback
├── models.py          # SQLAlchemy models (Series, Task, Run, GenerationJob, ...)
├── routes/
│   ├── videos.py      # generate / list / status / cancel / retry / events
│   ├── series.py      # series CRUD
│   ├── publishers.py  # publisher accounts, folders, login, publish
│   ├── synthetic.py   # ComfyUI image generation (opt-in)
│   └── tasks.py sources.py runs.py ai_settings.py tts_settings.py ...
├── services/
│   ├── video_service.py    # end-to-end generation orchestration
│   ├── compose_service.py  # MoviePy composition
│   ├── synthetic_service.py# ComfyUI SD3.5 image workflow (guarded)
│   └── material/           # Pexels / Pixabay / local / synthetic facade
├── publishers/        # Douyin, Xiaohongshu (Playwright), YouTube (Data API)
├── sources/           # RSS, News API, Hot topics
└── core/              # AI client, TTS engine, subtitles, task logger
```

## Run

```bash
uv run uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload   # API
uv run python -m src.worker                                        # queue consumer
```

## Test

```bash
uv run python -m pytest            # enforces 64% coverage
```

## Notes

- New DB columns are added via lightweight `PRAGMA`-based migrations in
  `database.init_db` (SQLite).
- Synthetic (ComfyUI) generation is opt-in (`ENABLE_SYNTHETIC=1`) and guarded by a
  free-memory gate + circuit breaker.
- Long generation should run in the worker, not the API request thread.
- News pipeline (`type=news`): articles are fetched from GNews (`GNEWS_API_KEY`,
  restart the worker after changing env) and article images become the background
  materials. Missing/failed images fall back to Pexels/online stock — never to
  synthetic ComfyUI. GNews free tier allows ~100 req/day and up to 10 articles,
  so `news_max_articles` defaults to 5 and responses are cached for 15 minutes.
  Image downloads send browser-like headers (User-Agent/Accept/Referer) so CDNs
  such as `gdb.voanews.com` no longer reject them with HTTP 403.

## Book -> series pipeline

Upload a book (`.txt` / `.md` / `.pdf`, UTF-8 or PDF) and split it into one
short-form episode per chapter, then batch-generate the episodes under a series.

```bash
# 1) Create a series from a book (multipart file) and split into episodes
curl -X POST http://localhost:8000/api/series/from-book \
  -F "file=@my-book.md" -F "title=我的书"

# PDFs work the same way (text extracted with pypdf)
curl -X POST http://localhost:8000/api/series/from-book \
  -F "file=@失去的三十年.pdf" -F "title=失去的三十年"

# ...or import into an existing series (JSON body works without multipart too)
curl -X POST http://localhost:8000/api/series/<series_id>/import-book \
  -H 'Content-Type: application/json' \
  -d '{"title":"我的书","text":"第一章 ...\n第二章 ..."}'

# 2) Inspect imported episodes
curl http://localhost:8000/api/series/<series_id>/episodes

# 3) Queue up to N episode videos (book pipeline, portrait, online bg)
curl -X POST "http://localhost:8000/api/series/<series_id>/generate-episodes?limit=3"
```

- Splitter recognizes markdown headings, `第N章` / `第N节`, `Chapter N`, and
  prologue/epilogue headings; blank-line paragraphs are the last resort.
- TOC-aware: when a chapter title appears both in a 目录 and in the body, the
  occurrence with the longest following body wins (works for front *and* back
  TOCs). TOC-only entries with no real body are dropped.
- Episodes are capped (`BOOK_MAX_EPISODES=20`) and trimmed to `BOOK_MAX_CHARS=3200`
  characters (large enough for a 3-4 min spoken episode).
  `BOOK_DEFAULT_EPISODES_PER_CALL=3` bounds each generate call.
- Episodes persist as `data/series/<slug>/episodes.json` — no DB migration in v1.
- `generate-episodes` queues `type=book` tasks (`background_source=online`,
  `resolution=landscape`, `series_id` set). Book videos use online/local stock
  materials only — never silent synthetic. The `content_type` is persisted on
  each task's `status.json`.
- `type=book` scripts are **gentle, friendly 讲书 scripts**: the worker always
  runs a warm "像和朋友聊一本书" rewrite (`book_script.BOOK_DENSE_REWRITE_PROMPT`)
  even when `rewrite_content` is not set, then generates a few calm points with
  the `book_script.BOOK_DENSE_SCRIPT_PROMPT`. Episodes target **3-4 minutes**
  (~800-1000 汉字 / 180-240s spoken), with a slower TTS rate (`BOOK_TTS_RATE`,
  default `-8%`) and a `BOOK_SEGMENT_PAUSE_SECONDS` (default `0.5`) pause
  between segments. Tasks persist `book_dense: true` in `status.json`.
- The generated cover opens the video as a title card for
  `BOOK_COVER_HOLD_SECONDS` (default `3.0`) — the first frame is the cover.
- Stills change about every `BOOK_IMAGE_HOLD_SECONDS` (default `5.0`), so a
  full episode uses ~40-50 images instead of holding a handful for ~10s each.
- Pexels stills prefer `large2x`/`original` and higher width (≥ ~1280 when
  metadata exists) for sharper output.
- Stills are **deduplicated per episode**: the fetcher keeps seen Pexels photo
  ids / filenames for the whole task and passes them back to Pexels so it walks
  further down the ranked list instead of reusing a photo. If unique stills run
  out the segment degrades to a clip/placeholder rather than repeating an image.
- Book material search derives English terms from the **chapter title + key
  nouns** (`derive_book_search_terms`, e.g. 泡沫经济 → `japan real estate boom`,
  日元升值 → `yen appreciation`, 雷曼 → `lehman brothers`) and runs every query
  through `to_visual_search_terms`. Book stock queries are **visual-safe**: avoid
  polysemous words like `bubble`/`foam`/`burst` that APIs read literally (soap
  bubbles) and rewrite them to concrete Japan/city/market imagery. A **chapter
  anchor** (`chapter_anchor_terms`) is derived once as a light theme bias, while
  `build_book_segment_query` leads with the segment's own concrete visuals and
  drops generic fillers (`economy`/`japan` alone), so consecutive stills stay on
  theme without locking onto one wrong literal. When nothing translates the book
  path uses book-specific fallbacks — never the global
  `stock market / world news / economy` list. Images are fetched before clips to
  keep smoke runs fast/relevant, and the final English queries are logged.
- Consecutive stills are joined with a **crossfade** of
  `BOOK_SLIDE_TRANSITION_SECONDS` (default `0.5`). Each still is extended by the
  transition so it overlaps the next one (borrowed from adjacent holds), keeping
  audio/subtitle timing and the total duration unchanged. The cover stays a clean
  first frame with no fade.

## Custom per-segment images/charts

Attach your own local images (charts, diagrams, screenshots) to individual script
segments and optionally override the cover. Segments without `segment_images`
keep the normal stock pipeline; segments with images never hit Pexels/Pixabay.

```bash
curl -X POST http://localhost:8000/api/videos/generate \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "失去的三十年",
    "content": "...",
    "cover_image": "/abs/path/cover.png",
    "segment_images": [
      {
        "segment": 0,
        "images": ["/abs/path/gdp.png", "/abs/path/inflation.png"],
        "hold_seconds": [6.0, 4.0],
        "fit": "contain",
        "motion": "gentle"
      },
      {
        "segment": 2,
        "images": ["/abs/path/trade.png"],
        "fit": "cover"
      }
    ]
  }'
```

- Every path is read **locally by the worker** and validated at request time:
  the file must exist, be a file, and end in `.png`/`.jpg`/`.jpeg`/`.webp`.
- `segment` is the 0-based script segment index; when omitted the list position
  is used. Out-of-range indices are logged and ignored.
- `fit`: `contain` (default) keeps the whole image visible, letterboxed on the
  neutral chart background (`CHART_BACKGROUND_COLOR`, default `#16181c`), with a
  bottom subtitle band of `CHART_SUBTITLE_BAND_RATIO` (default `0.12` of the
  frame); `cover` crops to fill (the old behaviour).
- `motion`: `gentle` adds a very slow 1.00→1.03 zoom inside the contain box
  (never cropping chart content); `none` (default) is static.
- `hold_seconds` sets each image's on-screen time; the list is scaled
  proportionally so the images still cover the full segment span (speech +
  pause). Without it the span is split evenly. Consecutive stills keep the
  crossfade (`BOOK_SLIDE_TRANSITION_SECONDS`).
- `cover_image` uses that local image as the title card (rendered whole, no
  crop) instead of generating a cover; narration still starts after
  `BOOK_COVER_HOLD_SECONDS`.
- Custom-visual episodes (a `general` request carrying `segment_images`) use the
  calm book-like pacing: `-8%` rate, `0.38s` sentence pauses and `0.5s` segment
  pauses (see [Type presets](#type-presets)).
- Subtitles that fall inside a `contain` segment's narration window are rendered
  in the bottom band at `CHART_SUBTITLE_FONT_RATIO` (default `0.036` of the
  frame height); all other subtitles keep the default placement.

## Type presets

One place for per-content-type narration/visual defaults. `get_type_preset(type)`
merges the type's overrides over the `general` preset, so unknown fields fall back
to the neutral defaults. Override any field with the `TYPE_PRESETS` env JSON.

| field | general | news | book | indicator |
| --- | --- | --- | --- | --- |
| `voice` | `zh-CN-XiaoxiaoNeural` | `zh-CN-XiaoxiaoNeural` | `zh-CN-XiaoxiaoNeural` | `zh-CN-YunxiNeural` |
| `tts_rate` | `+0%` | `+0%` | `-8%` | `-8%` |
| `sentence_pause_seconds` | `0` | `0` | `0.38` | `0.38` |
| `segment_pause_seconds` | `0` | `0` | `0.5` | `0.5` |
| `image_hold_seconds` | `4.0` | `4.0` | `5.0` | `5.0` |
| `orientation` | `landscape` | `landscape` | `landscape` | `landscape` |
| `footage` | `video_first` | `images_first` | `video_first` | `video_first` |
| `proofread` | `false` | `false` | `true` | `true` |

The `book` preset tracks the legacy `BOOK_TTS_RATE`,
`BOOK_SEGMENT_PAUSE_SECONDS` and `BOOK_IMAGE_HOLD_SECONDS` settings so existing
env overrides keep working; an explicit `TYPE_PRESETS` book entry wins.

```bash
TYPE_PRESETS='{"indicator":{"voice":"zh-CN-YunyangNeural"}}' uv run python -m src.worker
```

`indicator` is already a known preset (ready for the manifest-driven chart
episodes in G2): male voice, calm pacing, video-first stock and `proofread=true`.

## Sentence pauses

`edge-tts` writes one mp3 per script segment, so sentences inside a segment used
to run together. After synthesis the worker cuts the decoded PCM at the **midpoint
of each inter-sentence gap** (or at the next sentence's start when they overlap),
splices in `sentence_pause_seconds` of silence, re-encodes the mp3 in place and
shifts the sentence boundaries by `k * pause` for the k-th sentence. Subtitles
therefore stay in sync automatically. Only types with a non-zero
`sentence_pause_seconds` (book/indicator, or `general` with `segment_images`) are
affected. The step is best-effort: on any codec failure the original
audio/boundaries are kept and a warning is logged.

## Script review (lint + proofread)

Before TTS, types whose preset has `proofread=true` (book/indicator) run a
double-check on the **final TTS input** (`to_speakable_text(seg.text)`):

- **Deterministic lint** flags doubled/stray punctuation, a comma next to
  `《》`/quotes, ASCII punctuation beside CJK, >60-char unpunctuated runs, split
  numbers (`15. 5`, `52 %`, `1 985`), leftover Markdown and residual quote
  brackets. Safe mechanical issues are auto-fixed in the script text (doubled
  punctuation, ASCII→full-width next to CJK, comma removed around `《》`).
- **LLM proofread** sends all segment texts as a JSON array and only accepts a
  rewrite when the number-token multiset is identical (Arabic decimals/percent/
  thousand separators and Chinese numeral runs such as `三点五`), the length change
  is `<= 15%` and the result is non-empty. On any LLM error the originals are kept.

Results are written to the task dir as `script_review.json` (per-segment
original/final/tts_input, lint findings before/after, auto-fixes, proofread
verdict + compact diff, char count) and a readable `script_review.md`.

## Multi-language (EN) episodes for YouTube growth

The Chinese pipeline is unchanged and is the master. Add `language=en` (alias
`lang`) to a book episode or single-video generate to emit an English-narration
variant into the same series:

- The dense Chinese script is translated **segment-by-segment** into natural
  spoken English (same segment count/order -> same visual timeline), and segment
  keywords become concrete English stock-search terms.
- Edge-TTS voice map: `zh` -> `zh-CN-XiaoxiaoNeural` (unchanged),
  `en` -> `en-US-AriaNeural`. A mismatched Chinese voice is swapped out
  automatically; subtitles use the spoken language.
- The worker also generates an English YouTube **hook title + description +
  tags** (curiosity + topic keywords) and stores them on the task status as
  `youtube_title` / `youtube_description` / `youtube_tags`.
- Publishing to YouTube uses that packaging, sets `snippet.defaultLanguage`, and
  defaults privacy to `YOUTUBE_DEFAULT_PRIVACY` (`unlisted` unless set).

```bash
# 0) One-time: a YouTube publisher account with OAuth creds + a bound playlist
curl http://localhost:8000/api/publishers
# (create it, list folders, then PUT folder_id to bind the target playlist)

# 1) Queue 1 English book episode (same series as the zh master is fine)
curl -X POST "http://localhost:8000/api/series/<series_id>/generate-episodes?limit=1&language=en"
# -> {"data":{"tasks":[{"task_id":"video-xxxx","title":"第一章 ..."}]}}

# Single-video variant (English):
curl -X POST http://localhost:8000/api/videos/generate \
  -H 'Content-Type: application/json' \
  -d '{"type":"book","title":"失去的三十年","content":"...","language":"en"}'

# 2) Wait for completion, then inspect the generated English packaging
curl http://localhost:8000/api/videos/tasks/<task_id>
# data.language == "en", data.youtube_title / youtube_description / youtube_tags

# 3) Approve + publish to the YouTube playlist (unlisted by default)
curl -X POST http://localhost:8000/api/videos/tasks/<task_id>/review \
  -H 'Content-Type: application/json' -d '{"decision":"approve"}'
curl -X POST http://localhost:8000/api/videos/tasks/<task_id>/publish \
  -H 'Content-Type: application/json' \
  -d '{"platforms":["youtube"],"folder_id":"PLxxxx","privacy":"unlisted"}'

# ...or trigger the queued publish worker (drains publish_jobs):
cd apps/worker && uv run python -m src.worker
```

`POST /api/publishers/{id}/publish` accepts `language` / `publish_locale` too
(`publish_locale` e.g. `en-US` overrides the BCP-47 caption/audio language).

## Agent-Facing YouTube Publishing Workflow

This section documents the reliable, timeout-protected YouTube publish path via the worker API. Any agent can follow these steps to list/create playlists, bind them to a publisher, approve a completed video task, and publish to YouTube with clear error messages when Google APIs are unreachable.

### Prerequisites

1. **Publisher Account with Valid OAuth Credentials**  
   Create or retrieve a YouTube publisher account with OAuth refresh token stored in the `credentials` JSON field. The publisher must have `has_credentials: true` when fetched via `GET /api/publishers/{id}`.

2. **Approved Video Task**  
   A completed video task must be reviewed and approved via `POST /api/videos/tasks/{task_id}/review` with `{"decision": "approve"}`.

### API Workflow

```bash
# 1. List existing publishers
curl http://localhost:8000/api/publishers
# Response includes "has_credentials" and "has_cookies" flags (raw secrets are redacted)

# 2. Get a specific YouTube publisher
PUBLISHER_ID="e58dcc1f7a1c8c8b"
curl http://localhost:8000/api/publishers/${PUBLISHER_ID}

# 3. List existing YouTube playlists (folders)
#    - Returns 504 Gateway Timeout (not indefinite hang) if Google is unreachable
#    - Default timeout: 30s (configurable via EXTERNAL_API_TIMEOUT_S env var)
curl http://localhost:8000/api/publishers/${PUBLISHER_ID}/folders

# 4. Create a new playlist if needed
#    - Also protected by timeout; returns 504 on network failure
curl -X POST http://localhost:8000/api/publishers/${PUBLISHER_ID}/folders \
  -H "Content-Type: application/json" \
  -d '{"name": "My Series Playlist", "description": "Episode uploads", "privacy": "private"}'
# Response: {"success": true, "data": {"id": "PLxxx...", "name": "My Series Playlist"}}

# 5. Update the publisher to bind the default folder_id
PLAYLIST_ID="PLxxx..."
curl -X PUT http://localhost:8000/api/publishers/${PUBLISHER_ID} \
  -H "Content-Type: application/json" \
  -d "{\"folder_id\": \"${PLAYLIST_ID}\"}"

# 6. Approve a completed video task
TASK_ID="abc123..."
curl -X POST http://localhost:8000/api/videos/tasks/${TASK_ID}/review \
  -H "Content-Type: application/json" \
  -d '{"decision": "approve", "notes": "Looks good"}'

# 7. Publish the approved video to YouTube
#    - Upload timeout: 150s (5x the default external_api_timeout_s)
#    - Playlist add timeout: 30s
#    - Returns clear error on timeout or network failure
curl -X POST http://localhost:8000/api/publishers/${PUBLISHER_ID}/publish \
  -H "Content-Type: application/json" \
  -d "{\"task_id\": \"${TASK_ID}\", \"title\": \"Episode 1\", \"description\": \"My video\", \"folder_id\": \"${PLAYLIST_ID}\", \"privacy\": \"private\"}"
# Response: {"success": true/false, "data": {"platform": "YouTube", "post_url": "https://youtube.com/watch?v=...", "post_id": "...", "error": null}}
```

### Expected Error Scenarios

1. **Google APIs Unreachable (Network / Proxy Block)**  
   ```json
   {
     "detail": "Request timed out: Google API request timed out after 30s. Check network connectivity to googleapis.com"
   }
   ```
   HTTP Status: **504 Gateway Timeout**

2. **Missing or Invalid Credentials**  
   ```json
   {
     "success": false,
     "data": {
       "platform": "YouTube",
       "error": "YouTube 凭据未配置或无效（需要在 PublisherAccount.credentials 提供含 refresh_token 的 OAuth JSON）"
     }
   }
   ```

3. **Video File Not Found**  
   HTTP Status: **400 Bad Request**  
   ```json
   {"detail": "video_path required and must exist"}
   ```

### Security Notes

- **GET** `/api/publishers` and **GET** `/api/publishers/{id}` responses now **redact** raw credentials and cookies.
- Fields returned:
  - `has_credentials`: boolean indicating presence of credentials
  - `has_cookies`: boolean indicating presence of cookies
  - **No raw** `credentials` or `cookies` fields in responses
- **POST** and **PUT** routes still accept credentials for creation/update, but responses remain redacted.

### Configuration

Set the external API timeout via environment variable (applies to all Google API calls):

```bash
# Default: 30.0 seconds for folder operations, 150.0s for uploads (5x multiplier)
EXTERNAL_API_TIMEOUT_S=45.0
```

#### Proxy Support

The YouTube publisher honors standard HTTP proxy environment variables. This is essential for networks that require a proxy to reach Google APIs (e.g., users in regions where direct access to `googleapis.com` is blocked).

**Supported Environment Variables:**

- `HTTPS_PROXY` or `https_proxy` — Proxy for HTTPS requests (preferred for googleapis.com)
- `HTTP_PROXY` or `http_proxy` — Proxy for HTTP requests (fallback)
- `NO_PROXY` or `no_proxy` — Comma-separated list of hosts to exclude from proxying

**Supported Proxy Schemes:**

- `http://` — HTTP proxy (most common, e.g., Clash, V2Ray)
- `https://` — HTTPS proxy
- `socks5://` — SOCKS5 proxy
- `socks4://` — SOCKS4 proxy

**Example Setup:**

```bash
# For networks requiring a local proxy (e.g., Clash on macOS)
export HTTPS_PROXY=http://127.0.0.1:7890
export HTTP_PROXY=http://127.0.0.1:7890
export NO_PROXY=127.0.0.1,localhost

# Start the worker
uv run uvicorn src.main:app --host 0.0.0.0 --port 8000
```

**Verification:**

When a proxy is configured, you'll see log messages like:

```
INFO:src.publishers.youtube:YouTube API using proxy: http://127.0.0.1:7890
```

**Troubleshooting:**

1. **Direct Connection Times Out:**
   ```bash
   # Test if googleapis.com is reachable directly
   curl -I https://www.googleapis.com/
   
   # If timeout, verify proxy works
   curl -x http://127.0.0.1:7890 -I https://www.googleapis.com/
   ```

2. **Worker Still Times Out:**
   - Ensure proxy is running (`lsof -i :7890` or `netstat -an | grep 7890`)
   - Check proxy logs for connection attempts
   - Verify proxy allows connections from worker process
   - Test with `scutil --proxy` (macOS) to confirm system proxy settings

3. **Mixed Environment:**
   - If only some services need proxy, use `NO_PROXY` to exclude local services:
     ```bash
     export NO_PROXY=127.0.0.1,localhost,*.local
     ```

### Testing Without Live Google Connection

Run the unit tests to verify timeout and credential redaction behavior:

```bash
cd apps/worker
uv run pytest tests/test_youtube_timeout_and_security.py -v
```

All tests mock Google API calls to verify:
- Timeout protection on `list_folders`, `create_folder`, and `upload`
- HTTP 504 responses instead of indefinite hangs
- Credential redaction in API responses
