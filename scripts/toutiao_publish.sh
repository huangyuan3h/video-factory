#!/usr/bin/env bash
# Toutiao publisher wrapper — runnable from anywhere.
# Usage:
#   scripts/toutiao_publish.sh <payload.json> [--draft-only] [--headed] [--force] [--no-open] [extra args...]
#   scripts/toutiao_publish.sh --payload <payload.json> --mode draft|publish [extra args...]
# Examples:
#   scripts/toutiao_publish.sh ~/Projects/karios-series-output/zhihu/ep3_holiday_effect/toutiao_payload.json --draft-only
#   scripts/toutiao_publish.sh ~/Projects/karios-series-output/zhihu/ep3_holiday_effect/toutiao_payload.json --mode draft
# Smoke contract: draft mode NEVER clicks 发布/publish and never ticks 首发.
# Publish mode is implemented but NOT exercised in the smoke test.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKER_DIR="$ROOT/apps/worker"

usage() {
  cat <<'EOF'
Usage:
  toutiao_publish.sh <payload.json> [--draft-only] [--headed] [--force] [--no-open] [extra toutiao_publish args...]
  toutiao_publish.sh --payload <payload.json> [--mode draft|publish] [...]

Examples:
  toutiao_publish.sh ~/Projects/karios-series-output/zhihu/ep3_holiday_effect/toutiao_payload.json --draft-only
  toutiao_publish.sh <payload> --mode publish --no-open
EOF
}

if [[ $# -eq 0 ]]; then
  usage >&2
  exit 1
fi

for a in "$@"; do
  if [[ "$a" == "-h" || "$a" == "--help" ]]; then
    usage
    exit 0
  fi
done

cd "$WORKER_DIR"

# Prefer an already-installed venv python (no network) over `uv run`.
pick_python() {
  if [[ -x "$HOME/Projects/video-factory/apps/worker/.venv/bin/python" ]]; then
    echo "$HOME/Projects/video-factory/apps/worker/.venv/bin/python"
  elif [[ -x "$WORKER_DIR/.venv/bin/python" ]] && "$WORKER_DIR/.venv/bin/python" -c "import playwright" 2>/dev/null; then
    echo "$WORKER_DIR/.venv/bin/python"
  else
    echo "uv"
  fi
}

run_cli() {
  # Fix 2026-10-01: unbuffered (python -u) + timestamps so stdout is never empty.
  export PYTHONUNBUFFERED=1
  local py
  py="$(pick_python)"
  if [[ "$py" == "uv" ]]; then
    exec uv run python -u -m src.publishers.toutiao_publish "$@"
  else
    exec "$py" -u -m src.publishers.toutiao_publish "$@"
  fi
}

if [[ "${1:-}" == -* ]]; then
  run_cli "$@"
else
  PAYLOAD="$1"
  shift
  run_cli --payload "$PAYLOAD" "$@"
fi
