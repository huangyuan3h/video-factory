#!/bin/bash
# One-line wrapper (repo root): always run from apps/worker with proxy.
cd "$(dirname "$0")/../apps/worker" && export HTTPS_PROXY=http://127.0.0.1:7890 HTTP_PROXY=http://127.0.0.1:7890 NO_PROXY=127.0.0.1,localhost; exec uv run python scripts/youtube_reauth.py "$@"
