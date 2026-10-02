# `config/series.d/` — declarative series / content-type configs (optional)

Drop a `*.json` file here to declare a new series **without touching core code**.
Files are loaded by `src/services/series_registry.py::load_series_configs`
(and by `vf new-ep --type <name>`, which discovers them automatically).

## Minimal example (`novel.json`)

```json
{
  "name": "novel",
  "content_type": "novel",
  "description": "Future novel-reading series",
  "steps": ["research", "script", "review", "tts", "materials", "render", "qa", "publish"]
}
```

Rules:

- `name` (required): lowercase id, e.g. `novel`. After adding the file,
  `vf new-ep --n 99 --topic "…" --type novel --script-only --dry-run` works immediately
  (script-only dry-run + `vf qa` need no other code; `--n`/`--topic` are required
  even for dry-run; configs auto-load on import).
- `content_type`: pipeline request type (defaults to `name`).
- `steps`: subset of the canonical named steps
  (`research/script/review/tts/materials/render/qa/publish`). Unknown names fail fast.
- Full generation (TTS/render) additionally needs a request `builder`
  (see `series_registry.series` decorator + `cli_runner.build_generic_request`)
  and a QA gate (see `scripts/indicator_qa.py`); both register without core edits.
- Invalid files raise `ValueError` naming the file — fix the file, never the loader.

No live configs are shipped: the five built-in series
(`indicator/general/book/news/daily_news`) are registered in code.
