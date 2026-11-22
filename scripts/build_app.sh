#!/usr/bin/env bash
# Assemble the Care Finder Databricks App into build/care_finder_app/ (gitignored; synced via databricks.yml).
#   scripts/build_app.sh && databricks bundle deploy -t free --profile <p> && databricks bundle run care_finder -t free --profile <p>
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/build/care_finder_app"
rm -rf "$OUT" && mkdir -p "$OUT/hc" "$OUT/voice_agent"

if [ -f "$ROOT/frontend/package.json" ]; then
  (cd "$ROOT/frontend" && npm ci --silent && npm run build --silent)
  mkdir -p "$OUT/frontend" && cp -R "$ROOT/frontend/dist" "$OUT/frontend/dist"
else
  echo "no frontend/ yet: the app serves the API only (/docs)"
fi

rsync -a --exclude '__pycache__' "$ROOT/backend/app" "$OUT/"
cp "$ROOT/src/hc/__init__.py" "$ROOT/src/hc/care.py" "$ROOT/src/hc/symptoms.py" "$OUT/hc/"
cp "$ROOT/voice_agent/agent.py" "$ROOT/voice_agent/guidance.py" "$OUT/voice_agent/"
cp "$ROOT/deploy/care_finder_app/"{app.yaml,start_app.sh,requirements.txt} "$OUT/"
chmod +x "$OUT/start_app.sh"
echo "assembled $OUT:"; (cd "$OUT" && find . -type f | sort)
