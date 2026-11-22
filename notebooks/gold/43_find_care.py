# Databricks notebook source
# MAGIC %md
# MAGIC # Gold 43 · Serving: `find_care(service, place)`, one front door for the phone line and Genie
# MAGIC
# MAGIC Run after `02_llm_review` (and `03_external_validation` if you have the external files).
# MAGIC
# MAGIC `find_care('c-section', 'Patna')` / `find_care('dialysis', '800001')` / `find_care('nicu', '25.6, 85.1')`
# MAGIC - resolves the service from words (service key, label, synonyms) and the place (PIN, post office, city,
# MAGIC   district, state or "lat, lon"), using Mekeli's `service_catalog` and `location_lookup`
# MAGIC - ranks on the AI-adjusted score from `care_finder_index_v2`, skipping facilities whose record says the
# MAGIC   service is not available / planned / referred out
# MAGIC - returns the evidence quote, cautions, guideline check, external verification and contact details
# MAGIC - if the place is not found, returns one row with `result_rank = 0` and `name = 'PLACE NOT FOUND'`
# MAGIC
# MAGIC Creates only new objects: `find_care()`, and an empty `facility_external_validation` if gold/41 has not run.

# COMMAND ----------

GOLD = "workspace.hc_gold"
# Use the model-scored index from gold/44 when it exists, else the AI-reviewed index from gold/40
INDEX_TABLE = f"{GOLD}.care_finder_index_final" if spark.catalog.tableExists(f"{GOLD}.care_finder_index_final") else f"{GOLD}.care_finder_index_v2"
EVIDENCE_SOURCE = "evidence_source" if INDEX_TABLE.endswith("_final") else "CASE WHEN reviewed THEN 'AI review' ELSE 'rules' END"
print("find_care will read:", INDEX_TABLE)

# External validation is optional: create an empty table so find_care() always compiles
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {GOLD}.facility_external_validation (
  facility_id STRING, service_key STRING, verification_level STRING, external_source STRING,
  external_name STRING, match_method STRING, match_score DOUBLE)
COMMENT 'External cross-checks (LaQshya certification, National Hospital Directory). Filled by gold/41_external_validation.'
""")

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE FUNCTION {GOLD}.find_care(
  q_service STRING COMMENT 'What care is needed, in words: c-section, dialysis, NICU, heart attack...',
  q_location STRING COMMENT 'PIN code, post office, town, city, district or state (optionally "place, state"), or "lat, lon"',
  top_n INT DEFAULT 3 COMMENT 'How many facilities to return',
  max_km DOUBLE DEFAULT 150 COMMENT 'Search radius in km')
RETURNS TABLE
COMMENT 'Find the Right Care: ranked facilities for a service near a place, with cited evidence, AI review, guideline check, cautions and contacts. result_rank = 0 means the place was not found.'
RETURN
WITH svc AS (
    SELECT service_key, label FROM {GOLD}.service_catalog
    WHERE service_key = lower(trim(q_service))
       OR array_contains(match_keys, regexp_replace(upper(q_service), '[^A-Z0-9]', ''))
       OR exists(synonyms, s -> lower(trim(q_service)) = lower(s))
       OR lower(trim(q_service)) = lower(label)
    LIMIT 1
  ),
  q AS (
    SELECT trim(q_location) AS raw,
           regexp_replace(upper(trim(split(q_location, ',')[0])), '[^A-Z0-9]', '') AS name_key,
           nullif(regexp_replace(upper(trim(get(split(q_location, ','), 1))), '[^A-Z0-9]', ''), '') AS state_key
  ),
  coords AS (
    SELECT concat('coordinates ', raw) AS display_name, try_cast(trim(split(raw, ',')[0]) AS DOUBLE) AS lat,
           try_cast(trim(get(split(raw, ','), 1)) AS DOUBLE) AS lon, 0 AS priority, CAST(1 AS BIGINT) AS n_points
    FROM q WHERE raw RLIKE '^ *-?[0-9]+([.][0-9]+)? *, *-?[0-9]+([.][0-9]+)? *$'
  ),
  exact AS (
    SELECT concat_ws(', ', l.display_name, l.state) AS display_name, l.lat, l.lon, l.priority, l.n_points
    FROM {GOLD}.location_lookup l CROSS JOIN q
    WHERE l.name_key = q.name_key AND (q.state_key IS NULL OR l.state_key = q.state_key)
  ),
  fuzzy AS (
    SELECT concat_ws(', ', l.display_name, l.state) AS display_name, l.lat, l.lon, l.priority + 10 AS priority, l.n_points
    FROM {GOLD}.location_lookup l CROSS JOIN q
    WHERE length(q.name_key) >= 4 AND l.name_key LIKE concat(q.name_key, '%') AND l.kind <> 'pin'
      AND (q.state_key IS NULL OR l.state_key = q.state_key)
  ),
  loc AS (
    SELECT * FROM (
      SELECT * FROM coords
      UNION ALL SELECT * FROM exact WHERE NOT EXISTS (SELECT 1 FROM coords)
      UNION ALL SELECT * FROM fuzzy WHERE NOT EXISTS (SELECT 1 FROM coords) AND NOT EXISTS (SELECT 1 FROM exact))
    ORDER BY priority, n_points DESC LIMIT 1
  ),
  c AS (
    SELECT i.*, loc.display_name AS location_display,
           round(2 * 6371 * asin(sqrt(pow(sin(radians(i.lat - loc.lat) / 2), 2)
                 + cos(radians(loc.lat)) * cos(radians(i.lat)) * pow(sin(radians(i.lon - loc.lon) / 2), 2))), 1) AS distance_km
    FROM {INDEX_TABLE} i
    JOIN svc ON i.service_key = svc.service_key
    CROSS JOIN loc
    WHERE i.lat IS NOT NULL AND NOT coalesce(i.excluded, false)
  ),
  scored AS (
    SELECT *, round(adjusted_base_score * exp(-distance_km / tau_km), 4) AS score
    FROM c WHERE distance_km <= max_km
  ),
  dedup AS (
    SELECT * FROM (SELECT *, row_number() OVER (PARTITION BY upper(name), coalesce(upper(city), '') ORDER BY score DESC) AS _dup
                   FROM scored) WHERE _dup = 1
  ),
  ext AS (
    SELECT facility_id, service_key,
           max_by(verification_level, CASE verification_level WHEN 'Verified' THEN 4 WHEN 'Contradicted' THEN 3
                                        WHEN 'Corroborated' THEN 2 ELSE 1 END) AS verification_level,
           max_by(external_source, CASE verification_level WHEN 'Verified' THEN 4 WHEN 'Contradicted' THEN 3
                                     WHEN 'Corroborated' THEN 2 ELSE 1 END) AS external_source
    FROM {GOLD}.facility_external_validation GROUP BY facility_id, service_key
  ),
  ranked AS (
    SELECT d.*, e.verification_level, e.external_source,
           CAST(row_number() OVER (ORDER BY d.score DESC, d.distance_km) AS INT) AS result_rank
    FROM dedup d LEFT JOIN ext e ON d.facility_id = e.facility_id AND d.service_key = e.service_key
  )
SELECT result_rank, name, adjusted_confidence AS confidence, confidence AS rules_confidence,
       coalesce(verification_level, 'Not externally verified') AS verification_level, external_source,
       distance_km, score, phone, address, city, district, state, ownership, facility_type,
       CASE WHEN size(verified_quotes) > 0 THEN verified_quotes ELSE transform(top_evidence, e -> e.text) END AS evidence,
       all_cautions AS cautions, guideline_check, llm_status, {EVIDENCE_SOURCE} AS evidence_source,
       concat(why_evidence, ' ', format_string('%.1f km away.', distance_km)) AS why,
       service_label, location_display, facility_id, lat, lon
FROM ranked WHERE result_rank <= top_n
UNION ALL
SELECT 0, 'PLACE NOT FOUND', CAST(NULL AS STRING), CAST(NULL AS STRING), CAST(NULL AS STRING), CAST(NULL AS STRING),
       CAST(NULL AS DOUBLE), CAST(NULL AS DOUBLE), CAST(NULL AS STRING), CAST(NULL AS STRING), CAST(NULL AS STRING),
       CAST(NULL AS STRING), CAST(NULL AS STRING), CAST(NULL AS STRING), CAST(NULL AS STRING),
       CAST(NULL AS ARRAY<STRING>), CAST(NULL AS ARRAY<STRING>), CAST(NULL AS STRING), CAST(NULL AS STRING), CAST(NULL AS STRING),
       concat('No place matched "', q_location, '". Try a 6-digit PIN code or "town, state".'),
       CAST(NULL AS STRING), CAST(NULL AS STRING), CAST(NULL AS STRING), CAST(NULL AS DOUBLE), CAST(NULL AS DOUBLE)
WHERE NOT EXISTS (SELECT 1 FROM loc)
ORDER BY result_rank
""")
print("created find_care")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Tests

# COMMAND ----------

tests = [("c-section", "Patna"), ("dialysis", "800001"), ("nicu", "Jammu"), ("heart attack", "Pune"),
         ("caesarean", "Danapur, Bihar"), ("icu", "25.6, 85.1"), ("dialysis", "Nowhereville")]
for s, l in tests:
    print(f"\n=== find_care('{s}', '{l}')")
    display(spark.sql(f"SELECT result_rank, name, confidence, verification_level, distance_km, phone, guideline_check, location_display, cautions FROM {GOLD}.find_care('{s}', '{l}', 3)"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Grant the phone-line token access (if a different user or service principal runs the webhook)
# MAGIC ```sql
# MAGIC GRANT USE CATALOG ON CATALOG workspace TO `someone@example.com`;
# MAGIC GRANT USE SCHEMA, SELECT, EXECUTE ON SCHEMA workspace.hc_gold TO `someone@example.com`;
# MAGIC ```
