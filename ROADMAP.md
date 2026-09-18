# Video Factory — Roadmap / TODO

Status legend: `[x]` done, `[~]` partial / needs hardening, `[ ]` not started.

## Core pipeline

- [x] Text content → AI script → Edge-TTS → subtitles → cover → MoviePy compose → `output.mp4`
- [x] Per-segment material timeline (keywords → duration-aware clips)
- [x] Material sources: Pexels, Pixabay, local library
- [x] Source value normalization (`pexels`/`pixabay` are treated as `online`; `both` = all)
- [x] LLM rewrite step (optional, with fallback provider)

## Synthetic images (ComfyUI)

- [x] SD3.5-turbo workflow via ComfyUI HTTP API
- [x] **Opt-in by default** (`ENABLE_SYNTHETIC=0`) — never runs unless enabled
- [x] Memory gate (`SYNTHETIC_MIN_FREE_GB`, default 12GB) + OOM circuit breaker
- [x] Resolution hard-clamp (max 1024x576) + single image per call + cooldown
- [~] Model is hard-coded to `sd3.5_large_turbo.safetensors`; make configurable
- [ ] Verify against a real ComfyUI instance on a high-memory machine

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
- [ ] Per-task options (voice, resolution, publish targets) on the `Task` model
- [ ] Run history surfaced in the UI

## Publishing

- [x] Publisher registry + `PublisherAccount` CRUD
- [x] Auto-publish hook after generation (`publish_to`)
- [x] YouTube via Data API v3 (playlists as folders)
- [~] YouTube uploads are **mocked as successful** when no credentials are configured
- [~] Douyin: selectors are best-effort; collection handling is a UI stub
- [~] Xiaohongshu: selectors are best-effort; album handling is a UI stub
- [ ] Real folder/collection listing for Douyin / Xiaohongshu
- [ ] Cookie capture UI + session refresh
- [ ] Bilibili / Kuaishou publishers

## Frontend

- [x] Dashboard, Tasks, Videos, Assets, Logs, Settings, Publishers pages
- [x] Generate modal: voice, rate, music, resolution, rewrite, subtitles, publish targets
- [x] Background source selector incl. `AI 合成 (ComfyUI)` and `自动`
- [ ] Real-time progress via SSE/WebSocket (currently polling)
- [ ] Surface ComfyUI `enabled`/`available` state and disable when off

## Quality / ops

- [x] Worker test suite passing at the enforced 64% coverage threshold
- [x] Docker Compose with Redis + optional GPU ComfyUI profile
- [ ] CI pipeline (lint + tests) on push
- [ ] Fix legacy frontend TS errors in `components/ui/*` and `hooks/use-toast.ts`
- [ ] Structured logging / metrics

## Known pre-existing test failures

- `tests/test_videos_route_functions.py::test_video_generate_request_defaults`
- `tests/test_videos_route_functions.py::test_get_active_ai_client_none`
- `tests/test_videos_helpers.py::test_get_active_ai_client_with_setting`

These predate the queue/scheduler work and are unrelated to it.
