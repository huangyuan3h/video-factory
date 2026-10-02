# AGENT_QUICKSTART — Video Factory in 5 minutes

VF builds indicator chart videos (1440p) + publishes. Single entry: `vf`.
Full spec: `AGENTS.md`, `docs/agent-contract.md`, `docs/indicator-episode-runbook.md`.

## Layout
```
scripts/vf                 # only entrypoint (all jobs go through it)
apps/worker/src/           # pipeline: research/script/review/tts/materials/render/qa/publish
config/series.d/*.json     # declarative series (no core edits)
state/episodes.json        # single ledger (built by scripts/migrate_ledger.py)
data/output/<series>/<ep>/ # videos; only vf writes here
docs/ legacy/              # runbooks, research, retired scripts
```

## 10 commands (every `--help` has examples; `--json` last line has `error_code`)
1. `./scripts/vf status --json`
2. `./scripts/vf new-ep --n 26 --topic "地量见底" --script-only --dry-run --json`
3. `./scripts/vf new-ep --n 26 --topic "地量见底" --script-only --out-dir /tmp/ep26 --json`
4. `./scripts/vf render --ep 26 --approved-script /tmp/ep26 --dry-run --json`
5. `./scripts/vf qa --dir /tmp/ep26 --json`
6. `./scripts/vf publish --ep 26 --to youtube --dry-run --json`
7. `./scripts/vf publish --ep 26 --to youtube --check-funnel --json`
8. `./scripts/vf status --check-drift --json`
9. `./scripts/vf explain E_QA_FAIL`
10. `./scripts/vf check --json && ./scripts/vf doctor --json`

New-agent order: 1 -> 2 -> 3 -> 5 -> 6 -> 10. Resume: re-run same cmd + `--resume`.
Types: `./scripts/vf new-ep --list-types --json` (book/daily_news/general/indicator/news).

## State files
- `state/episodes.json`: `{meta, episodes{"epN":{ep,title,status,qa,narrative,youtube,bili,zhihu,toutiao}}}`.
- Task dir: `status.json` + `script.json`/`script.md` + `.vf_checkpoint.json`.
- Old ledgers (`series_done.log`/`queue.json`/`published.json`/`series_topics.md`/`narrative_devices.md`) live in MAIN checkout, read-only.
- `state/force_log.jsonl`: `--force` overrides. Never hand-edit `data/output`.

## Error codes (`vf explain <CODE>`)
- Final stdout line always JSON with `error_code`; `ok:true` <=> `E_OK`.
- Exit: 0 ok / 1 fail / 2 usage / 3 blocked. Every error has `hint` = next command.
- Codes: `E_OK E_USAGE E_CREDENTIALS E_BACKEND_OVERLOAD E_PNG_READ E_QA_FAIL E_MEMORY E_BLOCKED E_NOT_FOUND E_LEDGER`.
- Ex: `./scripts/vf explain E_QA_FAIL` -> cause+fix+next. No-arg lists all.

## Add series / platform (no core edits)
- Series: 1. drop `config/series.d/<name>.json` (`name,content_type,steps`; see `config/series.d/README.md`); 2. optional `@series("<name>")` builder in `src/services/series_registry.py`; 3. QA gate next to `scripts/indicator_qa.py`; 4. test fixture PASS + one FAIL. Check: `vf new-ep --n 99 --topic "x" --type <name> --script-only --dry-run --json`.
- Platform: 1. subclass `BasePublisher` in `src/publishers/<name>.py` (pure `parse_*/build_*/validate_*/is_already_published/should_refuse_publish`, no Playwright); 2. Playwright only in `async def` browser methods; 3. `register_publisher("<name>",Cls)` in `src/publishers/__init__.py`; 4. pure-logic test. Check: `vf publish --ep 25 --to <name> --dry-run --json`.

## Hard rules / never-do
- Unattended: never ask; emit JSON, exit 3 when blocked. Pen name `躺平的老黄`; never real name.
- 1440p only: `2560x1440 CRF17`, charts `2560x1267`, static image <=12s, BGM halved.
- Narrative: new device per ep, never repeat last 5. No jargon (seed/种子/params/dates FAIL QA). No repeated sentences. Per-group 12-stock grids, cue-timed. Cards never overflow. QA fail-closed (`--force --force-reason` only, logged).
- Publish safe: YT `unlisted` (public needs `--force`), others `draft-only`; dry-run unless `--execute`. Funnel gate: `vf publish --ep N --to youtube --check-funnel`.
- Memory: one heavy job at a time, <=2 workers, Whisper `small` only. Check `memory_pressure`+`pgrep`; kill only own procs. Light tests only (no render/TTS/Whisper/upload).
- Never: touch `~/Projects/karios-desktop`, others' procs, `data/output` by hand; switch/reset/stash `~/Projects/video-factory` (`feat/ep21-seed-fix`) or zhihu checkout; open `.png/.jpg` with read tool (`E_PNG_READ`); commit secrets (`.env*/*.pem/*.key/cookies.json/token*.json`); force-push or push `main` (merge `--no-ff`, run `vf check`).
- Money leads: per-trade positive after fees OR beats random -> append `~/Projects/wealth-ideas/profit-leads.md`.
