# Databricks notebook source
# MAGIC %md
# MAGIC # Gold 32 · LLM labels for the confidence model (random, stratified, resumable)
# MAGIC
# MAGIC Spec: `docs/CONFIDENCE_MODEL_SPEC.md`, step 1. Same prompt, model, JSON schema and quote check as the
# MAGIC first review (`gold/40_llm_review.py`, 200 rows in `hc_gold.llm_review`), so all labels
# MAGIC are consistent.
# MAGIC
# MAGIC | Output | What |
# MAGIC |---|---|
# MAGIC | `hc_gold.llm_label_sample` | the pairs to label: 25 random per service × rule confidence, plus audit pairs; created once |
# MAGIC | `hc_gold.llm_label_runs` | raw `ai_query` answers, appended per 200-row batch (re-runs skip finished batches) |
# MAGIC | `hc_gold.llm_labels` | parsed + grounded answers for every labelled pair (new + first review), with `label` and `origin` |
# MAGIC
# MAGIC **Databricks LLM features used:** Foundation Model API endpoint (pay-per-token, nothing to deploy) called
# MAGIC through the `ai_query()` SQL function, with `responseFormat` (JSON schema), `failOnError => false` and
# MAGIC temperature 0.

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

import json

from pyspark.sql import Window

from hc.io import write_table

G, S = cfg.gold, cfg.silver
MODEL = widget(dbutils, "llm_model", "databricks-meta-llama-3-3-70b-instruct", "Foundation Model endpoint")  # noqa: F821
PER_CELL = int(widget(dbutils, "per_cell", "25", "pairs per service x confidence"))  # noqa: F821
BATCH_SIZE = int(widget(dbutils, "batch_size", "200"))  # noqa: F821
SEED = widget(dbutils, "seed", "2026")  # noqa: F821
RESAMPLE = widget(dbutils, "resample", "false", "true = draw a new sample (drops finished batches' link)").lower() == "true"  # noqa: F821
MAX_TEXT_CHARS = 6000

SAMPLE, RUNS, LABELS = G("llm_label_sample"), G("llm_label_runs"), G("llm_labels")

# COMMAND ----------

# MAGIC %md ## 1 · The sample (created once; deterministic)

# COMMAND ----------

idx = spark.table(G("care_finder_index")).select("facility_id", "service_key", "service_label", "confidence")
prior = spark.table(G("llm_review")).select("facility_id", "service_key").distinct()
audit = spark.table(G("audit_sample")).select("facility_id", "service_key").distinct()

if RESAMPLE or not spark.catalog.tableExists(SAMPLE):
    pop = idx.groupBy("service_key", "confidence").agg(F.count("*").alias("pop_n"))
    w = Window.partitionBy("service_key", "confidence").orderBy(F.xxhash64("facility_id", "service_key", F.lit(SEED)))
    rnd = (
        idx.join(prior, ["facility_id", "service_key"], "left_anti")
        .join(audit, ["facility_id", "service_key"], "left_anti")
        .withColumn("_r", F.row_number().over(w))
        .where(F.col("_r") <= PER_CELL)
        .drop("_r")
        .join(pop, ["service_key", "confidence"])
        .withColumn("origin", F.lit("random"))
    )
    n_drawn = rnd.groupBy("service_key", "confidence").agg(F.count("*").alias("n_drawn"))
    rnd = rnd.join(n_drawn, ["service_key", "confidence"]).withColumn("sample_weight", F.col("pop_n") / F.col("n_drawn")).drop("n_drawn")
    # audit pairs the first review never looked at: needed for LLM vs human agreement
    aud = (
        audit.join(prior, ["facility_id", "service_key"], "left_anti")
        .join(idx, ["facility_id", "service_key"])
        .withColumn("pop_n", F.lit(None).cast("bigint"))
        .withColumn("origin", F.lit("audit"))
        .withColumn("sample_weight", F.lit(None).cast("double"))
    )
    cols = ["facility_id", "service_key", "service_label", "confidence", "origin", "pop_n", "sample_weight"]
    sample = rnd.select(cols).unionByName(aud.select(cols))
    wq = Window.orderBy("origin", F.xxhash64("facility_id", "service_key", F.lit(SEED)))
    sample = sample.withColumn("queue_pos", F.row_number().over(wq)).withColumn(
        "batch_no", ((F.col("queue_pos") - 1) / BATCH_SIZE).cast("int") + 1000  # 1000+ so batch ids never collide with the first review's
    )
    sample.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(SAMPLE)
    if RESAMPLE and spark.catalog.tableExists(RUNS):
        spark.sql(f"DROP TABLE {RUNS}")
    print("drew a new sample")

display(spark.table(SAMPLE).groupBy("origin", "confidence").agg(F.count("*").alias("pairs")).orderBy("origin", "confidence"))  # noqa: F821

# COMMAND ----------

# MAGIC %md ## 2 · Prompts (identical to the first review)

# COMMAND ----------

rules = spark.table(G("guideline_rules"))
fac = spark.table(S("vf_facilities"))


def humanize(col):
    return F.regexp_replace(F.regexp_replace(col, r"([a-z])([A-Z])", "$1 $2"), r"\s+", " ")


fac_text = fac.select(
    F.col("unique_id").alias("facility_id"),
    F.substring(F.concat_ws("\n",
        F.concat(F.lit("Name: "), F.col("name")),
        F.concat(F.lit("Type: "), F.coalesce(F.col("facility_type_id"), F.lit("unknown"))),
        F.concat(F.lit("Capability: "), F.coalesce(F.col("capability"), F.lit("-"))),
        F.concat(F.lit("Procedures: "), F.coalesce(F.col("procedure"), F.lit("-"))),
        F.concat(F.lit("Equipment: "), F.coalesce(F.col("equipment"), F.lit("-"))),
        F.concat(F.lit("Specialties: "), humanize(F.coalesce(F.col("specialties"), F.lit("-")))),
        F.concat(F.lit("Description: "), F.coalesce(F.col("description"), F.lit("-"))),
        F.concat(F.lit("Doctors: "), F.coalesce(F.col("number_doctors").cast("string"), F.lit("not reported"))),
        F.concat(F.lit("Beds: "), F.coalesce(F.col("capacity").cast("string"), F.lit("not reported")))),
        1, MAX_TEXT_CHARS).alias("record_text"),
)

INSTRUCTIONS = (
    "You verify whether a healthcare facility in India currently provides a specific service, "
    "using ONLY the facility record below. Do not use outside knowledge about the facility.\n"
    "Rules:\n"
    "- verdict = available only if the record states or clearly implies the service is provided now.\n"
    "- verdict = not_available if the record says it is not available, not provided, or absent.\n"
    "- verdict = planned if it is coming soon, under construction, proposed or future.\n"
    "- verdict = referral_only if the facility refers these patients elsewhere.\n"
    "- verdict = unclear if the evidence is only a department name, generic wording, home-care services, "
    "a research study mention, or otherwise insufficient.\n"
    "- For each required element, decide found or missing. Only mark found if the record supports it.\n"
    "- evidence_quotes must be copied word for word from the record (short phrases, max 4).\n"
    "- confidence is your probability (0 to 1) that the facility provides the service now.\n"
    "- red_flags: contradictions, dated (e.g. COVID-period) information, visiting-only doctors, implausible size.\n")

RESPONSE_FORMAT = json.dumps({
    "type": "json_schema",
    "json_schema": {"name": "service_review", "strict": True, "schema": {
        "type": "object", "additionalProperties": False,
        "required": ["verdict", "confidence", "evidence_quotes", "requirements_found", "requirements_missing", "red_flags", "explanation"],
        "properties": {
            "verdict": {"type": "string", "enum": ["available", "not_available", "planned", "referral_only", "unclear"]},
            "confidence": {"type": "number"},
            "evidence_quotes": {"type": "array", "items": {"type": "string"}},
            "requirements_found": {"type": "array", "items": {"type": "string"}},
            "requirements_missing": {"type": "array", "items": {"type": "string"}},
            "red_flags": {"type": "array", "items": {"type": "string"}},
            "explanation": {"type": "string"}}}}})
assert "'" not in RESPONSE_FORMAT

(spark.table(SAMPLE)
 .join(rules, "service_key")
 .join(fac_text, "facility_id")
 .withColumn("prompt", F.concat(
     F.lit(INSTRUCTIONS),
     F.lit("\nService: "), F.col("service_label"),
     F.lit("\nGuideline: "), F.col("guideline"),
     F.lit("\nRequired elements: "), F.concat_ws("; ", "required_elements"),
     F.lit("\n\nFacility record:\n"), F.col("record_text")))
 .createOrReplaceTempView("label_prompts"))

# COMMAND ----------

# MAGIC %md ## 3 · Run `ai_query` in resumable batches

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {RUNS} (
  facility_id STRING, service_key STRING, batch_no INT, model STRING, reviewed_at TIMESTAMP,
  raw_response STRING, error STRING, record_text STRING, required_elements ARRAY<STRING>, guideline STRING)
""")
done = {r.batch_no for r in spark.table(RUNS).select("batch_no").distinct().collect()}
todo = sorted({r.batch_no for r in spark.table(SAMPLE).select("batch_no").distinct().collect()} - done)
print(f"batches done: {len(done)}, to do: {len(todo)}")

for b in todo:
    out = spark.sql(f"""
      SELECT facility_id, service_key, batch_no, '{MODEL}' AS model, current_timestamp() AS reviewed_at,
             r.result AS raw_response, r.errorMessage AS error, record_text, required_elements, guideline
      FROM (
        SELECT *, ai_query('{MODEL}', prompt,
                           responseFormat => '{RESPONSE_FORMAT}',
                           modelParameters => named_struct('temperature', 0.0, 'max_tokens', 700),
                           failOnError => false) AS r
        FROM label_prompts WHERE batch_no = {b})
    """)
    out.write.mode("append").saveAsTable(RUNS)
    n = spark.table(RUNS).where(f"batch_no = {b}")
    print(f"batch {b}: {n.count()} rows, {n.where('error IS NOT NULL').count()} errors")

# COMMAND ----------

# MAGIC %md ## 4 · Parse, check every quote against the record, turn verdicts into labels

# COMMAND ----------

SCHEMA = ("verdict string, confidence double, evidence_quotes array<string>, requirements_found array<string>, "
          "requirements_missing array<string>, red_flags array<string>, explanation string")

first = (spark.table(G("llm_review")).alias("r")
         .join(spark.table(G("llm_review_queue")).select("facility_id", "service_key", "reason"), ["facility_id", "service_key"], "left")
         .withColumn("origin", F.when(F.col("reason").startswith("1_"), "priority_negation").otherwise("priority_high_acuity"))
         .drop("reason"))
new = spark.table(RUNS).join(spark.table(SAMPLE).select("facility_id", "service_key", "origin"), ["facility_id", "service_key"])
cols = ["facility_id", "service_key", "origin", "model", "reviewed_at", "raw_response", "error", "record_text", "required_elements"]
allr = first.select(cols).unionByName(new.select(cols))

norm_sql = "trim(regexp_replace(lower({x}), '[^a-z0-9]+', ' '))"
lab = (allr
       .withColumn("_rn", F.row_number().over(Window.partitionBy("facility_id", "service_key").orderBy(F.desc("reviewed_at"))))
       .where("_rn = 1").drop("_rn")
       .withColumn("p", F.from_json(F.regexp_extract("raw_response", r"(?s)(\{.*\})", 1), SCHEMA))
       .select("*", "p.*").drop("p")
       .withColumn("record_norm", F.expr(norm_sql.format(x="record_text")))
       .withColumn("verified_quotes", F.expr(
           f"filter(evidence_quotes, x -> length({norm_sql.format(x='x')}) >= 6 AND instr(record_norm, {norm_sql.format(x='x')}) > 0)"))
       .withColumn("grounded", F.size(F.coalesce("verified_quotes", F.array().cast("array<string>"))) > 0)
       .withColumn("llm_verdict",
                   F.when(F.col("verdict").isNull(), "error")
                    .when((F.col("verdict") == "available") & ~F.col("grounded"), "unclear")
                    .otherwise(F.col("verdict")))
       .withColumn("label", F.when(F.col("llm_verdict") == "available", 1)
                             .when(F.col("llm_verdict").isin("not_available", "planned", "referral_only"), 0)
                             .cast("int"))
       .join(spark.table(SAMPLE).select("facility_id", "service_key", "pop_n", "sample_weight"), ["facility_id", "service_key"], "left")
       .join(idx.select("facility_id", "service_key", F.col("confidence").alias("rules_confidence")), ["facility_id", "service_key"], "left")
       .select("facility_id", "service_key", "origin", "rules_confidence", "pop_n", "sample_weight", "model", "reviewed_at",
               F.col("verdict").alias("llm_raw_verdict"), "llm_verdict", "label", F.col("confidence").alias("llm_confidence"),
               "verified_quotes", "requirements_found", "requirements_missing", "red_flags", F.col("explanation").alias("llm_explanation"),
               "error"))

write_table(lab, LABELS)
spark.sql(f"COMMENT ON TABLE {LABELS} IS 'LLM labels for the confidence model (spec docs/CONFIDENCE_MODEL_SPEC.md). label: 1 available with a verified quote, 0 not available / planned / referral only, NULL unclear or error. origin: random (train), priority_negation (stress test), priority_high_acuity (holdout), audit (vs humans).'")

# COMMAND ----------

display(spark.sql(f"""
  SELECT origin, rules_confidence, count(*) AS pairs, count_if(label = 1) AS available, count_if(label = 0) AS no,
         count_if(label IS NULL) AS unclear_or_error, round(avg(label), 3) AS share_available
  FROM {LABELS} GROUP BY ALL ORDER BY origin, rules_confidence
"""))
