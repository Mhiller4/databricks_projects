#!/usr/bin/env bash
# Creates the `care-finder` secret scope the app needs before it can deploy.
#   scripts/create_secrets.sh <profile>
# Voice (optional): export LIVEKIT_API_KEY, LIVEKIT_API_SECRET and GOOGLE_API_KEY first, and set LIVEKIT_URL and
# CARE_FINDER_PHONE in deploy/care_finder_app/app.yaml to your own LiveKit project. Without them the keys are
# stored as "not-set" and the app serves the website and API only.
set -euo pipefail
PROFILE="${1:?usage: scripts/create_secrets.sh <profile>}"
SCOPE=care-finder

if ! databricks secrets list-scopes --profile "$PROFILE" -o json | grep -q "\"name\": *\"$SCOPE\""; then
  databricks secrets create-scope "$SCOPE" --profile "$PROFILE"
  echo "created scope $SCOPE"
fi

put() {  # put <key> <value>; values are never printed
  databricks secrets put-secret "$SCOPE" "$1" --string-value "$2" --profile "$PROFILE"
  echo "stored $1"
}
put livekit-api-key    "${LIVEKIT_API_KEY:-not-set}"
put livekit-api-secret "${LIVEKIT_API_SECRET:-not-set}"
put google-api-key     "${GOOGLE_API_KEY:-not-set}"
