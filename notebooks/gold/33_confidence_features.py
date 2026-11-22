# Databricks notebook source
# MAGIC %md
# MAGIC # Gold 33 · Features for the confidence model
# MAGIC
# MAGIC Spec: `docs/CONFIDENCE_MODEL_SPEC.md`, step 2.
# MAGIC
# MAGIC | Output | What |
# MAGIC |---|---|
# MAGIC | `hc_gold.confidence_features` | one row per facility × service (all pairs): model inputs, plus the rule outputs as `rules_*` (for comparison only) |
# MAGIC | `hc_gold.confidence_training` | the `random` labelled pairs: model inputs + `label`. No rule outputs, nothing from the LLM answer |
# MAGIC
# MAGIC Left out on purpose: our own scores (`evidence_score`, `confidence`, `base_score`, `type_fit`, `trust_score`),
# MAGIC so the comparison with the rules is fair, and every LLM field (that is where the label comes from).

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

from hc.io import write_table

G, S = cfg.gold, cfg.silver

NEGATION = r"\b(not available|not equipped|no facility|not provided|not offered|unavailable|absent)\b"
FUTURE = r"\b(planned|coming soon|upcoming|proposed|under construction|will be (started|opened|available)|to be started|expected to be)\b"
REFERRAL = r"\b(refer(red|ral)? (to|out|elsewhere)|referred|tie-?up with|in collaboration with)\b"

idx = spark.table(G("care_finder_index"))
ev_text = F.lower(F.concat_ws(" || ", F.expr("transform(top_evidence, e -> e.text)")))

base = idx.select(
    "facility_id", "service_key",
    F.size("fields").alias("n_fields"),
    F.size("direct_fields").alias("n_direct_fields"),
    F.col("n_snippets").cast("int").alias("n_snippets"),
    F.col("n_direct_snippets").cast("int").alias("n_direct_snippets"),
    F.col("has_specifics").cast("int").alias("has_specifics"),
    (F.col("evidence_tier") == "direct").cast("int").alias("evidence_direct"),
    F.col("only_third_party_text").cast("int").alias("only_third_party_text"),
    F.length(ev_text).alias("evidence_chars"),
    ev_text.rlike(NEGATION).cast("int").alias("wording_negation"),
    ev_text.rlike(FUTURE).cast("int").alias("wording_future"),
    ev_text.rlike(REFERRAL).cast("int").alias("wording_referral"),
    "name_kind",
    F.col("name_conflict").cast("int").alias("name_conflict"),
    "facility_type",
    F.col("n_sources").alias("n_web_sources"),
    # rule outputs: kept for the head-to-head in gold/34, never used as inputs
    F.col("evidence_score").alias("rules_evidence_score"),
    F.col("base_score").alias("rules_base_score"),
    F.col("confidence").alias("rules_confidence"),
)

trust = spark.table(G("facility_trust"))
flags = [c for c in trust.columns if c.startswith("flag_") and c != "flag_listed_in_directory"]
trust = trust.select("facility_id", *[F.col(c).cast("int").alias(c) for c in flags])

ext = (spark.table(G("facility_external_matches"))
       .groupBy("facility_id")
       .agg(F.lit(1).alias("in_directory"), F.first("ownership", ignorenulls=True).alias("directory_ownership")))

cur = spark.table(S("facilities_silver_curated")).where("in_vf").select(
    "facility_id", "ownership", "beds", "doctors",
    (F.lit(2026) - F.col("year_established")).alias("facility_age_years"),
    "ihds_expected_care_finder", "ihds_peer_n",
)
rules = spark.table(G("guideline_rules")).select("service_key", F.col("high_acuity").cast("int").alias("high_acuity"))

feat = (base
        .join(trust, "facility_id", "left")
        .join(ext, "facility_id", "left")
        .join(cur, "facility_id", "left")
        .join(F.broadcast(rules), "service_key", "left")
        .withColumn("in_directory", F.coalesce("in_directory", F.lit(0)))
        .withColumn("ihds_peer_rate", F.element_at("ihds_expected_care_finder", F.col("service_key")))
        .withColumn("facility_age_years", F.when(F.col("facility_age_years").between(0, 300), F.col("facility_age_years")))
        .drop("ihds_expected_care_finder"))
write_table(feat, G("confidence_features"))
spark.sql(f"COMMENT ON TABLE {G('confidence_features')} IS 'Confidence-model inputs for every facility x service pair (gold/33). rules_* = rule outputs, for comparison only.'")

# COMMAND ----------

lab = spark.table(G("llm_labels")).where("origin = 'random' AND label IS NOT NULL").select("facility_id", "service_key", "label")
train = (spark.table(G("confidence_features")).join(lab, ["facility_id", "service_key"])
         .drop("rules_evidence_score", "rules_base_score", "rules_confidence"))
write_table(train, G("confidence_training"))
spark.sql(f"COMMENT ON TABLE {G('confidence_training')} IS 'Training rows for the confidence model: random stratified LLM-labelled pairs (gold/32). label 1 = record supports the service now.'")

display(spark.sql(f"""
  SELECT count(*) AS rows, count(DISTINCT facility_id) AS facilities, round(avg(label), 3) AS positive_rate,
         count_if(wording_negation + wording_future + wording_referral > 0) AS with_negative_wording
  FROM {G('confidence_training')}
"""))
