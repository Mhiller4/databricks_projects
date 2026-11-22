# Care Finder web app

Guided, phone-first page for the Care Finder Databricks App: who is asking → (patient) emergency check →
what care → where → one clear answer with a Call button, plus "Why this one?", other options, a map and
"How we decided". A floating mic opens a voice / chat session with the same LiveKit agent as the phone line.
`/monitor` shows the latest phone-call search live.

```bash
npm ci
npm run dev      # http://localhost:5173, proxies /api and /ws to the backend on :8000
npm run build    # dist/, served by backend/app/main.py; scripts/build_app.sh packages it into the app
```

Everything shown comes from `POST /api/recommend` (backend/app/engine.py). The page never ranks or scores.
