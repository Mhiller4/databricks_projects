# Design: Care Finder web app

## 1. Architecture

One Databricks App runs everything users touch. The data pipeline stays a Databricks job.

```
                         ┌──────────────── Databricks App "care-finder-<you>" (one container) ────────────────┐
 Browser                 │                                                                                     │
  React page ──HTTPS──►  │  uvicorn  backend/app/main.py  (FastAPI + DuckDB, Parquet loaded at startup)        │
   ├─ POST /api/recommend│     /api/recommend  /api/locations  /api/services  /api/config                      │
   ├─ POST /api/livekit/token ─► signs a short-lived LiveKit token (key + secret from the secret scope)          │
   ├─ WS  /ws/live  ◄───────── broadcasts every voice result (used by /monitor for phone calls)                 │
   │                     │                                                                                     │
   │                     │  python voice_agent/agent.py start   (LiveKit worker, background process)           │
   │                     │     └─ find_best_care ─► http://127.0.0.1:$PORT/api/recommend  (same container)      │
   │                     └────────────────────────────────┬────────────────────────────────────────────────────┘
   │  WebRTC audio + text                                 │ outbound WebSocket
   └──────────────────────────────►  LiveKit Cloud  ◄─────┘   (room per call / web session)
 Phone caller ──PSTN/SIP──────────►  LiveKit Cloud            Gemini Live (Google) ◄── worker, outbound
                                                              
 Job hc_care_finder ─► UC volume workspace.hc_gold.serving/*.parquet ─► app downloads at startup (SDK, app service principal)
```

**Why one app with the worker inside it**

- The worker calls the backend on `127.0.0.1`, so there's no Databricks OAuth between them.
- Phone calls and web sessions share one backend, so `/ws/live` sees phone results too.
- It's managed in Databricks, matching the requirement. Logs: `databricks apps logs <name>`.

**Risk**: Free Edition apps must allow outbound WebSockets to `*.livekit.cloud` and
`generativelanguage.googleapis.com`. Work package WP0 checks this first. **Fallback**: the worker runs on a
laptop with `CARE_FINDER_API=<app url>`. That needs a Databricks OAuth bearer token on each request (see
WP2.4), or the worker calls a local backend copy and `/monitor` runs locally for phone demos.

## 2. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | React + Vite + TypeScript, built to static files and served by FastAPI | One app, one URL. `main.py` already serves `frontend/dist` when it exists |
| D2 | LiveKit's React library (`livekit-client`, `@livekit/components-react`, `@livekit/components-styles`) | Ready-made mic, audio visualizer, transcripts and chat. Check current hook names in the LiveKit docs before use |
| D3 | Map: Leaflet + `react-leaflet`, OpenStreetMap tiles with attribution | Free, no key. Tiles load in the browser, not the app |
| D4 | Web sessions get results **through the LiveKit room** (text stream topic `care-finder.result`), not `/ws/live` | Each browser sees only its own session; works wherever the backend runs |
| D5 | `/ws/live` stays for **phone calls** and the `/monitor` screen (broadcasts tagged with `room`) | A phone call has no browser in the room |
| D6 | Role chosen on the page is passed in the token as participant attribute `care_finder.role` | The agent skips the "press 1 / 2" greeter for web users |
| D7 | Chat uses LiveKit's default text input (`lk.chat` topic); replies arrive as transcript text plus audio | One conversation, two ways in. Already enabled by default in livekit-agents 1.8 (`RoomOptions.text_input`) |
| D8 | Manual search calls `POST /api/recommend` directly, no LiveKit | Works when voice is down. It's the demo fallback |
| D9 | Sliders re-query the API (debounced about 150 ms) with `weights`; the frontend never re-ranks | Gates and scores stay in one place (`engine.py`) |
| D10 | Data comes from the UC volume at app startup if `backend/data/` is missing | Keeps the app source small; a pipeline rerun plus app restart refreshes data |
| D11 | App source is **assembled** by `scripts/build_app.sh` into `build/care_finder_app/` | The backend imports `src/hc/care.py` (outside `backend/`), and `frontend/dist` and `data/` are gitignored, so bundle sync would skip them |

## 3. Backend additions (contracts)

### 3.1 `POST /api/livekit/token`

Request: `{ "role": "provider" | "patient" | null, "language": "en" | "hi" | ... | null }`

Response:
```json
{ "server_url": "wss://<project>.livekit.cloud", "participant_token": "<jwt>",
  "room_name": "web-3f9a1c2e", "identity": "web-user-3f9a1c2e" }
```
- Room name `web-<8 hex>`, identity `web-user-<same>`, TTL 15 minutes.
- Grants: `room_join`, `room=<room_name>`, `can_publish`, `can_subscribe`, `can_publish_data`.
- Attributes: `{"care_finder.role": role or "", "care_finder.language": language or ""}`.
- Python (package `livekit-api`):
  ```python
  from livekit import api
  token = (api.AccessToken(key, secret).with_identity(identity).with_name("Web user")
           .with_attributes(attrs).with_ttl(timedelta(minutes=15))
           .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True, can_publish_data=True))
           .to_jwt())
  ```
- The agent joins any new room automatically (empty agent name), so no dispatch call is needed.
- Rate-limit lightly (for example 10 tokens per minute per client IP) so the public page can't drain the
  free LiveKit and Gemini quotas.

### 3.2 `GET /api/locations?q=` (type-ahead)

- Start matching at **2 characters** (now 4), prefix-match localities and towns, and rank bigger places
  first (`n_points`, then kind priority).
- Return up to 8 rows: `{kind, display_name, district, state, lat, lon, precision, is_precise}`. Reuse
  `engine.location_precision()`.
- Remove duplicates that differ only by kind but name the same point (city and post office within 2 km).

### 3.3 `GET /api/config`

`{ "phone_number": "+1 ...", "services": [...], "funnel_base": {...}, "livekit_enabled": true }`. The
phone number comes from the env var `CARE_FINDER_PHONE` (blank hides the banner).

### 3.4 Broadcast tagging

`POST /api/recommend` accepts an optional `session` (the LiveKit room name). Broadcast messages become
`{type: "recommendation", source, audience, session, payload}`. `/monitor` shows the latest message of
any session.

### 3.5 Data loading in the app

`backend/app/data.py`: if `CARE_FINDER_DATA` has no Parquet, download `/Volumes/workspace/hc_gold/serving/**`
with the Databricks SDK (`WorkspaceClient().files`), using the app service principal, into a temp folder,
then load as today. Volume path from env var `CARE_FINDER_VOLUME` (default
`/Volumes/workspace/hc_gold/serving`).

## 4. Voice agent changes (contracts)

- **Role from the page**: in `entrypoint`, after `ctx.connect()`, wait for the first participant. If its
  attribute `care_finder.role` is `provider` or `patient`, start that persona directly. Otherwise start the
  `Greeter` (phone calls).
- **Results into the room**: after each `find_best_care` call, publish the **full** backend response
  (not the compact LLM version) with
  `get_job_context().room.local_participant.send_text(json.dumps(resp), topic="care-finder.result")`.
  Pass `session=<room name>` to the backend.
- **Run inside the app**: `scripts/start_app.sh` starts `python voice_agent/agent.py start` in the
  background, then `exec uvicorn ...` on `$DATABRICKS_APP_PORT`. The worker's own health server must not
  take the app port: set `AgentServer(port=...)` to a free port (for example 8091).
- **`CARE_FINDER_API`** defaults to `http://127.0.0.1:${DATABRICKS_APP_PORT:-8000}` inside the app.

## 5. LiveKit room messages (what the page listens to)

| Topic / channel | Direction | Content |
|---|---|---|
| audio track | both | Caller mic in, agent voice (Fola) out |
| `lk.transcription` | agent → page | Live captions for both sides (LiveKit default) |
| `lk.chat` | page → agent | Typed messages (LiveKit default text input) |
| `care-finder.result` | agent → page | Full `/api/recommend` response JSON after every search |

## 6. UI design

### 6.1 Layout (desktop; on phones it stacks top to bottom in this order)

```
┌ Header: "Care Finder · find the right care in India" ············ 📞 Call +1 xxx (from /api/config) ┐
│ ① Agent panel: big mic orb (Tap to talk) · visualizer · live caption · role chips [Health worker] [Patient] │
│ ② Conversation: transcript bubbles (spoken + typed) · text box [Type a message…] [Send]                     │
│ ③ Search bar (no voice needed): Service ▾  ·  Location box (type-ahead · 📍 Use my location) · urgency     │
│ ④ Map (left, 55%)                         │ ⑤ Result cards (right): Best balanced · Nearest verified ·      │
│   you-pin (draggable) · green 1-2-3 pins   │   Highest confidence. Each: name, distance, confidence chip,    │
│   grey skipped pins · red safe-radius ring │   1 quote, ⚠ cautions, 📞 call, [Why & how ▸]                    │
│ ⑥ Funnel strip: 10,088 → 10,077 → 9,698 → … → 3  (counts animate in)                                         │
└ Footer: data sources, "Only facilities in the Virtue Foundation dataset; call ahead before travelling." ─┘
```

### 6.2 Components (suggested file names under `frontend/src/components/`)

| Component | Shows | Data |
|---|---|---|
| `AgentPanel` | mic orb, connection state, visualizer, role chips | LiveKit room state; role → token request |
| `Conversation` | transcript + typed chat | `lk.transcription`, `lk.chat` |
| `SearchBar` | service select, `LocationBox`, urgency toggle, Search | `/api/services`, `/api/locations`, `POST /api/recommend` |
| `LocationBox` | type-ahead list, GPS button, precision badge | `/api/locations`; browser geolocation → `{lat, lon}` |
| `CareMap` | you-pin (draggable → new search), tier pins 1–3, skipped pins, desert ring (`safe_km`) | payload `query.location`, `recommendations`, `skipped_nearby`, `medical_desert_alert` |
| `ResultCard` | tier label, name, distance, confidence chip, first citation, cautions, call button | `recommendations[i]` |
| `WhyHowDrawer` | citations with field labels + `source_urls`; score breakdown bars (`contributions`); `confidence_reason`; `method.gates`; "Why not closer?" (`skipped_nearby`); weight sliders; referral card | full payload |
| `Funnel` | stages and counts | `funnel` |
| `DesertBanner` | red banner with `medical_desert_alert.message` and the nearest option | `medical_desert_alert`, `nearest_beyond_radius` |
| `Clarify` | "Which one?" buttons | `status: needs_clarification`, `options[].query` |
| `MonitorPage` (`/monitor`) | big-screen view of the latest phone-call result | `WS /ws/live` |

### 6.3 Mapping UI states to payloads

| Payload | UI |
|---|---|
| `status: "ok"`, `recommendations` non-empty | map + 3 cards + funnel |
| `recommendations` empty, `nearest_beyond_radius` non-empty | `DesertBanner` + cards from `nearest_beyond_radius` (labelled "Nearest verified, beyond safe distance") |
| `status: "needs_clarification"` | `Clarify` with `options` (click → search with `option.query`) |
| `status: "unknown_service"` | service picker highlighted, `options` as chips |
| `status: "unresolved_location"` | location box error, suggest PIN |
| `query.location.ask_for_more_detail = true` | amber precision badge: "City centre · add an area or PIN for closer results" |
| `confidence` | chip colours: High green, Medium amber, Low grey. Always with the word, never colour alone |

### 6.4 Referral card (copy button)

Built only from payload fields, in this format:
```
Referral · <service label>
<name> (<facility_type>) · <distance_km> km from <location display_name>
Address: <address>  ·  Phone: <phone>
Why: <why[0]>
Confidence: <confidence> — <confidence_reason>
Cautions: <cautions joined by "; " or "none listed">
Source: Care Finder (Virtue Foundation data, <date>) · call ahead before travelling
```

### 6.5 Look and accessibility

- Calm and clinical: white or near-white background, one teal accent, red only for emergencies and deserts.
  Support dark mode via `prefers-color-scheme`.
- Tap targets at least 44 px. Body text at least 16 px. Works at 360 px wide with no horizontal scroll.
- Plain-language labels, with UI strings kept in one file so a Hindi version is easy later.
- The mic orb has a text label and a keyboard shortcut (space). Status is announced for screen readers.
- Show `elapsed_ms` quietly in the funnel ("ranked in 42 ms"). It's a good demo detail.

## 7. Packaging and deploy

- `scripts/build_app.sh` (repo root): `npm ci && npm run build` in `frontend/`, then assemble
  `build/care_finder_app/` (gitignored):
  ```
  app.yaml  requirements.txt  start_app.sh
  app/            ← backend/app
  hc/             ← src/hc/__init__.py + src/hc/care.py   (engine imports `from hc import care`)
  voice_agent/    ← voice_agent/agent.py
  frontend/dist/  ← built page
  ```
  Fix the engine import so it works both in the repo (`sys.path` to `src/`) and in the assembled app
  (`hc/` next to `app/`).
- `databricks.yml`: add `sync: include: ["build/care_finder_app/**"]`, because bundle sync skips
  gitignored files.
- `resources/care_finder.app.yml`:
  ```yaml
  variables:   # in databricks.yml
    app_name: { default: "care-finder-${workspace.current_user.domain_friendly_name}" }  # ≤ 30 chars
  resources:
    apps:
      care_finder:
        name: ${var.app_name}
        description: "Care Finder: find the right care in India (voice, chat, search)"
        source_code_path: ../build/care_finder_app
        resources:
          - name: serving-volume
            uc_securable: { securable_full_name: workspace.hc_gold.serving, securable_type: VOLUME, permission: READ_VOLUME }
          - name: livekit-api-key
            secret: { scope: care-finder, key: livekit-api-key, permission: READ }
          - name: livekit-api-secret
            secret: { scope: care-finder, key: livekit-api-secret, permission: READ }
          - name: google-api-key
            secret: { scope: care-finder, key: google-api-key, permission: READ }
  ```
  Check the exact field names with `databricks bundle validate --strict -t free`, and the resolved name
  (lowercase letters, digits and hyphens, at most 30 characters) with `-o json`.
- `app.yaml`:
  ```yaml
  command: ["bash", "start_app.sh"]
  env:
    - { name: LIVEKIT_URL, value: "wss://<project>.livekit.cloud" }   # not secret; take from .env.local
    - { name: LIVEKIT_API_KEY, valueFrom: livekit-api-key }
    - { name: LIVEKIT_API_SECRET, valueFrom: livekit-api-secret }
    - { name: GOOGLE_API_KEY, valueFrom: google-api-key }
    - { name: CARE_FINDER_VOLUME, value: "/Volumes/workspace/hc_gold/serving" }
    - { name: CARE_FINDER_PHONE, value: "" }
  ```
- Secrets are created once by the **user** (the keys must not pass through chat or logs):
  ```bash
  databricks secrets create-scope care-finder --profile <p>
  databricks secrets put-secret care-finder livekit-api-key --profile <p>     # prompts for the value
  databricks secrets put-secret care-finder livekit-api-secret --profile <p>
  databricks secrets put-secret care-finder google-api-key --profile <p>
  ```
- Deploy: `scripts/build_app.sh && databricks bundle deploy -t free --profile <p> && databricks bundle run care_finder -t free --profile <p>`.
