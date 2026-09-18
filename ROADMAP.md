# Video Factory — Roadmap / TODO

Status legend: `[x]` done, `[~]` partial / needs hardening, `[ ]` not started.

## Core pipeline

- [x] Text content → AI script → Edge-TTS → subtitles → cover → MoviePy compose → `output.mp4`
- [x] Per-segment material timeline (keywords → duration-aware clips)
- [x] Material sources: Pexels, Pixabay, local library
- [x] Source value normalization (`pexels`/`pixabay` are treated as `online`; `both` = all)
- [x] LLM rewrite step (optional, with fallback provider)

## Video series / folders  (核心诉求)

Goal: when generating a video you can assign it to a **series** (a named folder),
so a family of videos lives together — and the series can drive the publishing
folder/playlist/album so distribution stays grouped.

- [ ] `Series` model: `id`, `name`, `description`, `cover`, `created_at`
- [ ] `POST/GET/PUT/DELETE /api/series` CRUD
- [ ] `VideoGenerateRequest.series_id` / `seriesId`; persist series on the task + `Run`
- [ ] Series → publisher folder mapping (`PublisherAccount.folder_id` per platform)
- [ ] Output layout `data/output/<series>/<task>/…` instead of a flat task dir
- [ ] Frontend: series picker (select existing / create new) in the generate modal
- [ ] Frontend: group the Videos page by series; series detail view with all runs
- [ ] Series-level defaults (voice, resolution, publish targets)

## UI / UX overhaul  (对齐核心流程管理)

Goal: the UI should mirror the actual pipeline and let you manage the whole
"source → series → generate → review → publish" flow, not just fire single jobs.

- [ ] Process-centric dashboard: pipeline stages with counts/status at a glance
- [ ] Series workspace replacing the flat task list as the primary view
- [ ] A guided "new video" flow: source → series → options → generate → review → publish
- [ ] Real-time progress (SSE/WebSocket) instead of polling
- [ ] In-app video preview + subtitle/cover review before publishing
- [ ] One-click "publish this series' new videos" action
- [ ] Consistent empty/loading/error states; fix the broken Tailwind/React type setup
- [ ] Surface capability state: ComfyUI on/off, material providers configured, accounts

## Synthetic images (ComfyUI)

- [x] SD3.5-turbo workflow via ComfyUI HTTP API
- [x] **Opt-in by default** (`ENABLE_SYNTHETIC=0`) — never runs unless enabled
- [x] Memory gate (`SYNTHETIC_MIN_FREE_GB`, default 12GB) + OOM circuit breaker
- [x] Resolution hard-clamp (max 1024x576) + single image per call + cooldown
- [~] Model is hard-coded to `sd3.5_large_turbo.safetensors`; make configurable
- [ ] Verify against a real ComfyUI instance on a high-memory machine

### ComfyUI animation / short video (research, 2026)

Yes — ComfyUI can generate multi-second animation, but the models are large and
not laptop-friendly. Validated against current ComfyUI docs/news:

| Approach | Clip length | Notes |
|----------|-------------|-------|
| AnimateDiff | ~2–16 s | Prompt→animation; needs motion modules + SD base |
| SVD (Stable Video Diffusion) | few s | Image→video only |
| LTX-Video / LTX-2.x | few s | Fast; i2v & t2v templates; audio support in 2.x |
| HunyuanVideo 1.5 (8.3B) | 5–10 s | Needs ~24GB VRAM, 720p, t2v + i2v |
| Wan 2.1 / 2.7 / 3.0 | up to ~30 s (Wan 3.0) | Open weights; large VRAM |

Implications for us:
- Add a separate `ENABLE_SYNTHETIC_VIDEO` (default off) distinct from images.
- Treat animation as **off unless a GPU/high-VRAM host** is present; never run on
  the dev laptop. Reuse the memory gate + circuit breaker, but with a much higher
  free-memory threshold and a single short clip per call.
- Prefer LTX-Video for a first integration (smallest/fastest), then Wan/Hunyuan.
- Track "Dynamic VRAM" improvements in ComfyUI for lower-memory hosts.

## Queue / worker

- [x] Redis-backed queue (`REDIS_URL`)
- [x] DB-backed queue (`generation_jobs` table) when `QUEUE_BACKEND=db`
- [x] Independent worker process (`python -m src.worker`) with thread-offloaded generation
- [x] Job status tracking (pending → processing → completed/failed)
- [ ] Atomic claim / locking for multiple concurrent DB workers
- [ ] Retry policy + dead-letter handling

## Scheduler

- [x] APScheduler started with the API (`ENABLE_SCHEDULER=1`)
- [x] `execute_task` wired end-to-end: source fetch → video generation
- [x] Manual trigger returns the real run id
- [~] Auto-publish for scheduled runs (`SCHEDULER_AUTO_PUBLISH`, default off)
- [ ] Per-task options (voice, resolution, series, publish targets) on the `Task` model
- [ ] Run history surfaced in the UI

## Publishing

- [x] Publisher registry + `PublisherAccount` CRUD
- [x] Auto-publish hook after generation (`publish_to`)
- [x] YouTube via Data API v3 (playlists as folders) — **fails loudly without credentials** (no more fake success)
- [x] Browser login / cookie capture flow: `POST /api/publishers/{id}/login` + "登录" button
- [x] Real folder create/list endpoints (`POST/GET /api/publishers/{id}/folders`)
- [x] Douyin / Xiaohongshu return real (empty) folder lists instead of mock data
- [x] Douyin / Xiaohongshu verify publish success before reporting `success=true`
- [~] Douyin: selectors are best-effort; collection assignment needs real API
- [~] Xiaohongshu: selectors are best-effort; album assignment needs real API
- [ ] Robust selector strategy (data-testid fallbacks, screenshots on failure)
- [ ] Bilibili / Kuaishou publishers

## Frontend

- [x] Dashboard, Tasks, Videos, Assets, Logs, Settings, Publishers pages
- [x] Generate modal: voice, rate, music, resolution, rewrite, subtitles, publish targets
- [x] Background source selector incl. `AI 合成 (ComfyUI)` and `自动`
- [x] Publishers page: real folder create/list, login/cookie capture
- [ ] See "UI / UX overhaul" above (process-centric redesign)

## Quality / ops

- [x] Worker test suite passing at the enforced 64% coverage threshold
- [x] Docker Compose with Redis + optional GPU ComfyUI profile
- [ ] CI pipeline (lint + tests) on push
- [ ] Fix legacy frontend TS errors (`react` types + `components/ui/*`, `hooks/use-toast.ts`)
- [ ] Structured logging / metrics

## Known pre-existing test failures

- `tests/test_videos_route_functions.py::test_video_generate_request_defaults`
- `tests/test_videos_route_functions.py::test_get_active_ai_client_none`
- `tests/test_videos_helpers.py::TestVideosHelperFunctions::test_get_active_ai_client_with_setting`

These predate the queue/scheduler work and are unrelated to it.
