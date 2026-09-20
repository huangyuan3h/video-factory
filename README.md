# Video Factory

Automated video generation and publishing factory. Fetch content from RSS/news
sources or paste text, generate short videos with AI, group them into series,
and publish to social platforms.

## Features

- **Content Sources**: RSS feeds, News APIs, Hot topics (Weibo, Zhihu)
- **AI Integration**: OpenAI-compatible API support (GPT-4o, DeepSeek, etc.)
- **TTS**: Edge-TTS / OpenAI-compatible local TTS (Qwen3-TTS, Spark-TTS)
- **Video Generation**: MoviePy + FFmpeg composition, per-segment timeline
- **Material**: Pexels, Pixabay, local library, optional ComfyUI synthetic images
- **Series**: group a family of videos into one folder with shared defaults
- **Queue / Worker**: Redis or DB-backed jobs, independent worker process
- **Scheduler**: cron tasks that fetch → generate → (optionally) publish
- **Auto Publishing**: Playwright (Douyin, Xiaohongshu) + YouTube Data API

## Tech Stack

| Component | Technology |
|-----------|------------|
| Frontend | Next.js 15, TypeScript, Tailwind CSS, shadcn/ui |
| Backend | FastAPI, APScheduler, SQLAlchemy |
| Database | SQLite |
| Video | MoviePy, FFmpeg |
| TTS | Edge-TTS / OpenAI-compatible local server |
| AI | OpenAI SDK (compatible mode) |
| Desktop | Tauri 2.x |

## Project Structure

```
video-factory/
├── apps/
│   ├── web/          # Next.js frontend
│   ├── desktop/      # Tauri desktop app
│   └── worker/       # FastAPI worker service
├── packages/
│   ├── shared/       # Shared TypeScript types
│   └── database/     # Prisma schema
└── data/
    ├── assets/       # Local video/image/music assets
    └── output/       # Generated videos (grouped by series)
```

## Quick Start

### Prerequisites

- Node.js 20+, pnpm 9+, Python 3.11+, FFmpeg

### Installation

```bash
pnpm install
cd apps/worker && uv sync   # or: pip install -r requirements.txt
playwright install chromium
```

### Development

```bash
# One-click: web + API + queue worker (ComfyUI off by default)
pnpm dev

# Enable ComfyUI (opt-in; heavy on RAM)
pnpm dev:comfyui
```

Individual services:

```bash
pnpm web dev                       # Next.js frontend
pnpm worker:dev                    # FastAPI API (uvicorn)
cd apps/worker && uv run python -m src.worker   # queue consumer
```

The DB schema (including new columns) is created/migrated automatically on API start.

### Desktop App

```bash
cd apps/desktop
pnpm tauri:dev     # development
pnpm tauri:build   # release
```

## Configuration

Copy `.env.example` to `.env` (repo root) and fill what you need. Everything is
optional except an AI provider for script generation (set in the UI or env).

### AI Provider

Set in the Settings page or via `OPENAI_BASE_URL` / `OPENAI_API_KEY` /
`OPENAI_MODEL`. A fallback provider (DeepSeek / Vercel gateway) is used for the
optional rewrite step.

### TTS

- Edge-TTS voices: `zh-CN-XiaoxiaoNeural` (default), `zh-CN-YunxiNeural`, etc.
- Local: set `VLLM_TTS_URL` (and optionally `VLLM_TTS_HQ_URL` for Spark-TTS).

### Series (系列)

Videos can belong to a series. Series carry default voice/resolution/material
source/system prompt, and (later) publishing targets.

- Output layout: `data/output/<series_slug>/<task_uuid>/`
- No series → `data/output/_unsorted/<task_uuid>/`
- Set `SERIES_OUTPUT_FOLDERS=0` to keep a flat layout (series tracked in DB only)
- Manage at the **系列** page; pick a series in the generate dialog

### Book episodes (书籍)

Book/chapter imports (`type=book`) are tuned into ~3–4 minute episodes:

- Each chapter is trimmed to `BOOK_MAX_CHARS` (default `3200`) before the forced
  dense "要点压缩" rewrite. The script targets **~1000–1400 汉字 / 180–240s**
  across **6–12 segments** (keep the no-fluff, fact/mechanism/number rule).
- The generated cover is used as the opening **title card** for
  `BOOK_COVER_HOLD_SECONDS` (default `3.0`) so the video's first frame is the
  cover (better platform thumbnails); narration/subtitles start after it.
- Stills change about every `BOOK_IMAGE_HOLD_SECONDS` (default `4.0`, not the old
  ~10s), so a full episode holds ~45–60 images.
- Material search stays chapter-topic aware (book dictionary + title), images
  first, and prefers higher-resolution Pexels sources (`large2x`/`original`,
  width ≥ ~1280 when the API provides metadata). Synthetic is never used here.
- Stills are **deduplicated per episode** (Pexels photo id + filename), so the
  same image is never reused across segments. Each segment searches with one
  short, **chapter-anchored** query (1–2 anchor terms + up to 2 narrower terms),
  which keeps consecutive images on the same theme instead of jumping topics.
- Consecutive stills are joined with a **crossfade** (`BOOK_SLIDE_TRANSITION_SECONDS`,
  default `0.5s`) that overlaps adjacent holds without extending the total video.

### Multi-language & YouTube growth (English)

The Chinese script stays the **master** (Bilibili, etc.). Any generate request can
ask for an English narration variant for YouTube discoverability:

- `language` (alias `lang`): `zh` (default) or `en`. It is persisted on the task so
  publish can read it.
- For `en`, the worker translates the dense Chinese script segment-by-segment into
  natural spoken English, keeping the segment count/order so visuals/timing do not
  shift, and generates an English **hook title + description + tags**.
- The TTS voice follows the language: `zh` keeps `zh-CN-XiaoxiaoNeural`; `en` uses
  `en-US-AriaNeural` (a swapped-in Chinese voice is replaced automatically).
  Subtitles follow the spoken language.
- YouTube publishes with that title/description/tags and
  `snippet.defaultLanguage`, and adds the video to the bound playlist. Privacy
  defaults to `YOUTUBE_DEFAULT_PRIVACY` (default `unlisted`; smoke-test friendly).

Enable a real generation of both `zh` and `en` variants of the same chapter (each
its own task/playlist is fine). See `apps/worker/README.md` for the exact curl
smoke flow.

### Queue / Worker

- `QUEUE_BACKEND=auto` (default): use Redis if `REDIS_URL` set, otherwise run
  inline in the API process.
- `QUEUE_BACKEND=db`: persist jobs to `generation_jobs` and process them with
  `python -m src.worker`.
- `REDIS_URL=redis://localhost:6379/0` to use Redis.

### Scheduler

- `ENABLE_SCHEDULER=1` starts APScheduler with the API.
- `SCHEDULER_AUTO_PUBLISH=0` (default) — when on, scheduled runs publish to all
  enabled publisher accounts.

### Synthetic images (ComfyUI)

**Off by default** — ComfyUI + SD3.5 can use 10GB+ RAM and has frozen laptops.

- `ENABLE_SYNTHETIC=1` to opt in
- `COMFYUI_URL` (default `http://127.0.0.1:8188`)
- `SYNTHETIC_MIN_FREE_GB` (default 12), `SYNTHETIC_MAX_IMAGES` (default 1)
- Model is currently `sd3.5_large_turbo.safetensors`

### Synthetic video / animation (ComfyUI)

**Off by default** — video models are multi-GB and a clip can take minutes.
Slow generation is fine: it runs in the queue worker with progress + cancel.

- `ENABLE_SYNTHETIC_VIDEO=1` to opt in; select material source **AI 动画**
- `SYNTHETIC_VIDEO_WORKFLOW` — path to an exported ComfyUI "workflow (API
  format)" JSON. Placeholders: `{{prompt}} {{negative}} {{width}} {{height}}
  {{length}} {{fps}} {{seed}} {{image}}`. Empty → built-in LTX-Video t2v.
- `SYNTHETIC_VIDEO_MIN_FREE_GB` (default 16), `_MAX_CLIPS` (2), `_TIMEOUT_S` (900),
  `_FRAMES` (97 ≈ 4s), `_FPS` (25), `_WIDTH`/`_HEIGHT`
- Strategy: each script segment generated as a short clip, then composed with
  audio/subtitles. Endpoint: `GET /api/synthetic/video/status`

### Publishing

Publishing is **review-gated by default** (`PUBLISH_REQUIRE_REVIEW=1`): approve a
finished video, then queue it. Jobs are processed by the worker and their
per-platform status + retry are shown in the UI.

- Queue: `POST /api/videos/tasks/{id}/publish`; jobs at `GET /api/publish/jobs`
- Series: configure publish targets and use "发布已审核" to queue all approved
  videos in a series (`/api/series/{id}/targets`, `/api/series/{id}/publish-approved`)
- **YouTube**: store an OAuth JSON with `refresh_token` in the account's
  credentials. Publishing fails loudly if credentials are missing.
- **Douyin / Xiaohongshu**: add the account, then click **登录** to open a browser
  and capture cookies. Folder lists are real; collection/album assignment is
  best-effort.

## License

MIT
