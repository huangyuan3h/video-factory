#!/usr/bin/env bash
# Publish the next unpublished item in the Zhihu queue (headless, idempotent).
# Queue: ~/Projects/karios-series-output/zhihu/queue.json (order ep2, ep8, ep11).
# Idempotency: a queue item is skipped when <payload-dir>/published.json has a URL.
# On success: verifies via publisher, prints URL, never opens a browser (--no-open).
# When nothing is left: prints QUEUE EMPTY and exits 0.
# Usage:
#   scripts/zhihu_publish_next.sh [--queue PATH] [--dry-run]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QUEUE_DEFAULT="$HOME/Projects/karios-series-output/zhihu/queue.json"
QUEUE=""
DRY_RUN=0

# Parse optional flags: --queue PATH, --dry-run, or positional queue path.
ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --queue)
      QUEUE="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      echo "Usage: $(basename "$0") [--queue PATH] [--dry-run]"
      exit 0
      ;;
    *)
      if [[ -z "$QUEUE" && "$1" != -* ]]; then
        QUEUE="$1"
        shift
      else
        ARGS+=("$1")
        shift
      fi
      ;;
  esac
done
if [[ -z "$QUEUE" ]]; then
  QUEUE="$QUEUE_DEFAULT"
fi

# RAM guard: never run alongside render/Whisper (ffmpeg/whisper only; NOT bare 'render' which matches Chrome renderers).
if pgrep -fl "ffmpeg|whisper" >/dev/null 2>&1; then
  echo "BLOCKED: render/whisper active; wait and retry" >&2
  exit 1
fi

NEXT_PAYLOAD="$(python3 - "$QUEUE" <<'PY'
import json, sys
from pathlib import Path
qpath = Path(sys.argv[1])
q = json.loads(qpath.read_text(encoding="utf-8"))
items = q.get("items", q) if isinstance(q, dict) else q
for it in items:
    payload = Path(it.get("payload", ""))
    if not payload.exists():
        continue
    pub = payload.parent / "published.json"
    done = False
    if pub.exists():
        try:
            rec = json.loads(pub.read_text(encoding="utf-8"))
            if rec.get("url"):
                done = True
        except Exception:
            done = False
    if not done:
        print(str(payload))
        break
PY
)"

if [[ -z "${NEXT_PAYLOAD:-}" ]]; then
  echo "QUEUE EMPTY"
  exit 0
fi

echo "NEXT: $NEXT_PAYLOAD" >&2
if [[ "$DRY_RUN" == "1" ]]; then
  echo "DRY-RUN: would publish $NEXT_PAYLOAD" >&2
  exit 0
fi

# One command, headless by default, never opens the URL.
"$SCRIPT_DIR/zhihu_publish.sh" "$NEXT_PAYLOAD" --mode publish --no-open
