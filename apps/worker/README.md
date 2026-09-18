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
