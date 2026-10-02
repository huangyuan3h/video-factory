# `legacy/` — retired scripts, moved (never deleted) with a reason

Policy (Phase 4): dead code, stale scripts, and duplicate ledgers superseded by
`state/episodes.json` move HERE with a dated note below — never silently deleted,
because daily routines (running on `feat/ep21-seed-fix` in `~/Projects/video-factory`)
may still reference old paths. Check the routine prompt files in the main checkout
(read-only) before moving anything.

## Survey 2026-10-02 (nothing moved yet — all candidates still in use)

| Candidate | Verdict | Evidence |
|---|---|---|
| Duplicate ledgers replaced by `state/episodes.json` | NONE EXIST in this checkout (`state/` holds only `episodes.json`) | `find . -name queue.json/published.json/bili_ready.json/series_done.log` → empty |
| `scripts/verify/verify_e2e.py` (heavy: real edge-tts/PIL/MoviePy/ffmpeg) | KEEP | Referenced by `ROADMAP.md` (49/49 history); it is the manual heavy harness, not superseded. Excluded from the fast suite by design (it is a script, not a pytest test). Run manually when needed. |
| `scripts/youtube_reauth.py` (byte-identical to `apps/worker/scripts/youtube_reauth.py`) | KEEP both | `docs/indicator-episode-runbook.md` + `scripts/youtube_reauth.sh` + `scripts/yt_upload_pending.sh` reference the root copy; the worker copy is the module path. Canonical for agents: root `scripts/youtube_reauth.sh`. |
| `scripts/{bili,toutiao,zhihu}*.sh`, `yt_upload_pending.sh` | KEEP | Publisher wrappers used by the Bili/Zhihu/Toutiao flows; `vf publish --execute` delegates to the same publisher CLIs. |
| `apps/worker/scripts/{run_daily_news_mvp,upload_news_mvp,build_news_upload_meta,fixup_news_materials}.py` | KEEP | Parked daily-news track tooling (news MVP entry + one-off helpers); harmless, referenced by the news design doc thread. Revisit if the news track is cancelled. |
| `apps/worker/scripts/{tts_gap_probe,subtitle_sync_report,generate_episode,indicator_episode}.py` | KEEP | Referenced by runbook/tests; thin wrappers over `cli_runner`. |
| `scripts/dev.sh`, `scripts/tts/` | KEEP | Dev launcher + voice library (`spark-voices.json` is read via `config.spark_voices_file`). |

## How to retire something

1. Confirm no routine prompt in `~/Projects/video-factory/.opencode-runs/` references the path (read-only grep).
2. `git mv <path> legacy/<name>-YYYY-MM-DD.<ext>` and append a row above (date, reason, replacement command).
3. Keep agent docs (`AGENTS.md`, `docs/agent-contract.md`) pointing at the live path.
