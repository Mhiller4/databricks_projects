#!/usr/bin/env bash
# Starts the API and the LiveKit voice worker; the worker restarts if it exits.
# The API owns DATABRICKS_APP_PORT; the worker's health server uses LIVEKIT_AGENT_PORT.
# On SIGTERM (app stop/redeploy) both are stopped right away, inside the 15 s limit.
set -u
PORT="${DATABRICKS_APP_PORT:-8000}"
export CARE_FINDER_API="http://127.0.0.1:${PORT}"
PIDS=()

# Fresh data on every start: the API re-downloads the gold export from the UC volume when this folder is empty,
# so "restart the app" always means "serve the latest hc_care_finder run".
[ -n "${CARE_FINDER_DATA:-}" ] && rm -rf "${CARE_FINDER_DATA}"

shutdown() { echo "[start_app] stopping"; kill "${PIDS[@]}" 2>/dev/null; pkill -P $$ 2>/dev/null; exit 0; }
trap shutdown TERM INT

uvicorn app.main:app --host 0.0.0.0 --port "${PORT}" &
PIDS+=($!)

# No LiveKit or Gemini keys (scripts/create_secrets.sh stored "not-set"): serve the website only.
if [ "${LIVEKIT_API_KEY:-not-set}" = "not-set" ] || [ "${GOOGLE_API_KEY:-not-set}" = "not-set" ]; then
  echo "[start_app] no voice keys: website and API only"
  wait "${PIDS[0]}"; exit $?
fi

(
  trap 'kill $(jobs -p) 2>/dev/null; exit 0' TERM
  for _ in $(seq 1 60); do
    python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${PORT}/api/health', timeout=3)" 2>/dev/null && break
    sleep 2
  done
  while true; do
    echo "[start_app] starting voice worker"
    python voice_agent/agent.py start &
    wait $! || echo "[start_app] voice worker exited ($?)"
    sleep 5
  done
) &
PIDS+=($!)

wait "${PIDS[0]}"   # the app lives as long as the API does
