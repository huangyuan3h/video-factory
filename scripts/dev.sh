#!/usr/bin/env bash
# One-click dev launcher for video-factory.
# Starts web + worker on random free ports (no conflicts).
# ComfyUI is OFF by default because it can stress RAM on laptops;
# enable with WITH_COMFYUI=1 — it runs with --lowvram --reserve-vram 4
# and the worker additionally hard-clamps resolutions + gates on free memory.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# --- pick random free ports ---------------------------------------------
free_port() {
  python3 - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
}
WORKER_PORT="${WORKER_PORT:-$(free_port)}"
WEB_PORT="${WEB_PORT:-$(free_port)}"
COMFY_PORT="${COMFY_PORT:-$(free_port)}"

export COMFYUI_URL="http://127.0.0.1:${COMFY_PORT}"
export WORKER_PORT

# Disable proxies so localhost + ComfyUI calls stay local
NO_PROXY="127.0.0.1,localhost"
no_proxy="127.0.0.1,localhost"
ALL_PROXY="" all_proxy="" http_proxy="" https_proxy=""

PIDS=()

cleanup() {
  echo ""
  echo "Shutting down video-factory dev services..."
  for p in "${PIDS[@]:-}"; do
    [ -n "$p" ] && kill "$p" 2>/dev/null
  done
  wait 2>/dev/null
}
trap cleanup EXIT INT TERM

# --- ComfyUI (optional, safe) -------------------------------------------
if [ "${WITH_COMFYUI:-0}" = "1" ]; then
  COMFY_DIR="${COMFY_DIR:-$HOME/Projects/ComfyUI}"
  if [ -d "$COMFY_DIR" ]; then
    echo "Starting ComfyUI on :${COMFY_PORT} (SAFE: --lowvram --reserve-vram 4)"
    (
      cd "$COMFY_DIR" || exit 1
      python main.py --listen 127.0.0.1 --port "$COMFY_PORT" \
        --lowvram --reserve-vram 4 --disable-smart-memory \
        --use-pytorch-cross-attention > /tmp/comfyui-dev.log 2>&1
    ) &
    PIDS+=($!)
  else
    echo "WITH_COMFYUI=1 but $COMFY_DIR not found — skipping ComfyUI"
  fi
fi

# --- Worker (FastAPI) ----------------------------------------------------
echo "Starting worker on :${WORKER_PORT}"
(
  cd "$ROOT/apps/worker" || exit 1
  NO_PROXY="$NO_PROXY" no_proxy="$no_proxy" ALL_PROXY="$ALL_PROXY" \
  all_proxy="$all_proxy" http_proxy="$http_proxy" https_proxy="$https_proxy" \
  uv run uvicorn src.main:app --host 127.0.0.1 --port "$WORKER_PORT" \
    > /tmp/worker-dev.log 2>&1
) &
PIDS+=($!)

# --- Web (Next.js) ------------------------------------------------------
echo "Starting web on :${WEB_PORT}"
(
  cd "$ROOT/apps/web" || exit 1
  WORKER_URL="http://127.0.0.1:${WORKER_PORT}" \
  NEXT_PUBLIC_WORKER_URL="http://127.0.0.1:${WORKER_PORT}" \
  pnpm dev -- -p "$WEB_PORT" > /tmp/web-dev.log 2>&1
) &
PIDS+=($!)

echo "=================================================================="
echo " video-factory dev"
echo "   web:     http://127.0.0.1:${WEB_PORT}"
echo "   worker:  http://127.0.0.1:${WORKER_PORT}   (/ready, /api/synthetic/status)"
echo "   comfyui: ${COMFYUI_URL}  ($([ "${WITH_COMFYUI:-0}" = "1" ] && echo ON || echo OFF))"
echo " logs:     /tmp/{web,worker,comfyui}-dev.log"
echo "=================================================================="
echo "Press Ctrl+C to stop all."

wait
