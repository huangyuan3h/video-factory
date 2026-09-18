# Video Factory — Roadmap / Plan

Status legend: `[x]` done, `[~]` partial / needs hardening, `[ ]` not started.

Guiding principle: **生成慢没关系** — long jobs belong in the queue/worker, not
the API request. Slow generation is acceptable; we optimize for correctness,
recoverability, and a UI that mirrors the real pipeline.

---

## 0. Current state (done)

### Core pipeline
- [x] Text → AI script → Edge-TTS → subtitles → cover → MoviePy → `output.mp4`
- [x] Per-segment material timeline (keywords → duration-aware clips)
- [x] Materials: Pexels, Pixabay, local library (+ normalized source aliases)
- [x] Optional LLM rewrite with fallback provider

### Queue / worker / scheduler
- [x] Redis queue + DB fallback (`generation_jobs`), independent worker process
- [x] Job status tracking (pending → processing → completed/failed)
- [x] Scheduler wired end-to-end (source fetch → video generation), manual trigger
- [x] Optional auto-publish for scheduled runs (default off)

### Synthetic (ComfyUI)
- [x] SD3.5-turbo image workflow via ComfyUI HTTP API
- [x] Opt-in (`ENABLE_SYNTHETIC=0`), 12GB free-memory gate, OOM breaker, single-image cap

### Publishing
- [x] Registry + `PublisherAccount` CRUD
- [x] YouTube Data API v3 (playlists as folders) — fails loudly without credentials
- [x] Browser login / cookie capture (`/api/publishers/{id}/login`)
- [x] Douyin / Xiaohongshu verify publish result; real (empty) folder lists
- [x] Real folder create/list endpoints
- [~] Douyin/XHS selectors best-effort; collection/album assignment needs real API

---

## 1. Domain model additions

Introduce a **Series** (系列/文件夹) as the unit that groups a family of videos
and drives output layout + publishing grouping.

### `Series`
| field | type | notes |
|-------|------|-------|
| id | str(32) pk | |
| name | str(255) | display name |
| slug | str(128) unique | filesystem-safe, auto from name |
| description | text | |
| cover_path | str(512) | optional |
| system_prompt | text | default script prompt for the series |
| default_voice / default_voice_rate | str | |
| default_resolution_width / height | int | |
| default_background_source / _music | str | |
| created_at / updated_at | datetime | |

### `SeriesPublishTarget` (per series, per platform)
| field | notes |
|-------|-------|
| id, series_id (FK), platform | |
| account_id (FK PublisherAccount) | which account to use |
| folder_id / folder_name | target playlist/collection/album |
| enabled | |

### Linking existing records
- `GenerationJob.series_id` (nullable)
- `Run.series_id` (nullable) — scheduled runs
- in-memory `video_tasks[task_id]["series_id"]` + `status.json.series_id`

### Output layout
```
data/output/
  <series_slug>/
    <task_uuid>/
      script.json  segment_*.mp3  subtitles.ass  cover.png  output.mp4  status.json
  _unsorted/            # videos generated without a series (backward compatible)
```
`settings.output_dir` stays the root; `task_dir` = root / (slug or `_unsorted`) / uuid.

---

## 2. Milestones

### M1 — Series foundation (backend) — recommended next
- [x] `Series` + `SeriesPublishTarget` models; lightweight `ALTER TABLE` migration in `init_db`
- [x] `/api/series` CRUD (+ slug generation incl. CJK, uniqueness)
- [x] `VideoGenerateRequest.series_id` / `seriesId`; resolve series → slug → task dir
- [x] `GET /api/videos/tasks?series_id=...` filter
- [x] persist `series_id` on `GenerationJob`, `Run`, `status.json`
- [x] `SERIES_OUTPUT_FOLDERS` switch (1 = per-series folders, 0 = flat)
- **Acceptance**: generation with/without a series lands in the right folder;
  unknown series → 404; no-series flow unchanged. ✅

### M2 — Series workspace (UI)
- [x] Sidebar "系列" entry → `/series` list, `/series/[id]` detail
- [x] Create/edit series (name, description, defaults, cover path, system prompt)
- [x] Generate modal: series picker + inline "新建系列"
- [x] Videos page: filter by series + series badge
- [x] Series detail: all its videos with live status, play/download/delete
- [x] Apply series defaults (voice/resolution/material/prompt) when selected
- [ ] Series detail publish actions (moved to M5)
- **Acceptance**: can create a series, generate into it, see all its videos grouped. ✅

### M3 — Long-running job plumbing
- [x] `GenerationJob.progress / current_step / message / cancel_requested`; worker mirrors `status.json`
- [x] `POST /api/videos/tasks/{id}/cancel` (flag file + DB flag); worker checks cancel between steps
- [x] SSE `GET /api/videos/events` streaming status updates; UI consumes via EventSource
- [x] `POST /api/videos/tasks/{id}/retry` (re-runs from stored payload)
- [x] `_enrich_task` reads status/progress/message from `status.json` (correct across processes)
- [x] UI: live progress, cancel button, retry button (Videos + Series detail)
- [ ] Retry policy / exponential backoff + dead-letter
- **Acceptance**: a long job shows live progress and can be cancelled; failed jobs can be retried. ✅

### M4 — ComfyUI animation mode (slow, opt-in)
Separate from images; long jobs are fine.
- [x] `ENABLE_SYNTHETIC_VIDEO=0` (default off), higher memory gate (16GB), per-clip timeout
- [x] `services/synthetic_video_service.py`: built-in LTX-Video t2v workflow **and**
      configurable exported workflow JSON with placeholders
- [x] image-to-video support (uploads the still to ComfyUI when `{{image}}` present)
- [x] material source value `synthetic_video`; UI option "AI 动画 (ComfyUI 视频, 很慢/高显存)"
- [x] circuit breaker + no auto-run under `auto`/`both` (explicit selection only)
- [x] endpoints `GET /api/synthetic/video/status`, `POST /api/synthetic/video/generate`
- [ ] Verify per-segment still → i2v → compose on a real high-VRAM host
- [ ] Presets for Wan 2.x / HunyuanVideo 1.5 workflows
- **Acceptance**: on a capable host, a segment produces a short animated clip that
  composes into the final video; disabled by default and safe on laptops. (code path ✅, real-host verification pending)

### M5 — Review & publish pipeline
- [ ] Task/Series "review" state before publishing (preview video/cover/subtitles)
- [ ] Publish queue + per-target status + retry; screenshots on failure
- [ ] Series publish targets drive auto-publish (`publish_to` = series targets)
- [ ] "Publish all approved videos in series X" one-click action
- [ ] Optional scheduled series publishing
- **Acceptance**: nothing publishes without review; per-platform results are visible and retryable.

### M6 — Process-centric UI (最终目标)
- [ ] Dashboard = pipeline board: counts by stage
      (来源 → 待生成 → 生成中 → 待审核 → 已发布 / 失败)
- [ ] Series-centric navigation as the primary mental model
- [ ] Real-time updates via SSE (no polling)
- [ ] Unified task/run detail drawer with logs, files, actions
- [ ] Settings page: capability panel (ComfyUI on/off, providers configured, accounts)
- [ ] Fix frontend TS/Tailwind setup (`react` types, `components/ui/*`, `hooks/use-toast`)
- **Acceptance**: the whole flow is manageable from one place and reflects live state.

---

## 3. Engineering tracks (cross-cutting)

- **Reliability**: idempotent job claim, retries, dead-letter, resume-after-restart
- **Observability**: structured logs, per-step timing, `/api/health` details, failure screenshots
- **Security**: encrypt stored cookies/OAuth tokens at rest; API token already enforced on mutations
- **Performance**: cache material search results; avoid re-downloading assets
- **Testing/CI**: keep worker coverage ≥64%, add GitHub Actions (lint + tests), frontend tests for series UI
- **Docs**: keep this file and README in sync as milestones land

---

## 4. ComfyUI animation — feasibility (2026)

Yes, ComfyUI generates multi-second animation; models are large, which is fine
given we accept slow jobs on the worker.

| Approach | Clip length | Notes |
|----------|-------------|-------|
| AnimateDiff | ~2–16 s | Prompt→animation; motion modules + SD base |
| SVD | few s | Image→video only |
| LTX-Video / LTX-2.x | few s | Fast; i2v & t2v; audio in 2.x — **first integration** |
| HunyuanVideo 1.5 (8.3B) | 5–10 s | ~24GB VRAM, native 720p, t2v + i2v |
| Wan 2.1 / 2.7 / 3.0 | up to ~30 s (3.0) | Open weights; large VRAM |

Plan: introduce a distinct opt-in video mode (M4), run it in the worker with
progress/cancel (M3), and keep images as the default fast path.

---

## 5. Known pre-existing test failures

- `tests/test_videos_route_functions.py::test_video_generate_request_defaults`
- `tests/test_videos_route_functions.py::test_get_active_ai_client_none`
- `tests/test_videos_helpers.py::TestVideosHelperFunctions::test_get_active_ai_client_with_setting`

Predate the queue/scheduler work; unrelated. Fix as part of M6 cleanup.
