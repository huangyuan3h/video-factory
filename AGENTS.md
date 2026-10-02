# AGENTS.md — Video Factory (single entrypoint, safe defaults)

> New agent? Start here: [docs/AGENT_QUICKSTART.md](docs/AGENT_QUICKSTART.md) (5-min, 10 commands).

Model: `opencode-go/muse-spark-1.3-contributor`, variant `xhigh`.
Unattended: never ask questions; use safe defaults below.
Owner pen name: 「躺平的老黄」. NEVER write his real name anywhere (code, docs, titles, descriptions).

## 0. First 5 minutes (script-only dry run, no TTS/render/publish)

```bash
./scripts/vf status --json                                  # ledger ep1-25
./scripts/vf new-ep --n 26 --topic "…" --script-only --dry-run --json   # intent only, writes nothing
./scripts/vf new-ep --n 26 --topic "…" --script-only --out-dir /tmp/ep26 --json
./scripts/vf qa --dir /tmp/ep26 --json                      # must PASS
./scripts/vf publish --ep 26 --to youtube --dry-run --json  # never real without --execute
./scripts/vf check --json && ./scripts/vf doctor --json     # repo gate + env health
```

Stuck? Every error names the next command (`hint` in JSON). Or: `vf explain <E_CODE>`.

## 1. `vf` jobs (every subcommand: `--help` has examples; `--json` final line carries `error_code`)

- New episode: `vf new-ep --n 26 --topic "…" --script-only --out-dir DIR [--resume]`
  (`--type` defaults `indicator`; `vf new-ep --list-types` lists all. Full non-indicator
  generation: `apps/worker generate_episode.py --type <t> --help`.)
- Re-render one: `vf render --ep 26 --approved-script DIR [--dry-run] [--resume]`
  (fail-closed on QA; override: `--force --force-reason "…"`, logged to `state/force_log.jsonl`).
- QA: `vf qa --ep 26 | --dir DIR` (7 gates: overflow/repeat/transition/jargon/beats/sync/encode).
- Publish per platform (dry-run unless `--execute`; YT `unlisted`, Bili/Zhihu/Toutiao `draft-only`):
  `vf publish --ep 26 --to youtube|bili|zhihu|toutiao [--execute]`
  Public YT needs `--force`. Funnel gate: `vf publish --ep 26 --to youtube --check-funnel`
  (needs `VF_FUNNEL_URL` set — canonical URL still TBD, ask owner).
- Resume after crash: re-run the same command with `--resume` (checkpoint via `status.json`+hashes;
  publishers dedupe drafts via `is_already_published`/`should_refuse_publish`). Never redo finished steps by hand.
- Check drift: `vf status --check-drift --json` (new ledger vs old read-only ledgers; exit 1 + `drifts[]` when diffed).
- Gate + health: `vf check` (lint+type/tests+doctor, read-only) · `vf doctor` (disk/mem/ffmpeg/whisper/creds-booleans/proxy; exit 3 if disk <5GB).
- Exit codes `0` ok / `1` fail / `2` usage / `3` blocked. Machine spec: `docs/agent-contract.md`.

## 2. State (where things live)

- Single ledger: `state/episodes.json` (built by `scripts/migrate_ledger.py`, read-only on old ledgers).
  Old ledgers (`series_done.log`, `queue.json`, `published.json`, `bili_ready.json`, `series_topics.md`,
  `narrative_devices.md`) live in the MAIN checkout and stay the routines' source of truth — never edit them here.
- Task dirs: `status.json` + `script.json`/`script.md` + `.vf_checkpoint.json`. `data/output` only via `vf`.
- Retired scripts move to `legacy/` with a README row (never delete). Heavy manual harness: `scripts/verify/verify_e2e.py`.

## 3. Memory / CPU (16GB Mac, serial heavy jobs only)

- One heavy job at a time (`render`, `ffmpeg`, `whisper`); check `memory_pressure` + `pgrep` first.
- ≤2 workers max. Whisper `small` only. Proxy `127.0.0.1:7890` for YouTube/external APIs.
- Never kill processes you did not start. Light tests only: no render/TTS/upload/publish/Whisper.

## 4. Never do

- Never touch `~/Projects/karios-desktop` (read-only), others' processes, or `data/output` by hand.
- Daily routines run on `feat/ep21-seed-fix` in `~/Projects/video-factory` (YT 9:55/21:55) and in
  `~/Projects/video-factory-zhihu` (Zhihu 20:02/Bili/Toutiao). NEVER switch/reset/stash those checkouts.
- Never open `.png/.jpg` with the file-read tool (crashes session: `Invalid upload request`, `E_PNG_READ`).
  Key-frames only via Python/OCR text checks.
- No secrets in commits (`.env*`, `*.pem`, `*.key`, `cookies.json`, `token*.json` are gitignored).
  Footgun: importing `moviepy` auto-loads the MAIN checkout's real `.env` (its `find_dotenv` walks up
  from the venv when no tracer runs). Tests are hermetic via `conftest._hermetic_env`; never rely on
  ambient keys, never print them (`vf doctor` reports booleans only).
- No force-push, never push `main`. Merge `--no-ff`, run `vf check`.

## 5. Quality bars (do not regress)

- 1440p: `2560x1440 CRF17`, charts native `2560x1267`, no upscaling. Static single image ≤12s unless animated.
- Narrative rotation: new device per ep, never repeat last 5 (check ledger `narrative` + `narrative_devices.md`).
- No jargon in narration/key_point/subtitles (seed/种子/param-names/file-extensions/dates FAIL QA).
- Per-group thumbnail grids (not number cards), cue-timed beat sync. No repeated sentences; bridges must differ.
- Lockstep: YT unlisted→public per runbook §7, Bili drafts, Zhihu queue, Toutiao draft-only.
  Every upload: funnel link + playlist CTA + disclaimer + 「躺平的老黄」 byline (`vf publish --check-funnel`).
- QA fail-closed: `render`/`publish` refuse on FAIL unless `--force` + reason.

## 6. Extend: new series / content type / platform (no core edits)

- New series type: 1. add `config/series.d/<name>.json` (see `config/series.d/README.md` for the 6-line example);
  2. optional request builder via `@series("<name>")` in `src/services/series_registry.py`;
  3. QA gate next to `scripts/indicator_qa.py`; 4. test (fixture script + mocked render, PASS + one FAIL case).
  Check: `vf new-ep --n 99 --topic "…" --type <name> --script-only --dry-run --json` works immediately after step 1
  (JSON configs auto-load on import; `--n`/`--topic` are required even for dry-run).
- New platform: 1. subclass `BasePublisher` in `src/publishers/<name>.py` — pure helpers first
  (`parse_*`/`build_*_payload`/`validate_*`/`is_already_published`/`should_refuse_publish`, sync + unit-tested,
  no Playwright); 2. Playwright only in `async def` browser methods; 3. `register_publisher("<name>", Cls)`
  in `src/publishers/__init__.py`; 4. pure-logic test (no network/browser).
  Tiny check: `get_publisher("<name>").platform_name` + `vf publish --ep 25 --to <name> --dry-run --json`.
- Pipeline steps every series shares: `research/script/review/tts/materials/render/qa/publish`
  (`series_registry.steps_for`). `vf new-ep --script-only` stops after `review`.

## 7. Money-lead rule (backtest screening)

- Every backtest screening MUST append money leads (per-trade positive after fees OR clearly beats random)
  to `~/Projects/wealth-ideas/profit-leads.md` (date, indicator, numbers, source ep, next validation).
  Append only, never rewrite history. Format follows the existing table.

Deep docs: runbook `docs/indicator-episode-runbook.md` (§§0.3/0.6 no-touch+memory kept verbatim),
`docs/agent-contract.md` (machine spec), `docs/*-publishing-research.md`, `legacy/README.md`.
New-agent checklist: `status` → `new-ep --script-only` → `qa` → `publish --dry-run`; if blocked: emit JSON, exit 3, stop.
