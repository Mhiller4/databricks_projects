# WP0 spike: outbound egress from a Databricks Free Edition app

Answers one question before we commit to the architecture (design §1): **can an app reach
`*.livekit.cloud` (WebSocket) and `generativelanguage.googleapis.com` (Gemini Live)?**

- Pass → the voice worker runs inside the Databricks App.
- Fail → the worker runs on a laptop (WP2.4) and the app serves the page + API only.

Also reports (informational) whether the Files API answers from inside the app, which
pre-checks the volume download path in `backend/app/data.py`.

## Run it

1. Put your LiveKit project URL (`wss://...livekit.cloud`, **not** a secret) into `app.yaml`.
2. Deploy from the repo root:
   ```
   databricks apps create spike-connectivity            # once
   databricks apps deploy spike-connectivity --path apps/spike_connectivity
   databricks apps start spike-connectivity
   ```
3. Open the app URL: the page shows REACHABLE or BLOCKED per host. Record it in
   `openspec/changes/add-web-app/tasks.md` (WP0), then delete the app
   (`databricks apps delete spike-connectivity`).

Stdlib only — no `requirements.txt`, nothing to install, small compute.