# Change: add the Care Finder web app (voice + chat + search), deployed as a Databricks App

**Start here.** This folder is a self-contained handoff for the agent building the web app:

| File | What it holds |
|---|---|
| `proposal.md` (this file) | Why, what, current state, ground rules |
| `design.md` | Architecture, decisions, API/message contracts, UI design |
| `tasks.md` | Work packages in build order: dependencies, steps, commands, acceptance checks |
| `specs/web-app/spec.md` | Requirements with scenarios (what "done" means) |

Product background: [`docs/CHALLENGE.md`](../../../docs/CHALLENGE.md) and [`openspec/specs/care-finder/spec.md`](../../specs/care-finder/spec.md).
Deadline: **Sun Nov 22, 12:30 PM** (code, analysis and video). Plan for a demo-ready build by **Sun 9:00 AM**.

## Why

Care Finder already works end to end on the phone: a LiveKit voice agent asks who is calling (provider or
patient), takes a service and a location, and reads back grounded recommendations from our FastAPI engine
over the Databricks gold tables. There is no web interface yet. Judges, health workers and planners need:

- a page where they **tap a mic and talk** to the same agent (like LiveKit's agent playground),
- a **chat box** for when they can't talk (noise, privacy, a blocked mic), in the same conversation,
- a **manual search** that works even if voice is down,
- and the evidence on screen: a **map, three result cards, the funnel, and a "Why & How" drawer**, which
  fill in live while the agent talks.

The whole thing must be **deployed and managed in Databricks** (a Databricks App in our bundle). Not Vercel
or any other host.

## What changes

1. **Backend** (`backend/`): a LiveKit token endpoint, location type-ahead, loading data from the Unity
   Catalog volume when deployed, tagging broadcasts with the session, and a `/api/config` endpoint.
2. **Voice agent** (`voice_agent/agent.py`): read the caller's role from the web page (skip the "press 1/2"
   greeter), publish each full result into the LiveKit room for the page, and run inside the Databricks App.
3. **Frontend** (new `frontend/`): React + Vite + TypeScript. Mic and agent panel, chat, location box with
   type-ahead / GPS / draggable pin, map, result cards, funnel, Why & How drawer, weight sliders, and a
   `/monitor` screen for phone-call demos.
4. **Packaging and deploy**: a build script that assembles the app folder, a bundle app resource
   (`resources/care_finder.app.yml`), a secret scope for the LiveKit and Gemini keys, and a smoke test.

## Current state (as of Sat Nov 21, ~5:30 PM)

Working and tested locally:

- **Data**: `hc_care_finder` job (Delta Share → bronze → silver → gold → Parquet export). The serving
  Parquet is in the UC volume `workspace.hc_gold.serving` and downloaded to `backend/data/` (gitignored).
- **Backend**: `backend/app/` (FastAPI + DuckDB). 11 passing tests: `cd backend && .venv/bin/pytest -q`.
  Endpoints: `GET /api/health`, `GET /api/services`, `GET /api/locations?q=`, `POST /api/recommend`,
  `GET /api/last`, `WS /ws/live`. Example responses: `backend/examples/*.json`. Typical query 30–80 ms.
- **Voice agent**: `voice_agent/agent.py` (livekit-agents 1.8.13, Gemini Live `gemini-3.8-live`, voice
  `Fola`, API version `v1beta`). Flow: Greeter ("press 1 or say provider / press 2 or say patient", by
  keypad or voice) → ProviderAgent or PatientAgent, both with one tool `find_best_care` that calls
  `POST /api/recommend` with `audience` and `broadcast_to_ui=true`. It registers with LiveKit Cloud with an
  empty agent name, so it **joins every new room in the project automatically**.
- **Not done**: frontend, token endpoint, Databricks App, phone dispatch rule, ML model drivers
  (`model_drivers` is always `null` for now).
- **Git**: branch `hackathon/healthcare-datathon`. Recent work is **not committed**. Ask the user before
  committing or pushing.

## Ground rules (non-negotiable)

- **Grounding.** The page renders only facilities that are in an API payload. Never invent, fill or
  "improve" a facility, phone number, distance or claim. Cautions and evidence quotes are shown verbatim.
  Desert messages keep the words "in this dataset".
- **Rules live in the backend.** Gates, weights, tiers and summaries are computed by `backend/app/engine.py`
  and `summary.py`. The frontend never re-ranks or re-scores. Moving the sliders calls the API again.
- **Secrets.** Keys live in `/Users/mekelihiller/Desktop/Databricks_Hackathon/.env.local`, one folder
  *above* the repo: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `GOOGLE_API_KEY`. Never print,
  log, commit or paste them. Check presence with a length-only test. In Databricks they go into a secret scope.
- **Databricks CLI profile.** Never auto-select a profile. The user has been using `--profile Mekeli`.
  Confirm with the user before the first command.
- **Only Databricks hosts it.** No Vercel, Netlify, or other hosts.
- **Free Edition.** Serverless only, small app compute (2 vCPU / 6 GB). Keep the app to one process tree.
