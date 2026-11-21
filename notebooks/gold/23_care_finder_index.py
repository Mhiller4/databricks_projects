# Databricks notebook source
# MAGIC %md
# MAGIC # Gold 23 · `care_finder_index` + the two functions everything else calls
# MAGIC
# MAGIC * `care_finder_index`: one row per facility × service, with everything a recommendation needs
# MAGIC   except distance: scores, confidence label, plain-language explanation, citations, cautions, contacts.
# MAGIC * `resolve_location(q)`: "Patna", "Patna, Bihar", "800001", "25.61, 85.14" → candidate points.
# MAGIC * `recommend_facilities(service, lat, lon [, top_n, max_km])`: the ranked answer, with WHY and HOW columns.
# MAGIC
# MAGIC ```sql
# MAGIC SELECT * FROM workspace.hc_gold.resolve_location('Patna, Bihar');
# MAGIC SELECT * FROM workspace.hc_gold.recommend_facilities('dialysis', 25.61, 85.14);
# MAGIC ```
# MAGIC
# MAGIC **Score** = evidence × type fit × record trust × exp(−distance / service travel distance).
# MAGIC **Confidence** ignores distance: High = evidence ≥ 0.75 and trust ≥ 0.75 and type fits; Medium =
# MAGIC evidence ≥ 0.5, trust ≥ 0.5 and type fit ≥ 0.5; Low = everything else.

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

from hc.io import write_table

S, G = cfg.silver, cfg.gold

ev = spark.table(G("facility_service_evidence"))
tr = spark.table(G("facility_trust")).select("facility_id", "trust_score", F.col("cautions").alias("_trust_cautions"), "supporting_facts")
fm = spark.table(S("facility_master")).select(
    "facility_id", "name", "facility_type", "address", "city", "district", "state", "pin", "phone", "website",
    "lat", "lon", "location_source", "n_sources", F.slice("source_urls", 1, 5).alias("source_urls"),
)
cat = spark.table(G("service_catalog")).select("service_key", F.col("label").alias("service_label"), "tau_km")

idx = ev.join(tr, "facility_id").join(fm, "facility_id").join(F.broadcast(cat), "service_key")

conf = (
    F.when((F.col("evidence_score") >= 0.75) & (F.col("trust_score") >= 0.75) & (F.col("type_fit") >= 0.9), "High")
    .when((F.col("evidence_score") >= 0.5) & (F.col("trust_score") >= 0.5) & (F.col("type_fit") >= 0.5), "Medium")
    .otherwise("Low")
)
first_specialty = F.expr("get(filter(top_evidence, x -> x.field = 'specialties'), 0).text")
why_evidence = F.when(
    F.col("evidence_tier") == "direct",
    F.format_string(
        "%s is mentioned in this facility's %s (%d matching claim%s%s).",
        "service_label",
        F.array_join("direct_fields", ", "),
        "n_direct_snippets",
        F.when(F.col("n_direct_snippets") == 1, "").otherwise("s"),
        F.when(F.col("has_specifics"), ", including specific numbers").otherwise(""),
    ),
).otherwise(
    F.format_string("No direct mention of %s; only a related specialty (%s) is listed.", F.lower("service_label"), F.coalesce(first_specialty, F.lit("?")))
)
evidence_cautions = F.array(
    F.when(F.col("evidence_tier") == "indirect", F.lit("Indirect evidence only: a related department is listed, but the service itself is never mentioned. Call ahead.")),
    F.when(F.col("only_third_party_text"), F.lit("The matching text reads like a directory listing about another hospital, not this one.")),
    F.when(F.size("direct_fields") == 1, F.format_string("Only one field (%s) mentions it; not corroborated elsewhere in the record.", F.col("direct_fields")[0])),
    F.col("type_fit_note"),
)

idx = (
    idx.withColumn("base_score", F.round(F.col("evidence_score") * F.col("type_fit") * F.col("trust_score"), 4))
    .withColumn("confidence", conf)
    .withColumn("why_evidence", why_evidence)
    .withColumn(
        "confidence_reason",
        F.format_string(
            "%s confidence: evidence %.2f from %d independent field(s), record trust %.2f, facility-type fit %.2f.",
            "confidence", "evidence_score", F.size("direct_fields"), "trust_score", "type_fit",
        ),
    )
    .withColumn("cautions", F.concat(F.filter(evidence_cautions, lambda x: x.isNotNull()), F.col("_trust_cautions")))
    .drop("_trust_cautions")
)
write_table(idx, G("care_finder_index"))
spark.sql(
    f"COMMENT ON TABLE {G('care_finder_index')} IS 'Care Finder: one row per facility x service with evidence, trust, "
    "confidence, explanation, citations (top_evidence), cautions and contact details. Rank with recommend_facilities().'"
)

# COMMAND ----------

# MAGIC %md ## `resolve_location(q)`

# COMMAND ----------

LOOKUP = G("location_lookup")
spark.sql(f"""
CREATE OR REPLACE FUNCTION {G('resolve_location')}(q STRING)
RETURNS TABLE (kind STRING, display_name STRING, district STRING, state STRING, lat DOUBLE, lon DOUBLE, priority INT, n_points BIGINT)
COMMENT 'Care Finder: resolve a PIN, district, city, post office, state ("Patna, Bihar" narrows by state) or "lat, lon" to candidate points, best first.'
RETURN
  WITH input AS (
    SELECT trim(q) AS raw,
           regexp_replace(upper(trim(split(q, ',')[0])), '[^A-Z0-9]', '') AS name_key,
           nullif(regexp_replace(upper(trim(get(split(q, ','), 1))), '[^A-Z0-9]', ''), '') AS state_key
  ),
  coords AS (
    SELECT 'coordinates' AS kind, concat('Coordinates ', raw) AS display_name, CAST(NULL AS STRING) AS district,
           CAST(NULL AS STRING) AS state, try_cast(trim(split(raw, ',')[0]) AS DOUBLE) AS lat,
           try_cast(trim(get(split(raw, ','), 1)) AS DOUBLE) AS lon, 0 AS priority, CAST(1 AS BIGINT) AS n_points
    FROM input
    WHERE raw RLIKE '^ *-?[0-9]+([.][0-9]+)? *, *-?[0-9]+([.][0-9]+)? *$'
  ),
  exact AS (
    SELECT l.kind, l.display_name, l.district, l.state, l.lat, l.lon, l.priority, l.n_points
    FROM {LOOKUP} l CROSS JOIN input i
    WHERE l.name_key = i.name_key AND (i.state_key IS NULL OR l.state_key = i.state_key)
      AND NOT EXISTS (SELECT 1 FROM coords)
  ),
  fuzzy AS (
    SELECT l.kind, concat(l.display_name, ' (partial match)') AS display_name, l.district, l.state, l.lat, l.lon,
           l.priority + 10 AS priority, l.n_points
    FROM {LOOKUP} l CROSS JOIN input i
    WHERE length(i.name_key) >= 4 AND l.name_key LIKE concat(i.name_key, '%') AND l.kind <> 'pin'
      AND (i.state_key IS NULL OR l.state_key = i.state_key)
      AND NOT EXISTS (SELECT 1 FROM coords) AND NOT EXISTS (SELECT 1 FROM exact)
  )
  SELECT * FROM (SELECT * FROM coords UNION ALL SELECT * FROM exact UNION ALL SELECT * FROM fuzzy)
  ORDER BY priority, n_points DESC
  LIMIT 20
""")

# COMMAND ----------

# MAGIC %md ## `recommend_facilities(service, lat, lon, top_n = 5, max_km = 300)`

# COMMAND ----------

INDEX, CATALOG = G("care_finder_index"), G("service_catalog")
spark.sql(f"""
CREATE OR REPLACE FUNCTION {G('recommend_facilities')}(
  q_service STRING, q_lat DOUBLE, q_lon DOUBLE, top_n INT DEFAULT 5, max_km DOUBLE DEFAULT 300
)
RETURNS TABLE (
  result_rank INT, name STRING, facility_type STRING, confidence STRING, distance_km DOUBLE, score DOUBLE,
  why STRING, confidence_reason STRING,
  evidence ARRAY<STRUCT<field: STRING, text: STRING, third_party: BOOLEAN>>,
  cautions ARRAY<STRING>, supporting_facts ARRAY<STRING>,
  address STRING, district STRING, state STRING, phone STRING, website STRING, source_urls ARRAY<STRING>,
  location_source STRING, evidence_score DOUBLE, type_fit DOUBLE, trust_score DOUBLE, distance_score DOUBLE,
  service_label STRING, facility_id STRING, lat DOUBLE, lon DOUBLE
)
COMMENT 'Care Finder: best facilities for a service near a point. score = evidence x type fit x record trust x exp(-km / service travel distance). Every row cites its evidence and cautions.'
RETURN
  WITH svc AS (
    SELECT service_key FROM {CATALOG}
    WHERE array_contains(match_keys, regexp_replace(upper(q_service), '[^A-Z0-9]', ''))
    LIMIT 1
  ),
  c AS (
    SELECT i.*,
           round(2 * 6371 * asin(sqrt(pow(sin(radians(i.lat - q_lat) / 2), 2)
                 + cos(radians(q_lat)) * cos(radians(i.lat)) * pow(sin(radians(i.lon - q_lon) / 2), 2))), 1) AS distance_km
    FROM {INDEX} i JOIN svc ON i.service_key = svc.service_key
    WHERE i.lat IS NOT NULL
  ),
  scored AS (
    SELECT *, round(exp(-distance_km / tau_km), 3) AS distance_score,
              round(base_score * exp(-distance_km / tau_km), 4) AS score
    FROM c WHERE distance_km <= max_km
  ),
  dedup AS (  -- the same facility listed twice shows once (its best-scoring record)
    SELECT * FROM (
      SELECT *, row_number() OVER (PARTITION BY upper(name), coalesce(upper(city), '') ORDER BY score DESC) AS _dup
      FROM scored
    ) WHERE _dup = 1
  ),
  ranked AS (SELECT *, CAST(row_number() OVER (ORDER BY score DESC, distance_km) AS INT) AS result_rank FROM dedup)
  SELECT result_rank, name, facility_type, confidence, distance_km, score,
         concat(why_evidence, ' ', format_string('%.1f km away (location from %s).', distance_km, location_source)) AS why,
         confidence_reason, top_evidence AS evidence, cautions, supporting_facts,
         address, district, state, phone, website, source_urls,
         location_source, evidence_score, type_fit, trust_score, distance_score,
         service_label, facility_id, lat, lon
  FROM ranked WHERE result_rank <= top_n
  ORDER BY result_rank
""")
print("functions created:", G("resolve_location"), G("recommend_facilities"))

# COMMAND ----------

# MAGIC %md ## Smoke test

# COMMAND ----------

loc = spark.sql(f"SELECT * FROM {G('resolve_location')}('Patna, Bihar')").first()
print(loc)
display(spark.sql(f"SELECT result_rank, name, confidence, distance_km, score, why, cautions FROM {G('recommend_facilities')}('dialysis', {loc.lat}, {loc.lon})"))
