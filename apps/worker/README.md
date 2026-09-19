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

Upload a book (`.txt` / `.md`, UTF-8) and split it into one short-form episode
per chapter, then batch-generate the episodes under a series.

```bash
# 1) Create a series from a book (multipart file) and split into episodes
curl -X POST http://localhost:8000/api/series/from-book \
  -F "file=@my-book.md" -F "title=我的书"

# ...or import into an existing series (JSON body works without multipart too)
curl -X POST http://localhost:8000/api/series/<series_id>/import-book \
  -H 'Content-Type: application/json' \
  -d '{"title":"我的书","text":"第一章 ...\n第二章 ..."}'

# 2) Inspect imported episodes
curl http://localhost:8000/api/series/<series_id>/episodes

# 3) Queue up to N episode videos (general pipeline, portrait, online bg)
curl -X POST "http://localhost:8000/api/series/<series_id>/generate-episodes?limit=3"
```

- Splitter recognizes markdown headings, `第N章` / `第N节`, `Chapter N`, and
  prologue/epilogue headings; blank-line paragraphs are the last resort.
- Episodes are capped (`BOOK_MAX_EPISODES=20`) and trimmed to `BOOK_MAX_CHARS=800`
  characters. `BOOK_DEFAULT_EPISODES_PER_CALL=3` bounds each generate call.
- Episodes persist as `data/series/<slug>/episodes.json` — no DB migration in v1.
- `generate-episodes` uses `type=general`, `background_source=online`,
  `resolution=portrait` and queues normal video tasks (`series_id` set).
