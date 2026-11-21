# Care Finder: find the right care in India

> A patient needs a specific kind of care. Where should they go, and why should they trust that answer?
> CMU Datathon Fall 2026 · Virtue Foundation dataset · Team: Mekeli + Bryce · Due Sun Nov 22, 12:30 PM

**The challenge:** take a **service** (dialysis, emergency C-section, NICU, MRI, ...) and a **location**
(city, district, PIN code, or coordinates). Return the best facilities, each with **cited evidence** from
the facility text and an honest **confidence level**. The data is about 10,000 Indian facility records
extracted from web text, so every field is a claim to verify. The tool must run on Databricks Free
Edition and work for non-technical users such as community health workers and NGO coordinators.

* Full brief, requirements checklist and data findings: [docs/CHALLENGE.md](docs/CHALLENGE.md)
* Product requirements: [openspec/specs/care-finder/spec.md](openspec/specs/care-finder/spec.md)

### Challenge data in this workspace

| Delta Share table | Bronze (as received) | Silver (cleaned) |
|---|---|---|
| `facilities` (10,088) | `hc_bronze.vf_facilities` | `hc_silver.vf_facilities` (10,077, exact duplicates removed) |
| `india_post_pincode_directory` (165,627) | `hc_bronze.vf_india_post_pincode_directory` | `hc_silver.vf_india_post_pincode_directory` |
| `nfhs_5_district_health_indicators` (706) | `hc_bronze.vf_nfhs_5_district_health_indicators` | `hc_silver.vf_nfhs_5_district_health_indicators` |

The share is `databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset`. To reload it, use
`databricks jobs run-now` on `hc_kickoff` with job parameters `table_prefix=vf_` and
`source_tables=<the three full table names>`; the exact command is in [docs/KICKOFF_RUNBOOK.md](docs/KICKOFF_RUNBOOK.md).

### Care Finder gold layer (built Sat Nov 21)

`databricks bundle run hc_care_finder -t free --profile <p>` rebuilds everything (about 5 minutes). Rules
and weights are in [`src/hc/care.py`](src/hc/care.py).

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

> The US public-data pipeline below (`hc_public_sources` → `county_context`) was built before kickoff.
> It covers US counties, so it isn't part of the India submission. It still works, but it's parked.
> The generic pieces (bronze/silver ingestion, DQ profiling, the auto-cleaner, the model template) carry over.

## Pipeline

A medallion pipeline built before we saw the organizers' data:

* **Public context, pre-built:** 8 free federal datasets cleaned and joined into `hc_gold.county_context`
  (one row per US county, ~120 columns).
* **Kickoff data, auto-ingested:** drop any files in the landing volume. The pipeline reads them,
  profiles them, cleans them, and logs every cleaning decision.
* **Glue:** ZIP / FIPS / state + county name → county, so the kickoff data joins to the context.

```
landing volume ──► hc_bronze (as received) ──► hc_silver (clean, typed, keyed) ──► hc_gold (joined, scored)
 public/  kickoff/      all strings + lineage       types, FIPS/ZIP, dedupe          county_context, dq_*, model + decision outputs
```

## Layout

| Path | What it is |
|---|---|
| `databricks.yml` | bundle: `free` target (default) and `hackathon` target |
| `resources/hc_public_sources.job.yml` | job: fetch → bronze → silver → `county_context` → DQ profile |
| `resources/hc_kickoff.job.yml` | job: kickoff files → bronze → profile → auto-clean → profile |
| `src/hc/` | shared library (sources, naming, io, geo, clean, profile) |
| `notebooks/_setup.py` | `%run ../_setup` → `cfg`, helpers on the path |
| `notebooks/00_setup/` | create schemas + landing volume |
| `notebooks/bronze/` | `01` fetch public · `02` ingest public · `03` ingest kickoff files |
| `notebooks/silver/` | `10` DQ profile · `11` auto-clean kickoff · `12` clean public sources |
| `notebooks/gold/` | `20` county_context · `21` link kickoff data to counties · `30` model template |
| `resources/hc_model.job.yml` | job: any table + target → dummy / linear / LightGBM → SHAP → MLflow → gold decision tables |
| `scripts/fetch_public_sources.py` | laptop fallback if the workspace can't reach the internet |
| `docs/KICKOFF_RUNBOOK.md` | **Saturday-morning checklist** |

## Setup (once per person)

```bash
brew tap databricks/tap && brew trust databricks/tap && brew install databricks
databricks auth login --host https://<your-free-edition-host> --profile <name>
databricks bundle validate -t free --profile <name>
databricks bundle deploy   -t free --profile <name>
databricks bundle run hc_public_sources -t free --profile <name>     # ~10-15 min
```

If `fetch_public` fails (outbound internet blocked), run this on a laptop and re-run the job:

```bash
python3 scripts/fetch_public_sources.py --upload --profile <name>
```

No CLI? Everything also works from the UI: create a Git folder from this repo and run the notebooks
in order (`00_setup` → `bronze/01` → `02` → `silver/12` → `gold/20` → `silver/10`).

## Public sources

| Table | Publisher | Grain | Join key |
|---|---|---|---|
| `svi_county_2022` | CDC/ATSDR | county | FIPS |
| `places_county` | CDC | county × 40 health measures | FIPS |
| `overdose_county_vsrr` | CDC/NCHS | county × month | FIPS (unpadded) |
| `hpsa_primary_care`, `hpsa_mental_health` | HRSA | shortage designation | FIPS |
| `cms_hospital_general_info` | CMS | hospital | state + county name, ZIP |
| `usda_rucc_2023` | USDA ERS | county | FIPS |
| `zcta_county_xwalk_2020` | Census | ZIP × county | ZCTA → FIPS |

Details, caveats and URLs are in [`src/hc/sources.py`](src/hc/sources.py). Messiness found so far:
~47% of county-month overdose counts are suppressed (1-9 deaths); PLACES mixes 2022/2023 survey
years; ~60% of HPSA rows are withdrawn designations; CMS has no FIPS and 42% of hospitals have
no star rating.

## Output tables worth knowing

* `hc_gold.county_context`: the join target (column comments set for Genie)
* `hc_gold.dq_table_summary`, `hc_gold.dq_profile`: before/after data-quality scorecard
* `hc_gold.dq_cleaning_log`: every automated cleaning decision, per column
* `hc_bronze._column_map`: original source column names
* `hc_gold.pred_<run>`: per-row out-of-fold score, rank, and top 3 reasons (from `gold/30`)
* `hc_gold.model_leaderboard`, `hc_gold.model_feature_importance`: every model run, keyed by MLflow `run_id`

## Modeling

```bash
# default: counties with more overdose deaths than their profile predicts (split by state)
databricks bundle run hc_model -t free --profile <name>
# any other table / target
databricks bundle run hc_model -t free --profile <name> \
  --params source_table=<gold table>,target_col=<col>,id_cols=<ids>,exclude_cols=<leaky globs>,group_col=<col or blank>
```

Note: `--params` replaces a parameter's default, so pass `exclude_cols` in full each time.
Runs appear in MLflow under `/Users/<you>/hc_datathon_models`.

## Tests

```bash
python3 tests/test_local.py
```
