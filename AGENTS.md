# AGENTS.md — Video Factory (single entrypoint, safe defaults)

Model: `opencode-go/muse-spark-1.3-contributor`, variant `xhigh`.
Unattended: never ask questions; use safe defaults below.

## 1. One command: `vf` (scripts/vf)
- `vf status [--ep 25] [--json] [--resume]`
  reads `state/episodes.json` (ep1-25). Old ledgers stay read-only.
- `vf new-ep --n 26 --topic "…" [--manifest DIR] [--script-only]`
  thin wrapper over `cli_runner.indicator_main`.
- `vf render --ep 26 --approved-script DIR`
  cue-synced render; fail-closed on QA.
- `vf qa --ep 26 | --dir DIR [--json]`
  7 gates: overflow / repeat / transition / jargon / beats / sync / encode.
  Exit 0 PASS, 1 FAIL (prints offenders + JSON `{"pass":…}`).
- `vf publish --ep 26 --to youtube|bili|zhihu|toutiao`
  dry-run unless `--execute`.
  YouTube default `unlisted` (public needs `--force`).
  Toutiao/Zhihu/Bili default `draft-only` (never publish/首发).
- Everywhere: `--json` means final stdout line is single JSON object.
- Everywhere: `--resume` means skip finished steps via `status.json` + hashes.
- Exit codes: 0 ok / 1 fail / 2 usage / 3 blocked (memory/credentials/missing).
- Default resolution `2560x1440 CRF17` (1440p). Do NOT default to 1080p.
- Script-only from one paragraph:
  `vf new-ep --n 26 --topic "…" --script-only --json`
  then `vf qa --ep 26 --json`.

## 2. Memory / CPU (16GB Mac, serial heavy jobs only)
- One heavy job at a time: `python render`, `ffmpeg`, `whisper`.
- Before starting: check `memory_pressure` + `pgrep python|ffmpeg|whisper`.
- Never kill processes you did not start.
- ≤2 workers max.
- Whisper `small` only (never large).
- Proxy `127.0.0.1:7890` for YouTube/external APIs when set.
- `vf` preflight refuses when free disk <5GB (exit 3).
- Synthetic guards: `min_free_gb` 12/16, max 1 image / 2 clips.
- Light tests only by default: no render, no TTS, no upload, no publish, no Whisper.

## 3. Never touch / never open
- Never touch `~/Projects/karios-desktop` (read-only reference).
- Never touch others' processes or `data/output` by hand (only via `vf`).
- Daily routines run on `feat/ep21-seed-fix` in `~/Projects/video-factory`
  (YouTube 9:55/21:55). Do NOT switch/reset/stash that checkout.
- Never touch `~/Projects/video-factory-zhihu` worktree
  (Zhihu 20:02 / Bili / Toutiao publishers run from it).
- Do all work in a separate worktree/branch (e.g. `chore/phase2-mainline`).
- Never open `.png/.jpg` with the file-read tool.
  It crashes the session (`Invalid upload request`).
  Key-frames only via Python/OCR text checks.
- No secrets in commits: `.env*`, `*.pem`, `*.key`,
  `cookies.json`, `token*.json` are gitignored. Never `git add` them.

## 4. Quality defaults (do not regress)
- Keep 1440p: `2560x1440 CRF17`, charts native `2560x1267`, no upscaling.
- Narrative rotation: each ep uses a new device; never repeat last 5 eps.
  Check `state/episodes.json` + `narrative_devices.md` first.
- No jargon in narration/key_point/subtitles:
  seed/random_state/param-names/file-extensions/dates all FAIL QA.
- Per-group thumbnail grids (not number cards), cue-timed beat sync.
- Static single image ≤12s unless animated (`motion != "none"`).
- Lockstep publishing: YT unlisted→public per runbook §7,
  Bili drafts, Zhihu queue, Toutiao draft-only.
- Every upload needs funnel link + playlist CTA + disclaimer
  (`vf publish --check-funnel` pattern; history has zero-http descriptions).
- QA fail-closed: `render`/`publish` refuse on FAIL unless `--force` + reason.

## 5. State / docs / git
- Single ledger: `state/episodes.json`
  built by `scripts/migrate_ledger.py` (reads only, never writes old ledgers).
- Old ledgers (`queue.json`, `published.json`, `bili_ready.json`,
  `series_done.log`, `series_topics.md`) stay for daily routines.
- Deep reference: `docs/indicator-episode-runbook.md`
  (§§0.3/0.6 no-touch + memory rules kept verbatim).
- Research docs tracked under `docs/` (bilibili/toutiao/zhihu/daily-news).
- No force-push, never push `main`. Merge with `--no-ff`, run light `pytest`.
- New agent checklist: `vf status --json` → `vf new-ep --script-only`
  → `vf qa --json` → `vf publish --dry-run`.
  If blocked: emit JSON, exit 3, stop. Never guess, never publish for real.
