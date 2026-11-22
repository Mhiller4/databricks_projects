# Care Finder: find the right care in India

> A patient needs a specific kind of care. Where should they go, and why should they trust that answer?
> CMU Datathon Fall 2026 · Virtue Foundation dataset · Team: Mekeli, Bryce + Vidushi · Due Sun Nov 22, 12:30 PM

**The challenge:** take a **service** (dialysis, emergency C-section, NICU, MRI, ...) and a **location**
(city, district, PIN code, or coordinates). Return the best facilities, each with **cited evidence** from
the facility text and an honest **confidence level**. The data is about 10,000 Indian facility records
extracted from web text, so every field is a claim to verify. The tool must run on Databricks Free
Edition and work for non-technical users such as community health workers and NGO coordinators.

* Full brief, requirements checklist and data findings: [docs/CHALLENGE.md](docs/CHALLENGE.md)
* Product requirements: [openspec/specs/care-finder/spec.md](openspec/specs/care-finder/spec.md)
* Confidence model design and results: [docs/CONFIDENCE_MODEL_SPEC.md](docs/CONFIDENCE_MODEL_SPEC.md)

### Challenge data in this workspace

| Delta Share table | Bronze (as received) | Silver (cleaned) |
|---|---|---|
| `facilities` (10,088) | `hc_bronze.vf_facilities` | `hc_silver.vf_facilities` (10,077, exact duplicates removed) |
| `india_post_pincode_directory` (165,627) | `hc_bronze.vf_india_post_pincode_directory` | `hc_silver.vf_india_post_pincode_directory` |
| `nfhs_5_district_health_indicators` (706) | `hc_bronze.vf_nfhs_5_district_health_indicators` | `hc_silver.vf_nfhs_5_district_health_indicators` |

The share is `databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset` (bundle variable `share`).

### Care Finder gold layer

Rules and weights are in [`src/hc/care.py`](src/hc/care.py).

```sql
SELECT * FROM workspace.hc_gold.resolve_location('Darbhanga, Bihar');          -- or a PIN, or 'lat, lon'
SELECT * FROM workspace.hc_gold.recommend_facilities('dialysis', 26.13, 85.90); -- ranked, with why / evidence / cautions
```

| Table | Grain | What it holds |
|---|---|---|
| `hc_silver.facility_master` | facility | canonical state, location (with a tie-break when coordinates and PIN disagree), parsed claim lists, flags |
| `hc_gold.location_lookup` | place name | PIN / city / district / post office / state → median point |
| `hc_gold.service_catalog` | service | 16 services: match pattern, related specialties, travel distance |
| `hc_gold.facility_evidence_snippets` | facility × service × claim | **citations**: the exact text and its source field |
| `hc_gold.facility_service_evidence` | facility × service | evidence score, fields that agree, top 3 citations, type fit |
| `hc_gold.facility_trust` | facility | trust score, plain-language cautions, supporting facts |
| `hc_gold.care_finder_index` | facility × service | all of the above plus confidence and the explanation |

**Score** = evidence × type fit × record trust × exp(−km / service travel distance). **Confidence**
(High / Medium / Low) ignores distance, so a far facility can still be well evidenced.

## Pipeline

`hc_care_finder` rebuilds the data layers from the share (about 10 minutes); `hc_full_refresh` adds the AI review and the confidence model:

```
Delta Share ──► hc_bronze (as received) ──► hc_silver (cleaned + facility_master) ──► hc_gold (evidence, trust, index, functions)
                 vf_* tables                 types, PIN codes, dedupe, flags              + dq_* scorecards and cleaning log
```

```bash
databricks bundle deploy -t free --profile <name>
databricks bundle run hc_full_refresh -t free --profile <name>
```

## Layout

| Path | What it is |
|---|---|
| `databricks.yml` | bundle: `free` target (default) and `hackathon` target; `share` variable |
| `resources/hc_full_refresh.job.yml` | runs the three jobs below in order |
| `resources/hc_care_finder.job.yml` | 1 · data: share → bronze → profile → clean → facility_master → gold index + SQL functions → Parquet export |
| `resources/hc_ai_review.job.yml` | 2 · first AI review (`gold/40`): risk-selected pairs, Llama 3.3 70B with quote checks → `care_finder_index_v2` |
| `resources/hc_confidence_model.job.yml` | 3 · labels (`gold/32`) → capability model (`gold/44`) → gap analysis (`gold/42`) + `find_care()` (`gold/43`) |
| `resources/care_finder.app.yml` | the care.in Databricks App (web page, API, phone agent) |
| `notebooks/00_setup/` | create schemas + landing volume |
| `notebooks/bronze/` | `01` copy the share tables · `02` external files from the landing volume |
| `notebooks/silver/` | `10` DQ profile · `11` auto-clean · `12` facility_master · `13`–`16` external sources · `17` facilities_curated · `18` facilities_clean + census population (Bryce) |
| `notebooks/gold/` | `20`–`29` location lookup, evidence, trust, index + SQL functions, demo, export, districts, corroboration, coverage, PM-JAY · `31` IHDS base rates · `32` LLM labels · `40` AI review · `41` external validation (not in a job) · `42` gap analysis · `43` find_care() · `44` capability model |
| `data/landing/` | outside data files, seeded into the landing volume by `bronze/02` ([sources and licences](data/landing/SOURCES.md)) |
| `scripts/` | `build_app.sh` (assemble the app), `create_secrets.sh` (secret scope) |
| `src/hc/` | shared library: `care` (Care Finder rules), `clean`, `profile`, `geo`, `io`, `naming`, `config`, `sources` |
| `notebooks/_setup.py` | `%run ../_setup` → `cfg`, helpers on the path |
| `backend/` | FastAPI decision engine over the gold Parquet export: `/api/recommend`, `/api/locations`, `/ws/live` (tests: `.venv/bin/pytest -q`) |
| `frontend/` | the care.in web page (React + Vite), built into the app by `scripts/build_app.sh` |
| `voice_agent/` | LiveKit phone agent (Gemini Live): greeter → provider / patient personas, grounded tools only |
| `docs/CHALLENGE.md` · `docs/CONFIDENCE_MODEL_SPEC.md` · `openspec/` | the brief and data findings, the confidence model design and results, product spec |

## Deploy it yourself

Everything (jobs, notebooks, model, app) is one Declarative Automation Bundle. It runs on Databricks
Free Edition with serverless compute only.

**Before you start**

1. A Databricks Free Edition workspace and a recent Databricks CLI:
   `brew tap databricks/tap && brew install databricks`, then
   `databricks auth login --host https://<your-workspace-host> --profile <name>`
2. **The challenge data.** Add the Virtue Foundation dataset from Databricks Marketplace so the catalog
   `databricks_virtue_foundation_dataset_dais_2026` exists. (Different catalog name? Set the bundle
   variable `share`.)
3. Node 18+ and npm, to build the web page.

The outside data files (National Health Portal directory, Census 2011, district boundaries, PM-JAY,
IHDS-II, Data For India) ship in [`data/landing/`](data/landing/SOURCES.md). The pipeline copies them
into the landing volume on its first run, so there is nothing to upload.

**Deploy and run**

```bash
scripts/create_secrets.sh <name>              # secret scope the app needs (voice keys optional, see below)
scripts/build_app.sh                          # builds the web page into build/care_finder_app
databricks bundle deploy -t free --profile <name>
databricks bundle run hc_full_refresh -t free --profile <name>   # data -> AI review -> model
databricks bundle run care_finder -t free --profile <name>       # start the app; prints its URL
```

`hc_full_refresh` runs three jobs in order: `hc_care_finder` (about 10 minutes), then `hc_ai_review` and
`hc_confidence_model`. The last two call Llama 3.3 70B through `ai_query` and take the longest; a rerun
skips batches that already finished.

**Voice (optional).** Without keys the app serves the website and API, and the Call button still dials our
hosted phone line. To run your own voice agent, export `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` and
`GOOGLE_API_KEY` before `create_secrets.sh`, and set `LIVEKIT_URL` and `CARE_FINDER_PHONE` in
`deploy/care_finder_app/app.yaml` to your LiveKit project.

**Notes.** The `free` target uses the catalog `workspace`, which every Free Edition workspace has. Some
notebooks (`silver/18`, `gold/41`–`44`) and `app.yaml` name it directly, so another catalog needs those
edited too. `bundle destroy` removes jobs and the app but never the schemas or tables.

No CLI? Create a Git folder from this repo and run the notebooks in the order `hc_full_refresh` does.

## Other tables worth knowing

* `hc_gold.dq_table_summary`, `hc_gold.dq_profile`: before/after data-quality scorecard (bronze vs silver)
* `hc_gold.dq_cleaning_log`: every automated cleaning decision, per column. Fix wrong calls with the
  `overrides_json` job parameter (types, keep_string, primary_key, rename, drop, null_tokens)
* `hc_gold.model_eval`, `model_eval_bands`, `model_stress_tests`: capability model (`gold/44`) results on held-out hospitals
* `hc_gold.district_service_gaps`: district x service access gap, NFHS-5 need and priority (`gold/42`)

## Tests

```bash
python3 tests/test_local.py
```
