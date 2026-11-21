# Kickoff runbook (Saturday)

## Friday night (done before kickoff)
- [ ] CLI installed + `databricks auth login` (both of us)
- [ ] `databricks bundle deploy -t free` and `bundle run hc_public_sources` succeeded
- [ ] `SELECT count(*) FROM workspace.hc_gold.county_context` returns ~3,144
- [ ] Glance at `hc_gold.dq_table_summary` to see the bronze vs silver numbers

## Kickoff status (Sat Nov 21)

The challenge is Care Finder (see [CHALLENGE.md](CHALLENGE.md)). The data arrived as a Delta Share and
is already in bronze and silver as `vf_*`. To reload it:

```bash
C=databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset
databricks jobs run-now --profile <p> --json "{\"job_id\": <hc_kickoff job id>, \"job_parameters\": {\"table_prefix\": \"vf_\",
  \"source_tables\": \"$C.facilities,$C.india_post_pincode_directory,$C.nfhs_5_district_health_indicators\"}}"
```

(`bundle run --params` can't pass a list that contains commas, so use `jobs run-now --json`. To find the
job id, run `databricks bundle summary -t free`.)

Next: silver fixes for facilities (states, shifted rows, PIN/coordinate checks), then gold
`facility_service_evidence` and `facility_trust` (see the spec's proposed approach).

## Hour 0-1: land the data (generic, for file drops)
1. Download whatever the organizers give us.
2. Upload it to `/Volumes/workspace/hc_bronze/landing/kickoff/` (Catalog Explorer → volume → Upload,
   or `databricks fs cp -r ./kickoff dbfs:/Volumes/workspace/hc_bronze/landing/kickoff --profile <p>`).
   - Data arrives as a table / Delta Share instead? Run `bronze/03` with `source_tables=<full.table.names>`.
   - Excel? Add `%pip install openpyxl` at the top of `bronze/03`.
3. `databricks bundle run hc_kickoff -t free --profile <p>` (or run the notebooks by hand).

## Hour 1-2: understand the mess
- `hc_gold.dq_table_summary` / `dq_profile` (layer = bronze): rows, % null, duplicates, worst columns.
- `hc_gold.dq_cleaning_log`: what the auto-cleaner decided. Fix wrong calls with `overrides_json`
  in `silver/11` (types, keep_string, primary_key, rename, drop, null_tokens) and re-run.
- Write down the grain of each table (one row per patient? encounter? facility-month?). Every later
  join depends on it.
- Find the geography: FIPS, ZIP, county name, hospital CCN, state? → `gold/21` links it to
  `county_context` and reports the match rate.

## Hour 2+: question → model → decision
- Pick the outcome that matters (death, readmission, overdose, missed care) and the lever a decision
  maker controls (where to put clinics, naloxone, staff, outreach).
- Build one gold table at the grain of the decision (one row per patient / county / facility) with the
  outcome column, then run `hc_model` on it (see README → Modeling). Check the leakage scan first; read
  `pred_<run>` sorted by `risk_rank` / `excess_rank` for the decision list.
- Keep the screenshots for the video: before/after DQ table, match rates, suppression bias.

## Messy-data checklist (healthcare specific)
- Small-cell suppression (counts 1-9 blanked out) is not random: it is concentrated in rural counties. Say so.
- Sentinels: -999, 999, 9999, 0 meaning "unknown"; dates like 1900-01-01 / 9999-12-31.
- Impossible values: age > 115, negative length of stay, discharge before admit.
- Mixed code systems: ICD-9 vs ICD-10, codes with and without dots, NDC 10 vs 11 digits.
- ZIP ≠ ZCTA; a ZIP can span counties (we keep the largest-land-share county and expose the share).
- Provisional data (VSRR overdose) is revised; note the `data_as_of` date.
