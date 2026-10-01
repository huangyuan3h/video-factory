# AGENTS.md — Video Factory (single entrypoint, safe defaults)

Model: `opencode-go/muse-spark-1.3-contributor`, variant `xhigh`.
Unattended: never ask questions; use safe defaults below.

## 1. One command: `vf` (scripts/vf)
- `vf status [--ep 25] [--json] [--resume] [--check-drift]`
  reads `state/episodes.json` (ep1-25). Old ledgers stay read-only.
  `--check-drift` compares new ledger vs old read-only ledgers (series_done.log,
  bili_ready.json, zhihu published.json); exit 1 + JSON `drifts` when diffed.
- `vf new-ep --n 26 --topic "…" [--manifest DIR] [--script-only] [--out-dir DIR]`
  thin wrapper over `cli_runner.indicator_main`.
  `--script-only --out-dir DIR` writes deterministic `script.json`/`status.json`
  offline (no LLM/TTS) so `vf qa --dir DIR` can PASS without network.
- `vf render --ep 26 --approved-script DIR [--force --force-reason "…"]`
  cue-synced render; fail-closed on QA (refuse exit 1 unless `--force` + reason,
  reason appended to `state/force_log.jsonl`).
- `vf qa --ep 26 | --dir DIR [--json]`
  7 gates: overflow / repeat / transition / jargon / beats / sync / encode.
  Exit 0 PASS, 1 FAIL (prints offenders + JSON `{"pass":…}`).
- `vf publish --ep 26 --to youtube|bili|zhihu|toutiao [--force --force-reason "…"]`
  dry-run unless `--execute`.
  YouTube default `unlisted` (public needs `--force`).
  Toutiao/Zhihu/Bili default `draft-only` (never publish/首发).
  Fail-closed on ledger QA FAIL (ep13 stopped etc.) unless `--force` + reason (logged).
- `vf doctor [--json]`
  free GB / memory / ffmpeg / whisper / credentials presence (booleans only,
  never prints secrets) / proxy `127.0.0.1:7890`. Exit 3 when disk <5GB.
- Everywhere: `--json` means final stdout line is single JSON object, always
  carries `error_code`: `E_CREDENTIALS` / `E_BACKEND_OVERLOAD` / `E_PNG_READ` /
  `E_QA_FAIL` / `E_MEMORY` (+`E_OK`/`E_USAGE`/`E_BLOCKED`/`E_NOT_FOUND`/`E_LEDGER`).
- Everywhere: `--resume` means skip finished steps via `status.json` + hashes
  (`src/services/checkpoint.py`: `check_resume`/`save_checkpoint`; publishers
  use draft-dedupe `is_already_published`/`should_refuse_publish` everywhere).
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

## 6. Extensibility: add a series type / platform publisher
- New series type (e.g. `type=news` already exists as reference):
  1. Add builder in `apps/worker/src/services/` (pure `build_*_request` + `*_main`
     in `cli_runner.py`, like `build_generic_request`); 2. add QA gate in
     `apps/worker/scripts/` (like `indicator_qa.py`, exit 0/1 + offender list);
  3. wire `vf new-ep --type …` + `vf qa`; 4. add test `tests/test_<type>.py`
     (fixture manifest + mocked TTS/render, assert PASS + one FAIL case, no network).
  Example test shape: `def test_newtype_qa_pass(tmp_path): write script.json…;
  assert qa_main([str(td)]) == 0` (see `tests/test_phase3_qa.py`).
- New platform publisher (e.g. `toutiao.py`/`zhihu.py` are the template):
  1. Subclass `BasePublisher` in `apps/worker/src/publishers/<name>.py`,
     implement pure helpers first (`parse_*_markdown`, `build_*_payload`,
     `validate_*`, `classify_login_state`/`is_logged_in_state`,
     `is_already_published`/`should_refuse_publish` draft-dedupe, all sync +
     unit-tested, no Playwright); 2. keep Playwright only in `async def`
     browser methods (excluded from 80% coverage); 3. register in
     `publishers/__init__.py` (`PUBLISHER_REGISTRY["name"] = Cls`) + `get_publisher`
     + `list_platforms`; 4. add `tests/test_phase3_*_pure.py` (markdown/payload/
     dedupe/login-detection, fixtures/mocks, no network/browser).
  Tiny example: `assert get_publisher("toutiao").platform_name` +
  `parse_toutiao_markdown("# T\\n\\n正文。")["title"] == "T"` (see
  `tests/test_phase3_publishers_pure.py`).

## 7. Money-lead rule (backtest screening)
- Every backtest screening (any series/indicator/news candidate triage) MUST
  append money leads — per-trade positive after fees OR clearly beats random
  (event percentile / combination) — to `~/Projects/wealth-ideas/profit-leads.md`
  (date, indicator, key numbers, source ep, next validation). History stays;
  never rewrite past rows, only append. Format follows the existing table there.
