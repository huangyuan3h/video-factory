#!/usr/bin/env bash
# Zhihu publisher wrapper — runnable from anywhere.
# Usage:
#   scripts/zhihu_publish.sh <payload.json> [--draft-only] [--headed] [--force] [--no-open] [extra args...]
#   scripts/zhihu_publish.sh --payload <payload.json> --mode publish [extra args...]
# Examples:
#   scripts/zhihu_publish.sh ~/Projects/karios-series-output/zhihu/ep9_ma5_20_golden_cross/publish_payload.json --draft-only
#   scripts/zhihu_publish.sh ~/Projects/karios-series-output/zhihu/ep1_macd_golden_cross/publish_payload.json --mode publish
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKER_DIR="$ROOT/apps/worker"

usage() {
  cat <<'EOF'
Usage:
  zhihu_publish.sh <payload.json> [--draft-only] [--headed] [--force] [--no-open] [extra zhihu_publish args...]
  zhihu_publish.sh --payload <payload.json> [--mode draft|publish] [...]

Examples:
  zhihu_publish.sh ~/Projects/karios-series-output/zhihu/ep9_ma5_20_golden_cross/publish_payload.json --draft-only
  zhihu_publish.sh <payload> --mode publish --no-open
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

# Prefer an already-installed venv python (no network) over `uv run`
# (which may try to re-sync on slow networks). Main checkout venv is the
# known-good read-only fallback (worktree .venv never finished `uv sync`);
# worktree .venv is used only when it actually has playwright.
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
  local py
  py="$(pick_python)"
  if [[ "$py" == "uv" ]]; then
    exec uv run python -m src.publishers.zhihu_publish "$@"
  else
    exec "$py" -m src.publishers.zhihu_publish "$@"
  fi
}

if [[ "${1:-}" == -* ]]; then
  # Caller already uses flags (e.g. --payload ...); pass through verbatim.
  run_cli "$@"
else
  PAYLOAD="$1"
  shift
  run_cli --payload "$PAYLOAD" "$@"
fi
