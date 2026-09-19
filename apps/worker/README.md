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
  nouns** (`derive_book_search_terms`, e.g. 泡沫经济 → `bubble economy`, 日元升值 →
  `yen appreciation`, 雷曼 → `lehman brothers`). A **chapter anchor**
  (`chapter_anchor_terms`) is derived once and prepended to every segment query;
  `build_book_segment_query` then adds at most two narrower segment terms and
  drops generic fillers (`economy`/`japan` alone), so consecutive stills stay on
  the same theme instead of jumping topics. When nothing translates the book path
  uses book-specific fallbacks — never the global
  `stock market / world news / economy` list. Images are fetched before clips to
  keep smoke runs fast/relevant, and the final English queries are logged.
- Consecutive stills are joined with a **crossfade** of
  `BOOK_SLIDE_TRANSITION_SECONDS` (default `0.5`). Each still is extended by the
  transition so it overlaps the next one (borrowed from adjacent holds), keeping
  audio/subtitle timing and the total duration unchanged. The cover stays a clean
  first frame with no fade.
