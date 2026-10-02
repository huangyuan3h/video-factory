# VF agent contract (machine-readable)

Single source for automation: shapes of `state/episodes.json` and every
`vf --json` output. `AGENTS.md` is the human entry; THIS file is the parse spec.
Validated by `apps/worker/tests/test_phase4_contract.py` (stdlib only, no network).

## 1. Global `vf --json` envelope

- The FINAL stdout line is always ONE JSON object (preceding lines are human logs).
- It ALWAYS carries `error_code` (see §3). `ok: true` ⟺ `error_code == "E_OK"`
  (except `qa`, which ALSO carries `pass`; `pass` and `ok` agree).
- Exit codes: `0` ok · `1` fail (incl. QA FAIL) · `2` usage · `3` blocked.
- Every error payload carries `hint`: the exact next command to run.
- `vf explain <CODE>` prints cause + fix + next for any code.

## 2. `state/episodes.json`

Top level: `{meta, episodes}`. `episodes` maps `"epN"` → entry (ep1–ep25 today).

```jsonc
{
  "meta": {
    "generated_at": "2026-10-02T05:54:11",   // string, required
    "sources": ["..."],                      // string[], read-only inputs (never edited by migrate)
    "note": "...",                           // string
    "default_resolution": "2560x1440 CRF17 (1440p)"  // string, MUST stay 1440p
  },
  "episodes": {
    "ep1": {
      "ep": "ep1",            // "epN", required, key == ep
      "id": "ep1_macd_golden_cross",  // string|null
      "topic": "MACD 金叉",   // string
      "title": "…｜什么指标不赚钱 第1集",  // string
      "research_commit": null, // string|null
      "script_sha": null,     // string|null
      "video_path": "/abs/path/output.mp4",  // string|null (gitignored data/)
      "qa": "",               // string: contains PASS / FAIL / "" (unknown)
      "status": "published",  // "published" | "ready" | "stopped"
      "narrative": "plain直讲…",  // string (rotation device; never repeat last 5)
      "youtube": {"id": null, "url": null, "status": null},
      "bili": {"bvid": "BV…", "url": "https://…", "status": "已通过"},
      "zhihu": {"url": "https://…", "published": true, "queued": false, "queue_title": null},
      "toutiao": {"status": "draft-only"}
    }
  }
}
```

Rules:

- Old ledgers (`series_done.log`, `queue.json`, `published.json`, `bili_ready.json`,
  `series_topics.md`) are READ-ONLY inputs; daily routines still own them.
- `vf status --check-drift` diffs the new ledger vs old ledgers → `drifts[]`.
- `ep13`-style `stopped` entries: `video_path: null`, QA text explains why.
- `vf publish` fail-closed reads `qa`: any `FAIL` (except ep12 video-PASS special case)
  refuses unless `--force --force-reason` (logged to `state/force_log.jsonl`).

JSON Schema (draft 2020-12, abridged — full validation in test):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["meta", "episodes"],
  "properties": {
    "meta": {"type": "object", "required": ["generated_at", "sources"]},
    "episodes": {
      "type": "object",
      "patternProperties": {
        "^ep[0-9]+$": {
          "type": "object",
          "required": ["ep", "title", "status", "qa", "youtube", "bili", "zhihu", "toutiao"],
          "properties": {
            "ep": {"type": "string", "pattern": "^ep[0-9]+$"},
            "status": {"enum": ["published", "ready", "stopped"]},
            "qa": {"type": "string"}
          }
        }
      }
    }
  }
}
```

## 3. Error codes (`src/services/error_codes.py`)

`E_OK E_USAGE E_CREDENTIALS E_BACKEND_OVERLOAD E_PNG_READ E_QA_FAIL E_MEMORY
E_BLOCKED E_NOT_FOUND E_LEDGER` — `vf explain <CODE>` prints cause/fix/next.

## 4. Per-command `--json` shapes (final line)

- `status`: `{ok, error_code, count, episodes{...}}` · `--ep`: `{ok, error_code, ep, entry, video_exists}` · `--check-drift`: `{ok, error_code, drifts[{ep,field,ledger,old,note}], count}` (exit 1 when drifted)
- `new-ep`: `{ok, error_code, ep, type, topic, resolution, resume, dry_run, out_dir}` (+`skipped/reason` on resume-hit) · `--list-types`: `{ok, error_code, types[]}`
- `render`: `{ok, error_code, ep, resolution, resume, exit}` · `--dry-run`: `{ok, error_code, ep, resolution, dry_run:true, dir, qa}`
- `qa`: `{pass, ok, error_code, ep, mode:"full"|"ledger", dir?, log?|qa?}`
- `publish` (dry-run): `{ok, error_code, ep, to, privacy, draft_only, dry_run:true, resume}` · `--check-funnel`: `{ok, error_code, ep, to, funnel_ok, missing[], present[], detail}`
- `explain [CODE]`: `{ok, error_code, code, cause, fix, next}` (no arg: `{ok, error_code, codes[]}`)
- `check`: `{ok, error_code, steps:{lint:{ok}, typecheck:{ok,how}, tests:{ok,passed}, doctor:{ok}}}` (exit 1 unless all pass)
- `doctor`: `{ok, error_code, free_gb, disk_ok, memory{}, ffmpeg{}, whisper{}, credentials{booleans only}, proxy{}}` (exit 3 when disk <5GB; never prints secrets)
