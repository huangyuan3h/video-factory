#!/bin/bash
# Resume pending YouTube replacements (public stays public, same playlist position).
# Reads .opencode-runs/yt_pending_uploads.json (18 eps, ep1 first). One upload at a time.
# Needs: HTTPS_PROXY=http://127.0.0.1:7890, valid OAuth (on invalid_grant, stop + reauth).
# On quotaExceeded: stop, keep remaining in pending file, report done + pending.
set -e
cd "$(dirname "$0")/../apps/worker"
export HTTPS_PROXY=http://127.0.0.1:7890 HTTP_PROXY=http://127.0.0.1:7890 NO_PROXY=127.0.0.1,localhost
PENDING="../../.opencode-runs/yt_pending_uploads.json"
if [ ! -f "$PENDING" ]; then
  echo "no pending file $PENDING"
  exit 0
fi
EPS=$(python3 -c "import json; print(' '.join(str(e['ep']) for e in json.load(open('$PENDING'))))")
for EP in $EPS; do
  echo "=== uploading ep$EP ==="
  set +e
  uv run python ../../.opencode-runs/yt_replace.py "$EP"
  CODE=$?
  set -e
  if [ $CODE -eq 0 ]; then
    echo "ep$EP done, removing from pending"
    python3 -c "import json; p='$PENDING'; d=json.load(open(p)); d=[e for e in d if e['ep']!=int('$EP')]; open(p,'w').write(json.dumps(d, ensure_ascii=False, indent=2))"
  elif [ $CODE -eq 2 ]; then
    echo "invalid_grant on ep$EP: stop, run youtube_reauth, then rerun this script"
    exit 2
  elif [ $CODE -eq 3 ]; then
    echo "quotaExceeded on ep$EP: stop, remaining stay pending, rerun later"
    exit 3
  else
    echo "ep$EP failed code $CODE: stop, keep pending for manual check"
    exit 1
  fi
  sleep 5
done
echo "all pending uploads done"
