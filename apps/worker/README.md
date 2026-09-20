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
  `resolution=portrait`, `series_id` set). Book videos use online/local stock
  materials only — never silent synthetic. The `content_type` is persisted on
  each task's `status.json`.
- `type=book` scripts are **dense key-point scripts**: the worker always runs a
  "要点压缩" rewrite (`book_script.BOOK_DENSE_REWRITE_PROMPT`) even when
  `rewrite_content` is not set, then generates 6-12 hard points with the
  `book_script.BOOK_DENSE_SCRIPT_PROMPT`. Episodes target **3-4 minutes**
  (~1000-1400 汉字 / 180-240s spoken), while keeping the no-fluff key-point rule.
  Tasks persist `book_dense: true` in `status.json`.
- The generated cover opens the video as a title card for
  `BOOK_COVER_HOLD_SECONDS` (default `3.0`) — the first frame is the cover.
- Stills change about every `BOOK_IMAGE_HOLD_SECONDS` (default `4.0`), so a
  full episode uses ~45-60 images instead of holding a handful for ~10s each.
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

### Proxy Support

YouTube publisher supports HTTP/HTTPS/SOCKS proxies via environment variables. This requires **PySocks** (automatically installed as a dependency since this fix).

```bash
# HTTP/HTTPS proxy (e.g., Clash, V2Ray, or corporate proxy)
HTTPS_PROXY=http://127.0.0.1:7890
# or
HTTP_PROXY=http://proxy.example.com:8080

# SOCKS5 proxy
HTTPS_PROXY=socks5://127.0.0.1:1080

# SOCKS4 proxy
HTTPS_PROXY=socks4://127.0.0.1:1080

# Proxy with authentication
HTTPS_PROXY=http://username:password@proxy.example.com:8080
```

**Notes:**
- The publisher automatically detects proxy settings from environment variables
- If proxy is configured but PySocks is not installed, you'll get a clear error: `"PySocks is required for proxy support but is not installed. Please install it with: pip install PySocks"`
- Proxy configuration applies to all YouTube API operations (list folders, create playlist, upload video)
- Both `HTTPS_PROXY` and `https_proxy` (lowercase) are supported

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
