# Databricks notebook source
# MAGIC %md
# MAGIC **Silver 18 · facilities_silver_clean + census_2011_population** (by Bryce; copied from the workspace notebook
# MAGIC "Facility Data Cleaning Workbook"). Runs after `silver/17_facilities_curated` in job `hc_care_finder`.

# COMMAND ----------

# DBTITLE 1,Overview
# MAGIC %md
# MAGIC # Facility Data Cleaning Workbook
# MAGIC
# MAGIC Cleans `workspace.hc_silver.facilities_silver_curated` (source of truth — one cleaned row per facility; `*_source` columns record where each field came from) using its bronze input `workspace.hc_bronze.ext_nhp_hospital_directory` (raw strings, `'0'` means missing). Result: `workspace.hc_silver.facilities_silver_clean`.
# MAGIC
# MAGIC | Cell | Task | Key outputs |
# MAGIC | --- | --- | --- |
# MAGIC | Task 1 | Canonicalize services arrays (`services_any/vf/directory`), recompute `services_corroborated` | mapping table, before/after distinct counts |
# MAGIC | Task 2 | Geocode verification: India bbox + district bbox, resolve conflicting coordinate sources | `coord_quality`, `coord_source`, `coord_conflict`, QA report per state |
# MAGIC | Task 3 | Doctor/bed number audit from bronze, cleaned numeric columns | pattern audit, `doctors_clean` / `beds_clean` |
# MAGIC | Task 4 | Assemble and write the clean table | `facilities_silver_clean` + verification |
# MAGIC | Task 5 | Census 2011 population (from `2011_Census_india.xlsx` in `hc_bronze.landing`), doctors/beds per 100,000 by state | `census_2011_population` table + per-100k report |
# MAGIC
# MAGIC Run cells in order — later cells reuse temp views (`svc_clean`, `geo_final`, `doc_final`) built earlier.

# COMMAND ----------

# DBTITLE 1,Install openpyxl (needed to read 2011_Census_india.xlsx)
# MAGIC %pip install openpyxl

# COMMAND ----------

# DBTITLE 1,Task 1 — Canonicalize services arrays
# MAGIC %sql
# MAGIC -- ============================================================
# MAGIC -- TASK 1 — Canonicalize the services arrays
# MAGIC -- services_any / services_vf / services_directory / services_corroborated
# MAGIC -- Normalization: trim -> lowercase -> punctuation to '_' -> collapse repeated '_'
# MAGIC --                -> synonym rules. Any label containing '24x7', '24 hrs', '24 hours',
# MAGIC --                '24/7', '24x7x365', 'round the clock' collapses to '24_7_services'.
# MAGIC -- ============================================================
# MAGIC
# MAGIC -- 1a. inventory of raw labels across the three source arrays
# MAGIC CREATE OR REPLACE TEMP VIEW svc_raw_labels AS
# MAGIC SELECT DISTINCT raw_label FROM (
# MAGIC   SELECT explode(services_any) AS raw_label FROM workspace.hc_silver.facilities_silver_curated WHERE services_any IS NOT NULL
# MAGIC   UNION
# MAGIC   SELECT explode(services_vf) AS raw_label FROM workspace.hc_silver.facilities_silver_curated WHERE services_vf IS NOT NULL
# MAGIC   UNION
# MAGIC   SELECT explode(services_directory) AS raw_label FROM workspace.hc_silver.facilities_silver_curated WHERE services_directory IS NOT NULL
# MAGIC );
# MAGIC
# MAGIC -- 1b. the mapping table actually applied (raw -> canonical)
# MAGIC SELECT
# MAGIC   raw_label,
# MAGIC   CASE
# MAGIC     WHEN lower(raw_label) LIKE '%24x7%' OR lower(raw_label) LIKE '%24 x7%' OR lower(raw_label) LIKE '%24 x 7%'
# MAGIC       OR lower(raw_label) LIKE '%24 hrs%' OR lower(raw_label) LIKE '%24hours%' OR lower(raw_label) LIKE '%24 hours%'
# MAGIC       OR lower(raw_label) LIKE '%24x7x365%' OR lower(raw_label) LIKE '%24/7%'
# MAGIC       OR lower(raw_label) LIKE '%round the clock%' OR lower(raw_label) LIKE '%round-the-clock%'
# MAGIC       THEN '24_7_services'
# MAGIC     ELSE lower(regexp_replace(regexp_replace(trim(raw_label), '[^0-9a-zA-Z]+', '_'), '_+', '_'))
# MAGIC   END AS canonical_label
# MAGIC FROM svc_raw_labels
# MAGIC ORDER BY canonical_label, raw_label;
# MAGIC
# MAGIC -- 1c. apply canonicalization; recompute services_corroborated =
# MAGIC --     service present in BOTH source arrays (vf AND directory) = confirmed by more than one source
# MAGIC CREATE OR REPLACE TEMP VIEW svc_clean AS
# MAGIC SELECT
# MAGIC   f.* EXCEPT (services_any, services_vf, services_directory, services_corroborated),
# MAGIC   array_sort(array_distinct(filter(
# MAGIC     transform(services_any, s -> CASE
# MAGIC       WHEN lower(s) LIKE '%24x7%' OR lower(s) LIKE '%24 x7%' OR lower(s) LIKE '%24 x 7%'
# MAGIC         OR lower(s) LIKE '%24 hrs%' OR lower(s) LIKE '%24hours%' OR lower(s) LIKE '%24 hours%'
# MAGIC         OR lower(s) LIKE '%24x7x365%' OR lower(s) LIKE '%24/7%'
# MAGIC         OR lower(s) LIKE '%round the clock%' OR lower(s) LIKE '%round-the-clock%'
# MAGIC         THEN '24_7_services'
# MAGIC       ELSE lower(regexp_replace(regexp_replace(trim(s), '[^0-9a-zA-Z]+', '_'), '_+', '_'))
# MAGIC     END),
# MAGIC     x -> x IS NOT NULL AND x <> ''))) AS services_any,
# MAGIC   array_sort(array_distinct(filter(
# MAGIC     transform(services_vf, s -> CASE
# MAGIC       WHEN lower(s) LIKE '%24x7%' OR lower(s) LIKE '%24 x7%' OR lower(s) LIKE '%24 x 7%'
# MAGIC         OR lower(s) LIKE '%24 hrs%' OR lower(s) LIKE '%24hours%' OR lower(s) LIKE '%24 hours%'
# MAGIC         OR lower(s) LIKE '%24x7x365%' OR lower(s) LIKE '%24/7%'
# MAGIC         OR lower(s) LIKE '%round the clock%' OR lower(s) LIKE '%round-the-clock%'
# MAGIC         THEN '24_7_services'
# MAGIC       ELSE lower(regexp_replace(regexp_replace(trim(s), '[^0-9a-zA-Z]+', '_'), '_+', '_'))
# MAGIC     END),
# MAGIC     x -> x IS NOT NULL AND x <> ''))) AS services_vf,
# MAGIC   array_sort(array_distinct(filter(
# MAGIC     transform(services_directory, s -> CASE
# MAGIC       WHEN lower(s) LIKE '%24x7%' OR lower(s) LIKE '%24 x7%' OR lower(s) LIKE '%24 x 7%'
# MAGIC         OR lower(s) LIKE '%24 hrs%' OR lower(s) LIKE '%24hours%' OR lower(s) LIKE '%24 hours%'
# MAGIC         OR lower(s) LIKE '%24x7x365%' OR lower(s) LIKE '%24/7%'
# MAGIC         OR lower(s) LIKE '%round the clock%' OR lower(s) LIKE '%round-the-clock%'
# MAGIC         THEN '24_7_services'
# MAGIC       ELSE lower(regexp_replace(regexp_replace(trim(s), '[^0-9a-zA-Z]+', '_'), '_+', '_'))
# MAGIC     END),
# MAGIC     x -> x IS NOT NULL AND x <> ''))) AS services_directory,
# MAGIC   array_sort(array_distinct(array_intersect(
# MAGIC     filter(transform(services_vf, s -> CASE
# MAGIC       WHEN lower(s) LIKE '%24x7%' OR lower(s) LIKE '%24 x7%' OR lower(s) LIKE '%24 x 7%'
# MAGIC         OR lower(s) LIKE '%24 hrs%' OR lower(s) LIKE '%24hours%' OR lower(s) LIKE '%24 hours%'
# MAGIC         OR lower(s) LIKE '%24x7x365%' OR lower(s) LIKE '%24/7%'
# MAGIC         OR lower(s) LIKE '%round the clock%' OR lower(s) LIKE '%round-the-clock%'
# MAGIC         THEN '24_7_services'
# MAGIC       ELSE lower(regexp_replace(regexp_replace(trim(s), '[^0-9a-zA-Z]+', '_'), '_+', '_'))
# MAGIC     END), x -> x IS NOT NULL AND x <> ''),
# MAGIC     filter(transform(services_directory, s -> CASE
# MAGIC       WHEN lower(s) LIKE '%24x7%' OR lower(s) LIKE '%24 x7%' OR lower(s) LIKE '%24 x 7%'
# MAGIC         OR lower(s) LIKE '%24 hrs%' OR lower(s) LIKE '%24hours%' OR lower(s) LIKE '%24 hours%'
# MAGIC         OR lower(s) LIKE '%24x7x365%' OR lower(s) LIKE '%24/7%'
# MAGIC         OR lower(s) LIKE '%round the clock%' OR lower(s) LIKE '%round-the-clock%'
# MAGIC         THEN '24_7_services'
# MAGIC       ELSE lower(regexp_replace(regexp_replace(trim(s), '[^0-9a-zA-Z]+', '_'), '_+', '_'))
# MAGIC     END), x -> x IS NOT NULL AND x <> '')
# MAGIC   ))) AS services_corroborated
# MAGIC FROM workspace.hc_silver.facilities_silver_curated f;
# MAGIC
# MAGIC -- 1d. before/after distinct-value counts
# MAGIC SELECT
# MAGIC   (SELECT COUNT(*) FROM svc_raw_labels) AS distinct_labels_before,
# MAGIC   (SELECT COUNT(DISTINCT c) FROM (
# MAGIC      SELECT explode(services_any) AS c FROM svc_clean
# MAGIC      UNION
# MAGIC      SELECT explode(services_vf) FROM svc_clean
# MAGIC      UNION
# MAGIC      SELECT explode(services_directory) FROM svc_clean)) AS distinct_labels_after;
# MAGIC
# MAGIC -- 1e. corroborated coverage before vs after, plus the new per-service counts
# MAGIC SELECT
# MAGIC   (SELECT COUNT(*) FROM workspace.hc_silver.facilities_silver_curated
# MAGIC      WHERE size(coalesce(services_corroborated, array())) > 0) AS rows_corroborated_before,
# MAGIC   (SELECT COUNT(*) FROM svc_clean WHERE size(services_corroborated) > 0) AS rows_corroborated_after;
# MAGIC
# MAGIC SELECT label, COUNT(*) AS facilities
# MAGIC FROM (SELECT explode(services_corroborated) AS label FROM svc_clean)
# MAGIC GROUP BY 1 ORDER BY facilities DESC;
# MAGIC
# MAGIC -- 1f. where the messy phrasing lives: bronze raw 'facilities' strings with 24-hour variants
# MAGIC SELECT
# MAGIC   COUNT(*) AS bronze_rows,
# MAGIC   SUM(CASE WHEN lower(coalesce(facilities, '')) LIKE '%24x7%'
# MAGIC         OR lower(coalesce(facilities, '')) LIKE '%24 hrs%'
# MAGIC         OR lower(coalesce(facilities, '')) LIKE '%24 hours%'
# MAGIC         OR lower(coalesce(facilities, '')) LIKE '%24/7%'
# MAGIC         OR lower(coalesce(facilities, '')) LIKE '%round the clock%'
# MAGIC         THEN 1 ELSE 0 END) AS rows_with_24h_phrasing
# MAGIC FROM workspace.hc_bronze.ext_nhp_hospital_directory;

# COMMAND ----------

# DBTITLE 1,Task 2 — Geocode verification
# MAGIC %sql
# MAGIC -- ============================================================
# MAGIC -- TASK 2 — Geocode verification
# MAGIC -- Candidates per facility:
# MAGIC --   curated lat/lon      (PIN-code centroid, or a listed geocode when location_source says so)
# MAGIC --   vf_facilities        (VF 'listed coordinates' — join facility_id = unique_id)
# MAGIC --   bronze location_coordinates ('lat, lon' string from the NHP directory — join nhp_id = sr_no)
# MAGIC -- Validation: India bbox (lat 6–37.5, lon 68–97.5) AND district bbox from
# MAGIC --   district_boundaries_2011 (0.05 deg tolerance; state bbox fallback when the district
# MAGIC --   code does not join).
# MAGIC -- Resolution: curated-listed > VF listed > NHP listed > PIN centroid;
# MAGIC --   VF coordinates are used only when they fall inside the district AND within ~10 km of
# MAGIC --   the PIN centroid (or when the PIN point itself fails validation) — VF points far from
# MAGIC --   the PIN area are treated as suspect and not adopted;
# MAGIC --   if nothing validates but the district is known -> district centroid (downgraded);
# MAGIC --   else coords_valid = false (failed).
# MAGIC -- ============================================================
# MAGIC
# MAGIC CREATE OR REPLACE TEMP VIEW geo_cand AS
# MAGIC SELECT
# MAGIC   f.*,
# MAGIC   v.latitude AS vf_lat, v.longitude AS vf_lon,
# MAGIC   try_cast(regexp_extract(n.location_coordinates, '^ *(-?[0-9]+(\\.[0-9]+)?) *,', 1) AS DOUBLE) AS nhp_lat,
# MAGIC   try_cast(regexp_extract(n.location_coordinates, ', *(-?[0-9]+(\\.[0-9]+)?) *$', 1) AS DOUBLE) AS nhp_lon,
# MAGIC   bb.district AS bb_district,
# MAGIC   bb.centroid_lat AS dist_centroid_lat, bb.centroid_lon AS dist_centroid_lon,
# MAGIC   CASE WHEN bb.district_code IS NOT NULL
# MAGIC        THEN named_struct('lat_min', bb.bbox_lat_min - 0.05, 'lat_max', bb.bbox_lat_max + 0.05,
# MAGIC                          'lon_min', bb.bbox_lon_min - 0.05, 'lon_max', bb.bbox_lon_max + 0.05)
# MAGIC        ELSE named_struct('lat_min', sb.lat_min, 'lat_max', sb.lat_max,
# MAGIC                          'lon_min', sb.lon_min, 'lon_max', sb.lon_max) END AS box
# MAGIC FROM svc_clean f
# MAGIC LEFT JOIN workspace.hc_silver.vf_facilities v ON f.facility_id = v.unique_id
# MAGIC LEFT JOIN workspace.hc_bronze.ext_nhp_hospital_directory n ON f.nhp_id = n.sr_no
# MAGIC LEFT JOIN workspace.hc_silver.district_boundaries_2011 bb ON f.district_code_2011 = bb.district_code
# MAGIC LEFT JOIN (
# MAGIC   SELECT lower(state) AS state_l,
# MAGIC          min(bbox_lat_min) - 0.05 AS lat_min, max(bbox_lat_max) + 0.05 AS lat_max,
# MAGIC          min(bbox_lon_min) - 0.05 AS lon_min, max(bbox_lon_max) + 0.05 AS lon_max
# MAGIC   FROM workspace.hc_silver.district_boundaries_2011
# MAGIC   GROUP BY lower(state)
# MAGIC ) sb ON lower(f.state) = sb.state_l;
# MAGIC
# MAGIC CREATE OR REPLACE TEMP VIEW geo_box AS
# MAGIC SELECT *,
# MAGIC   box.lat_min AS box_lat_min, box.lat_max AS box_lat_max,
# MAGIC   box.lon_min AS box_lon_min, box.lon_max AS box_lon_max
# MAGIC FROM geo_cand;
# MAGIC
# MAGIC CREATE OR REPLACE TEMP VIEW geo_eval AS
# MAGIC SELECT *,
# MAGIC   coalesce(box_lat_min IS NOT NULL AND lat IS NOT NULL
# MAGIC     AND lat BETWEEN 6.0 AND 37.5 AND lon BETWEEN 68.0 AND 97.5
# MAGIC     AND lat BETWEEN box_lat_min AND box_lat_max AND lon BETWEEN box_lon_min AND box_lon_max, false) AS cur_ok,
# MAGIC   coalesce(box_lat_min IS NOT NULL AND vf_lat IS NOT NULL
# MAGIC     AND vf_lat BETWEEN 6.0 AND 37.5 AND vf_lon BETWEEN 68.0 AND 97.5
# MAGIC     AND vf_lat BETWEEN box_lat_min AND box_lat_max AND vf_lon BETWEEN box_lon_min AND box_lon_max, false) AS vf_ok,
# MAGIC   coalesce(box_lat_min IS NOT NULL AND nhp_lat IS NOT NULL
# MAGIC     AND nhp_lat BETWEEN 6.0 AND 37.5 AND nhp_lon BETWEEN 68.0 AND 97.5
# MAGIC     AND nhp_lat BETWEEN box_lat_min AND box_lat_max AND nhp_lon BETWEEN box_lon_min AND box_lon_max, false) AS nhp_ok
# MAGIC FROM geo_box;
# MAGIC
# MAGIC CREATE OR REPLACE TEMP VIEW geo_res AS
# MAGIC SELECT *,
# MAGIC   CASE
# MAGIC     WHEN cur_ok AND lower(coalesce(location_source, '')) LIKE '%listed%' THEN 'curated_listed'
# MAGIC     WHEN vf_ok AND (
# MAGIC          coalesce(lat IS NOT NULL AND 111.32 * sqrt(pow(lat - vf_lat, 2)
# MAGIC               + pow(cos(radians((lat + vf_lat) / 2)) * (lon - vf_lon), 2)) <= 10, false)
# MAGIC          OR NOT cur_ok
# MAGIC        ) THEN 'vf_listed'
# MAGIC     WHEN nhp_ok THEN 'nhp_listed'
# MAGIC     WHEN cur_ok THEN 'pin_centroid'
# MAGIC     ELSE NULL
# MAGIC   END AS chosen_src
# MAGIC FROM geo_eval;
# MAGIC
# MAGIC CREATE OR REPLACE TEMP VIEW geo_final AS
# MAGIC SELECT
# MAGIC   g.*,
# MAGIC   CASE g.chosen_src
# MAGIC     WHEN 'curated_listed' THEN g.lat
# MAGIC     WHEN 'vf_listed' THEN g.vf_lat
# MAGIC     WHEN 'nhp_listed' THEN g.nhp_lat
# MAGIC     WHEN 'pin_centroid' THEN g.lat
# MAGIC     ELSE g.dist_centroid_lat
# MAGIC   END AS lat_final,
# MAGIC   CASE g.chosen_src
# MAGIC     WHEN 'curated_listed' THEN g.lon
# MAGIC     WHEN 'vf_listed' THEN g.vf_lon
# MAGIC     WHEN 'nhp_listed' THEN g.nhp_lon
# MAGIC     WHEN 'pin_centroid' THEN g.lon
# MAGIC     ELSE g.dist_centroid_lon
# MAGIC   END AS lon_final,
# MAGIC   (g.chosen_src IS NOT NULL OR g.dist_centroid_lat IS NOT NULL) AS coords_valid_final,
# MAGIC   CASE
# MAGIC     WHEN g.chosen_src IS NULL AND g.bb_district IS NOT NULL THEN 'district_centroid'
# MAGIC     WHEN g.chosen_src IS NULL THEN 'failed'
# MAGIC     WHEN g.chosen_src = 'pin_centroid' THEN 'pin_area'
# MAGIC     ELSE 'exact'
# MAGIC   END AS coord_quality,
# MAGIC   coalesce(g.chosen_src,
# MAGIC     CASE WHEN g.bb_district IS NOT NULL THEN 'district_centroid' ELSE 'none' END) AS coord_source,
# MAGIC   nullif(concat_ws(' | ',
# MAGIC     CASE WHEN g.lat IS NOT NULL AND g.vf_lat IS NOT NULL
# MAGIC           AND (abs(g.lat - g.vf_lat) > 0.01 OR abs(g.lon - g.vf_lon) > 0.01)
# MAGIC          THEN concat('curated_vs_vf_',
# MAGIC                CAST(round(111.32 * sqrt(pow(g.lat - g.vf_lat, 2)
# MAGIC                  + pow(cos(radians((g.lat + g.vf_lat) / 2)) * (g.lon - g.vf_lon), 2)), 1) AS STRING), 'km') END,
# MAGIC     CASE WHEN g.lat IS NOT NULL AND g.nhp_lat IS NOT NULL
# MAGIC           AND (abs(g.lat - g.nhp_lat) > 0.01 OR abs(g.lon - g.nhp_lon) > 0.01)
# MAGIC          THEN concat('curated_vs_nhp_',
# MAGIC                CAST(round(111.32 * sqrt(pow(g.lat - g.nhp_lat, 2)
# MAGIC                  + pow(cos(radians((g.lat + g.nhp_lat) / 2)) * (g.lon - g.nhp_lon), 2)), 1) AS STRING), 'km') END,
# MAGIC     CASE WHEN g.vf_lat IS NOT NULL AND g.nhp_lat IS NOT NULL
# MAGIC           AND (abs(g.vf_lat - g.nhp_lat) > 0.01 OR abs(g.vf_lon - g.nhp_lon) > 0.01)
# MAGIC          THEN concat('vf_vs_nhp_',
# MAGIC                CAST(round(111.32 * sqrt(pow(g.vf_lat - g.nhp_lat, 2)
# MAGIC                  + pow(cos(radians((g.vf_lat + g.nhp_lat) / 2)) * (g.vf_lon - g.nhp_lon), 2)), 1) AS STRING), 'km') END
# MAGIC   ), '') AS coord_conflict,
# MAGIC   g.lat AS lat_input,
# MAGIC   g.lon AS lon_input
# MAGIC FROM geo_res g;
# MAGIC
# MAGIC -- 2a. overall QA outcome
# MAGIC SELECT
# MAGIC   COUNT(*) AS facilities,
# MAGIC   SUM(CASE WHEN coord_quality = 'exact' THEN 1 ELSE 0 END) AS exact,
# MAGIC   SUM(CASE WHEN coord_quality = 'pin_area' THEN 1 ELSE 0 END) AS pin_area,
# MAGIC   SUM(CASE WHEN coord_quality = 'district_centroid' THEN 1 ELSE 0 END) AS district_centroid,
# MAGIC   SUM(CASE WHEN coord_quality = 'failed' THEN 1 ELSE 0 END) AS failed,
# MAGIC   SUM(CASE WHEN coords_valid_final AND NOT coords_valid THEN 1 ELSE 0 END) AS promoted_to_valid,
# MAGIC   SUM(CASE WHEN coords_valid AND NOT coords_valid_final THEN 1 ELSE 0 END) AS demoted_to_invalid,
# MAGIC   SUM(CASE WHEN coord_source IN ('vf_listed', 'nhp_listed') THEN 1 ELSE 0 END) AS switched_to_listed_coords,
# MAGIC   SUM(CASE WHEN coord_conflict IS NOT NULL THEN 1 ELSE 0 END) AS with_recorded_conflict
# MAGIC FROM geo_final;
# MAGIC
# MAGIC -- 2b. QA report per state: rejects and downgrades
# MAGIC SELECT
# MAGIC   state,
# MAGIC   COUNT(*) AS facilities,
# MAGIC   SUM(CASE WHEN coord_quality = 'exact' THEN 1 ELSE 0 END) AS exact,
# MAGIC   SUM(CASE WHEN coord_quality = 'pin_area' THEN 1 ELSE 0 END) AS pin_area,
# MAGIC   SUM(CASE WHEN coord_quality = 'district_centroid' THEN 1 ELSE 0 END) AS district_centroid,
# MAGIC   SUM(CASE WHEN coord_quality = 'failed' THEN 1 ELSE 0 END) AS failed,
# MAGIC   SUM(CASE WHEN coords_valid_final AND NOT coords_valid THEN 1 ELSE 0 END) AS promoted_to_valid,
# MAGIC   SUM(CASE WHEN coords_valid AND NOT coords_valid_final THEN 1 ELSE 0 END) AS demoted_to_invalid,
# MAGIC   SUM(CASE WHEN coord_conflict IS NOT NULL THEN 1 ELSE 0 END) AS coord_conflicts
# MAGIC FROM geo_final
# MAGIC GROUP BY state
# MAGIC ORDER BY facilities DESC;
# MAGIC
# MAGIC -- 2c. samples: facilities rescued by switching to a corroborated listed source
# MAGIC SELECT name, state, district, location_source, lat_input, lon_input, lat_final, lon_final, coord_source, coord_conflict
# MAGIC FROM geo_final WHERE coord_source IN ('vf_listed', 'nhp_listed') LIMIT 8;
# MAGIC
# MAGIC -- 2d. samples: failed validation (coords_valid will be false)
# MAGIC SELECT name, state, district, location_source, lat_input, lon_input, coord_quality, coord_conflict
# MAGIC FROM geo_final WHERE coord_quality = 'failed' LIMIT 8;

# COMMAND ----------

# DBTITLE 1,Task 3 — Doctor and bed numbers
# MAGIC %sql
# MAGIC -- ============================================================
# MAGIC -- TASK 3 — Doctor (and bed) numbers from bronze NHP directory
# MAGIC -- number_doctor / total_num_beds / num_mediconsultant_or_expert are dirty strings, '0' = missing.
# MAGIC -- ============================================================
# MAGIC
# MAGIC -- 3a. raw value patterns — why per-state doctor sums are ~zero
# MAGIC SELECT
# MAGIC   CASE
# MAGIC     WHEN number_doctor IS NULL THEN 'null'
# MAGIC     WHEN trim(number_doctor) = '' THEN 'blank'
# MAGIC     WHEN trim(number_doctor) = '0' THEN 'zero (missing)'
# MAGIC     WHEN number_doctor RLIKE '^[0-9]+$' THEN 'integer'
# MAGIC     WHEN number_doctor RLIKE '^[0-9]+ *(-|to) *[0-9]+$' THEN 'range'
# MAGIC     ELSE 'other_text'
# MAGIC   END AS number_doctor_pattern,
# MAGIC   COUNT(*) AS rows
# MAGIC FROM workspace.hc_bronze.ext_nhp_hospital_directory
# MAGIC GROUP BY 1 ORDER BY rows DESC;
# MAGIC
# MAGIC SELECT
# MAGIC   CASE
# MAGIC     WHEN num_mediconsultant_or_expert IS NULL THEN 'null'
# MAGIC     WHEN trim(num_mediconsultant_or_expert) = '' THEN 'blank'
# MAGIC     WHEN trim(num_mediconsultant_or_expert) = '0' THEN 'zero (missing)'
# MAGIC     WHEN num_mediconsultant_or_expert RLIKE '^[0-9]+$' THEN 'integer'
# MAGIC     ELSE 'other_text'
# MAGIC   END AS mediconsultant_pattern,
# MAGIC   COUNT(*) AS rows
# MAGIC FROM workspace.hc_bronze.ext_nhp_hospital_directory
# MAGIC GROUP BY 1 ORDER BY rows DESC;
# MAGIC
# MAGIC -- 3b. the ONLY non-zero doctor values in the whole directory
# MAGIC SELECT sr_no, hospital_name, state, number_doctor, num_mediconsultant_or_expert, total_num_beds
# MAGIC FROM workspace.hc_bronze.ext_nhp_hospital_directory
# MAGIC WHERE number_doctor RLIKE '^[0-9]+$' AND CAST(number_doctor AS INT) > 0;
# MAGIC
# MAGIC -- 3c. total_num_beds garbage: non-numeric values (phone numbers pasted into the column)
# MAGIC SELECT DISTINCT total_num_beds
# MAGIC FROM workspace.hc_bronze.ext_nhp_hospital_directory
# MAGIC WHERE total_num_beds IS NOT NULL AND trim(total_num_beds) NOT IN ('', '0')
# MAGIC   AND NOT total_num_beds RLIKE '^[0-9]+$';
# MAGIC
# MAGIC -- 3d. cleaned numeric views: '0'/blank/non-numeric -> NULL
# MAGIC CREATE OR REPLACE TEMP VIEW nhp_numeric AS
# MAGIC SELECT
# MAGIC   sr_no, state,
# MAGIC   CASE WHEN trim(number_doctor) RLIKE '^[0-9]+$' AND try_cast(number_doctor AS INT) > 0
# MAGIC        THEN try_cast(number_doctor AS INT) END AS doctors_nhp,
# MAGIC   CASE WHEN trim(total_num_beds) RLIKE '^[0-9]+$' AND try_cast(total_num_beds AS INT) BETWEEN 1 AND 10000
# MAGIC        THEN try_cast(total_num_beds AS INT) END AS beds_nhp
# MAGIC FROM workspace.hc_bronze.ext_nhp_hospital_directory;
# MAGIC
# MAGIC -- 3e. per-state sums from bronze — confirms the near-zero picture
# MAGIC SELECT state, SUM(doctors_nhp) AS sum_doctors_nhp, SUM(beds_nhp) AS sum_beds_nhp
# MAGIC FROM nhp_numeric
# MAGIC GROUP BY state
# MAGIC ORDER BY sum_doctors_nhp DESC NULLS LAST LIMIT 12;
# MAGIC
# MAGIC -- 3f. final cleaned doctors/beds: curated (VF-enriched) first, bronze NHP as fallback
# MAGIC CREATE OR REPLACE TEMP VIEW doc_final AS
# MAGIC SELECT
# MAGIC   f.curated_id,
# MAGIC   f.doctors AS doctors_curated, f.doctors_source AS doctors_source_curated,
# MAGIC   f.beds AS beds_curated, f.beds_source AS beds_source_curated,
# MAGIC   n.doctors_nhp, n.beds_nhp,
# MAGIC   coalesce(nullif(f.doctors, 0), n.doctors_nhp) AS doctors_clean,
# MAGIC   coalesce(nullif(f.beds, 0), n.beds_nhp) AS beds_clean
# MAGIC FROM workspace.hc_silver.facilities_silver_curated f
# MAGIC LEFT JOIN nhp_numeric n ON f.nhp_id = n.sr_no;
# MAGIC
# MAGIC SELECT
# MAGIC   COUNT(*) AS facilities,
# MAGIC   SUM(CASE WHEN doctors_clean IS NOT NULL THEN 1 ELSE 0 END) AS doctors_available,
# MAGIC   SUM(CASE WHEN doctors_curated IS NOT NULL AND doctors_curated <> 0 THEN 1 ELSE 0 END) AS doctors_from_curated,
# MAGIC   SUM(CASE WHEN doctors_nhp IS NOT NULL THEN 1 ELSE 0 END) AS doctors_from_nhp,
# MAGIC   SUM(CASE WHEN beds_clean IS NOT NULL THEN 1 ELSE 0 END) AS beds_available
# MAGIC FROM doc_final;
# MAGIC
# MAGIC -- 3g. population context: NO census/population counts table exists in the workspace —
# MAGIC --     doctors per 100,000 population per state cannot be computed yet.
# MAGIC --     Available state-level benchmark (Data For India 2023, ratios only):
# MAGIC SELECT state, healthcare_professionals,
# MAGIC   healthcare_professionals_per_10_000_persons,
# MAGIC   allopathic_doctors_per_10_000_persons,
# MAGIC   ayush_doctors_per_10_000_persons
# MAGIC FROM workspace.hc_bronze.ext_healthcare_professionals_for_every_10_000_people_2023_data_for_india
# MAGIC LIMIT 8;

# COMMAND ----------

# DBTITLE 1,Task 4 — Write facilities_silver_clean
# MAGIC %sql
# MAGIC -- ============================================================
# MAGIC -- TASK 4 — Assemble and write the cleaned table
# MAGIC -- workspace.hc_silver.facilities_silver_clean
# MAGIC -- ============================================================
# MAGIC
# MAGIC CREATE OR REPLACE TABLE workspace.hc_silver.facilities_silver_clean AS
# MAGIC SELECT
# MAGIC   g.* EXCEPT (lat, lon, coords_valid,
# MAGIC               vf_lat, vf_lon, nhp_lat, nhp_lon, box,
# MAGIC               box_lat_min, box_lat_max, box_lon_min, box_lon_max,
# MAGIC               bb_district, dist_centroid_lat, dist_centroid_lon,
# MAGIC               cur_ok, vf_ok, nhp_ok, chosen_src, lat_final, lon_final, coords_valid_final,
# MAGIC               doctors, beds, doctors_source, beds_source),
# MAGIC   d.doctors_clean AS doctors,
# MAGIC   CASE WHEN d.doctors_curated IS NOT NULL AND d.doctors_curated <> 0 THEN d.doctors_source_curated
# MAGIC        WHEN d.doctors_nhp IS NOT NULL THEN 'nhp_directory' END AS doctors_source,
# MAGIC   CASE WHEN d.beds_clean IS NOT NULL AND d.beds_clean > 5000 THEN NULL ELSE d.beds_clean END AS beds,
# MAGIC   CASE WHEN d.beds_curated IS NOT NULL AND d.beds_curated <> 0 THEN d.beds_source_curated
# MAGIC        WHEN d.beds_nhp IS NOT NULL THEN 'nhp_directory' END AS beds_source,
# MAGIC   coalesce(d.beds_clean > 5000, false) AS beds_is_outlier,
# MAGIC   g.lat_final AS lat,
# MAGIC   g.lon_final AS lon,
# MAGIC   g.coords_valid_final AS coords_valid
# MAGIC FROM geo_final g
# MAGIC LEFT JOIN doc_final d ON g.curated_id = d.curated_id;
# MAGIC
# MAGIC -- verification: row preservation and column coverage
# MAGIC SELECT
# MAGIC   COUNT(*) AS rows_written,
# MAGIC   SUM(CASE WHEN coords_valid THEN 1 ELSE 0 END) AS coords_valid_rows,
# MAGIC   SUM(CASE WHEN lat IS NULL THEN 1 ELSE 0 END) AS null_lat_rows,
# MAGIC   SUM(CASE WHEN doctors IS NOT NULL THEN 1 ELSE 0 END) AS doctors_available,
# MAGIC   SUM(CASE WHEN beds IS NOT NULL THEN 1 ELSE 0 END) AS beds_available,
# MAGIC   SUM(CASE WHEN size(coalesce(services_corroborated, array())) > 0 THEN 1 ELSE 0 END) AS rows_with_corroborated_services
# MAGIC FROM workspace.hc_silver.facilities_silver_clean;
# MAGIC
# MAGIC SELECT coord_quality, COUNT(*) AS facilities
# MAGIC FROM workspace.hc_silver.facilities_silver_clean
# MAGIC GROUP BY 1 ORDER BY 2 DESC;
# MAGIC
# MAGIC -- spot check: rescued points now on corroborated listed coordinates
# MAGIC SELECT name, state, district, lat, lon, coord_quality, coord_source, coord_conflict
# MAGIC FROM workspace.hc_silver.facilities_silver_clean
# MAGIC WHERE coord_source IN ('vf_listed', 'nhp_listed') LIMIT 5;
# MAGIC
# MAGIC -- cleaned doctor/bed availability per state (from the VF-enriched curated fields)
# MAGIC SELECT state, SUM(doctors) AS doctors_total, SUM(beds) AS beds_total
# MAGIC FROM workspace.hc_silver.facilities_silver_clean
# MAGIC WHERE doctors IS NOT NULL OR beds IS NOT NULL
# MAGIC GROUP BY state ORDER BY doctors_total DESC NULLS LAST LIMIT 12;

# COMMAND ----------

# DBTITLE 1,Task 5 — Census population and doctors per 100k
# ============================================================
# TASK 5 — Census 2011 population -> doctors / beds per 100,000 by state
# Source: /Volumes/workspace/hc_bronze/landing/2011_Census_india.xlsx
# (Census of India 2011, table A-1: villages/towns/households/population/area)
# Requires the %pip openpyxl cell at the top to have been run.
# Notes:
#   * 2011 predates Telangana (2014): census districts 532-541 of undivided
#     Andhra Pradesh are the Telangana region, so state populations are
#     rebuilt from DISTRICT rows (Telangana split out, residual = AP).
#   * Doctor/bed counts come from ~3.6k facilities (VF-enriched), so
#     per-100k values are floors, not official totals.
# ============================================================
import pandas as pd

raw = pd.read_excel(
    "/Volumes/workspace/hc_bronze/landing/2011_Census_india.xlsx",
    skiprows=4, header=None,
    usecols=[0, 1, 2, 3, 4, 5, 9, 10, 11, 12, 13],
    names=["state_code", "district_code", "subdistrict_code", "state_name",
           "name", "tru", "households", "persons", "males", "females", "area_sq_km"],
).dropna(subset=["state_code"])

# 5a. keep 'Total' rows at district level (district != 000, sub-district = 00000)
tot = raw[raw.tru.astype(str).str.strip().str.lower() == "total"]
dist = tot[(tot.district_code.astype(str).str.strip() != "000") &
           (tot.subdistrict_code.astype(str).str.strip() == "00000")].copy()

# 5b. canonical state names (aligned with facilities_silver_clean spellings)
def canon(s):
    s = str(s).strip().upper().removesuffix("@&").strip()
    s = " AND ".join(p.strip() for p in s.split("&"))
    s = " ".join(s.split())
    if s == "NCT OF DELHI":
        s = "DELHI"
    return s.title()

dist["district_code_2011"] = dist.district_code.astype(str).str.strip().astype(int)
# district rows carry the literal 'STATE' in the state-name column: map state_code ->
# real state name using the state-level rows (district 000 / sub-district 00000)
state_names = (tot[(tot.district_code.astype(str).str.strip() == "000") &
                  (tot.subdistrict_code.astype(str).str.strip() == "00000")]
               .drop_duplicates(subset=["state_code"])
               .set_index("state_code")["name"].map(canon).to_dict())
dist["state_census"] = dist.state_code.map(state_names)
dist["state"] = dist.apply(
    lambda r: "Telangana" if (r.state_code == 28 and 532 <= r.district_code_2011 <= 541) else r.state_census,
    axis=1)
dist["district"] = dist.name.astype(str).str.replace("@&", "", regex=False).str.strip()
dist["in_telangana_region_2011"] = dist.state == "Telangana"

keep = dist[["state", "state_census", "district", "district_code_2011", "households",
            "persons", "males", "females", "area_sq_km", "in_telangana_region_2011"]]
print(f"district rows: {len(keep)} across {keep.state.nunique()} states/UTs")

# 5c. persist the district-level population table
spark.createDataFrame(keep).write.format("delta").mode("overwrite") \
    .saveAsTable("workspace.hc_silver.census_2011_population")

# 5d. doctors / beds per 100,000 population by state (census 2011 denominator)
spark.sql("""
WITH pop AS (
  SELECT lower(state) AS state_key, MAX(state) AS state, SUM(persons) AS population_2011
  FROM workspace.hc_silver.census_2011_population GROUP BY 1
  UNION ALL
  SELECT 'dadra and nagar haveli and daman and diu',
         'Dadra and Nagar Haveli and Daman and Diu',
         SUM(persons)
  FROM workspace.hc_silver.census_2011_population
  WHERE lower(state) IN ('dadra and nagar haveli', 'daman and diu')
),
fac AS (
  SELECT
    lower(regexp_replace(regexp_replace(lower(trim(state)), ' & ', ' and '), '^the ', '')) AS state_key,
    COUNT(*) AS facilities,
    SUM(doctors) AS doctors_listed,
    SUM(beds) AS beds_listed
  FROM workspace.hc_silver.facilities_silver_clean
  WHERE state IS NOT NULL
  GROUP BY 1
),
bench AS (
  SELECT lower(trim(state)) AS state_key,
         10 * try_cast(allopathic_doctors_per_10_000_persons AS DOUBLE) AS benchmark_doctors_per_100k
  FROM workspace.hc_bronze.ext_healthcare_professionals_for_every_10_000_people_2023_data_for_india
)
SELECT initcap(fac.state_key) AS state,
  facilities,
  CAST(pop.population_2011 AS BIGINT) AS population_2011,
  doctors_listed,
  ROUND(100000 * doctors_listed / pop.population_2011, 1) AS doctors_per_100k,
  beds_listed,
  ROUND(100000 * beds_listed / pop.population_2011, 1) AS beds_per_100k,
  ROUND(bench.benchmark_doctors_per_100k, 0) AS registered_allopathic_per_100k_benchmark
FROM fac
JOIN pop USING (state_key)
LEFT JOIN bench USING (state_key)
ORDER BY doctors_per_100k DESC NULLS LAST""").show(40, False)

# COMMAND ----------

# DBTITLE 1,Decisions needed
# MAGIC %md
# MAGIC ## Decisions needed from a human
# MAGIC
# MAGIC 1. **PIN-area points now validated**: rows previously marked invalid because their coordinates were PIN-code centroids (`location_source = 'PIN code area'`) are re-validated against their district bbox; passing rows become `coords_valid = true` with `coord_quality = 'pin_area'`. If the locator map should stay conservative, filter on `coord_quality = 'exact'` instead of `coords_valid`.
# MAGIC 2. **VF listed coordinates**: a VF coordinate is adopted only when it falls inside the facility's district AND within ~10 km of the PIN centroid (or when the PIN point itself fails validation). VF points far from the PIN area are treated as suspect and rejected; all disagreements are recorded in `coord_conflict`.
# MAGIC 3. **Doctor counts**: the NHP directory publishes essentially none (29,533 of 30,273 rows are `'0'`, the rest NULL, exactly one row says 11). Coverage comes from the VF-enriched `doctors` column (~3.6k facilities). Any state-level doctor analysis needs an external source (e.g. NMC doctor registry, state health department data).
# MAGIC 4. **Doctors per 100,000 — RESOLVED (Task 5)**: the uploaded `2011_Census_india.xlsx` is parsed into `workspace.hc_silver.census_2011_population` (640 districts, 36 states/UTs, total 1,210,854,977 = census India total). 2011 predates Telangana, so it is split from undivided Andhra Pradesh using census district codes 532-541. Note the caveat: numerators are VF-listed doctor counts (current, only ~3.6k facilities) over 2011 population denominators — these are floor estimates, best read alongside the `registered_allopathic_per_100k_benchmark` column from the Data For India 2023 table.
# MAGIC 5. **Implausible bed counts** (standard practice applied): values beyond a domain-plausibility bound are flagged and excluded rather than kept or capped — the largest hospitals worldwide are under ~10,000 beds and the largest in India ~3,000. Beds > 5,000 are marked `beds_is_outlier = true` and set to NULL in the `beds` column ('Harsh Hospital', Bihar = 200,000 was the main offender). Adjust the 5,000 threshold in the Task 4 cell if needed.