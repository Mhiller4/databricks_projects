# Tasks: build order and orchestration

Read `proposal.md` (ground rules) and `design.md` (contracts) first. Mark tasks `[x]` as you go.

## Orchestration

```
WP0 spike (30 min) ──┐
WP1 backend ─────────┼──► WP2 agent ──┐
WP3 frontend ────────┘ (mock data)    ├──► WP4 package + deploy ──► WP5 polish + demo checks
                                      │
                       WP3 live wiring┘
```

- **Parallel**: WP0, WP1 and WP3 can start at once. WP3 builds against `backend/examples/*.json` until WP1
  lands.
- **Serial**: WP2 needs WP1.1 (token) and WP1.4 (session tag). WP4 needs WP1 to WP3. WP5 needs WP4.
- **Cut lines** if behind at **Sun 8:00 AM**, drop in this order: `/monitor` polish → referral copy
  button → sliders → GPS → chat. **Never drop**: citations, cautions, funnel, desert banner, manual search.
- **After each WP**: run its checks, tell the user what changed in two or three sentences, and don't
  commit unless asked.

## Environment and how to run (local)

```bash
cd /Users/mekelihiller/Desktop/Databricks_Hackathon/databricks_projects
# backend (Python 3.12 venv already exists)
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000      # http://localhost:8000/docs
.venv/bin/pytest -q                                                    # must stay green
# voice agent (separate venv)
cd ../voice_agent && .venv/bin/python agent.py dev                     # joins every room in the LiveKit project
# refresh data after the pipeline reruns (ask the user which profile; they have used Mekeli)
databricks fs cp -r --overwrite dbfs:/Volumes/workspace/hc_gold/serving backend/data --profile <p>
```

- Keys load automatically from `../.env.local` (one folder above the repo). Check presence without
  printing values.
- Node 20 is installed (`/opt/homebrew/opt/node@20/bin`). `uv` is available for Python venvs.
- Free test calls: LiveKit Cloud console (Agents → start session) or https://agents-playground.livekit.io.

---

## WP0 · Spike: can a Free Edition app reach LiveKit and Gemini? (30 min, do first)

- [ ] 0.1 Deploy a throwaway app (CLI: `databricks apps create` + `deploy`, or a temporary bundle
      resource) whose `app.py` opens outbound WebSockets to `LIVEKIT_URL` and to Gemini Live
      (`google-genai` live connect with `http_options={"api_version": "v1beta"}`), and serves the results
      at `/`.
- [ ] 0.2 Record the result in this file. **Pass**: the worker runs inside the app (design §1). **Fail**:
      the worker runs on a laptop, and WP2.4 becomes required.
- [ ] 0.3 Delete the throwaway app (ask the user first).
- Also note any Free Edition app limits you hit (number of apps, auto-stop). They affect the demo plan.

## WP1 · Backend additions (`backend/`)

- [x] 1.1 `POST /api/livekit/token` as in design §3.1. Add `livekit-api` to `backend/requirements.txt`.
      Test: a token decodes (no network), has room, identity, attributes and grants, and a TTL of 15 min.
      *(Note: LiveKit JWT carries identity in `sub`, grants camelCase (`roomJoin`), TTL = `exp` − `nbf`.)*
- [x] 1.2 `GET /api/locations` type-ahead as in design §3.2. Tests: `"Ban"` returns Bangalore/Bengaluru
      and Bandra-type localities with state and district; `"8000"` returns PIN 8000xx rows; at most 8 rows.
- [x] 1.3 `GET /api/config` as in design §3.3.
- [x] 1.4 Optional `session` on `POST /api/recommend`, echoed into broadcasts (design §3.4).
- [x] 1.5 Volume loading in `data.py` (design §3.5). Unit-test the "local data present" path; the volume
      path is tested in WP4. *(Implementation note: the SDK Files API methods are
      `list_directory_contents` + `download_to`; verified against the live volume — all 4 tables
      download. Inside a Databricks App the ambient credentials are the app service principal's.)*
- [x] 1.6 Engine import works both from the repo and from the assembled app (design §7).
      *(try `from hc import care`, fall back to `src/` on the path.)*
- **Checks**: `.venv/bin/pytest -q` green (**19 passed**: 11 existing + 8 new in `tests/test_web_app.py`).
  `/docs` shows the new endpoints (token, config; locations now type-ahead).

## WP2 · Voice agent (`voice_agent/agent.py`)

- [ ] 2.1 Role from the participant attribute `care_finder.role` → start `ProviderAgent` / `PatientAgent`
      directly; no attribute → `Greeter` (design §4). Keep DTMF and voice selection for phone calls.
- [ ] 2.2 Publish the full response to topic `care-finder.result` after each search, and pass
      `session=<room name>` to the backend.
- [ ] 2.3 Configurable worker port, and `CARE_FINDER_API` defaulting to the app port (design §4).
- [ ] 2.4 *(only if WP0 failed)* The laptop worker calls the deployed app with a Databricks OAuth token
      (for example from `databricks auth token --profile <p>`, refreshed before it expires), or the team
      uses a local backend plus local `/monitor` for phone demos. Write down which one you chose.
- **Checks**:
  - In the LiveKit console or playground (no role attribute), the greeter still asks 1 / 2.
  - With a token from 1.1 (role=patient), the agent opens with the emergency question.
  - A page subscribed to `care-finder.result` receives a JSON payload after a search.
  - Typing in chat gets a spoken and transcribed reply.

## WP3 · Frontend (`frontend/`, new)

- [ ] 3.1 Scaffold Vite + React + TypeScript. Dev proxy `/api` and `/ws` → `localhost:8000`.
      `npm run build` → `frontend/dist` (already gitignored; FastAPI serves it).
- [ ] 3.2 `SearchBar` + `LocationBox` + `ResultCard` + `Funnel` + `DesertBanner` + `Clarify`, driven by
      `backend/examples/*.json` (darbhanga = normal, nanded = desert, aurangabad = clarification). Then
      wire them to the live API.
- [ ] 3.3 `CareMap` (react-leaflet): you-pin (drag → new search with `{lat, lon}`), numbered tier pins,
      grey skipped pins with hover reasons, red ring of radius `safe_km` when a desert alert fires.
- [ ] 3.4 `WhyHowDrawer`: citations with field label and source links, contribution bars from
      `score_breakdown.contributions`, `confidence_reason`, `method.gates`, "Why not closer?" from
      `skipped_nearby`, weight sliders (debounced re-query), referral card with a copy button (design §6.4).
- [ ] 3.5 `AgentPanel` + `Conversation`: role chips → `POST /api/livekit/token` → connect with LiveKit's
      React components; mic orb, visualizer, transcript, chat input; render `care-finder.result` payloads
      into the same map, cards and funnel as manual search.
- [ ] 3.6 `/monitor` route: subscribes to `WS /ws/live`, shows the latest phone-call result full-screen.
- [ ] 3.7 Responsive (360 px), dark mode, accessibility items in design §6.5.
- **Checks**:
  - Every scenario in `specs/web-app/spec.md` passes by hand against the local backend.
  - No facility appears that isn't in the current payload.
  - `npm run build` succeeds with no TypeScript errors.

## WP4 · Package and deploy as a Databricks App

- [ ] 4.1 `scripts/build_app.sh` and `scripts/start_app.sh` (design §7). Add `build/` to `.gitignore`.
- [ ] 4.2 `databricks.yml`: `app_name` variable + `sync.include`. Add `resources/care_finder.app.yml` and
      `build/care_finder_app/app.yaml`.
- [ ] 4.3 Ask the **user** to create the secret scope and secrets (commands in design §7). Never handle
      the values yourself.
- [ ] 4.4 Validate: `databricks bundle validate --strict -t free -o json --profile <p>`. Check the resolved
      app name (≤ 30 characters, lowercase letters, digits and hyphens).
- [ ] 4.5 Deploy and start: `databricks bundle deploy -t free --profile <p>` then
      `databricks bundle run care_finder -t free --profile <p>`. Watch `databricks apps logs <name> --profile <p>`.
- [ ] 4.6 Smoke test on the app URL: page loads; `/api/health` ok; manual search for "dialysis" +
      "Darbhanga, Bihar" returns 3 cards; voice session connects and answers; `/monitor` updates on a
      phone or console call.
- [ ] 4.7 README: an "App" section with the URL pattern, the deploy commands, and how to refresh data
      (pipeline run → app restart).

## WP5 · Polish and demo checks

- [ ] 5.1 Phone banner from `CARE_FINDER_PHONE` once the user adds the LiveKit dispatch rule and gives the
      number.
- [ ] 5.2 Persona presets (Rural health worker / NGO coordinator / District planner) set role, urgency and
      default weights.
- [ ] 5.3 Run the demo script below twice, end to end, on the deployed app. Fix anything slow or confusing.

### Demo script (for the video)

1. Open the app. Tap **Patient**, then say: "My mother needs dialysis, we're in Bandra, Mumbai." The map
   and cards fill in while the agent speaks. Open **Why & how** on the top card: quote, sources, score bars.
2. Type in chat: "Why not the closer one?" The agent answers from `skipped_nearby`, and the map shows the grey pin.
3. Manual search: "emergency c-section", "Nanded", emergency. The desert banner and ring appear, with the
   nearest verified option 100 km away.
4. Drag the sliders (proximity to max). The ranking changes, but no unverified facility appears (gates).
5. Phone: call the number, press 1, ask for a NICU near PIN 226001. `/monitor` updates live.
