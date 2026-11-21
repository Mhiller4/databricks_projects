# Healthcare Datathon: Databricks pipeline

> Turn messy healthcare data into decisions that save lives.
> Team: Mekeli + Bryce · Submission due Sun Nov 22, 12:30 PM

A medallion pipeline that is ready **before** we see the organizers' data:

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
