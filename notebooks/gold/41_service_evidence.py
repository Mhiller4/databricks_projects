# Databricks notebook source
# MAGIC %md
# MAGIC # Gold 41 · Service evidence: which facilities offer what, and how do we know?
# MAGIC
# MAGIC Every claim in `procedure`, `equipment`, `capability` and `description` is matched against each
# MAGIC service's pattern (rules in `src/hc/care.py`). Specialty tags count as **indirect** evidence only.
# MAGIC
# MAGIC | Output | Grain | Used for |
# MAGIC |---|---|---|
# MAGIC | `service_catalog` | service | the service picker, and the HOW: patterns, weights, travel distance |
# MAGIC | `facility_evidence_snippets` | facility × service × matching claim | **citations**: the exact text behind every recommendation |
# MAGIC | `facility_service_evidence` | facility × service | evidence score, fields that agree, best 3 snippets, type fit |
# MAGIC
# MAGIC **Evidence score** = noisy-OR of the best weight per field: procedure / equipment 0.60, capability 0.50,
# MAGIC description 0.35, specialty tag 0.15. One procedure mention scores 0.60; procedure + capability
# MAGIC scores 0.80. Independent fields agreeing is what moves a claim toward fact. A snippet that reads
# MAGIC like a directory listing about another hospital ("listed as a referral hospital") counts half. A
# MAGIC snippet with specifics ("10 dialysis machines") adds a small bonus.

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

from pyspark.sql import Window

from hc import care
from hc.io import write_table

S, G = cfg.silver, cfg.gold


def k(c):
    return F.regexp_replace(F.upper(F.trim(c)), "[^A-Z0-9]", "")


fm = spark.table(S("facility_master"))

# COMMAND ----------

# MAGIC %md ## Service catalog

# COMMAND ----------

rows = []
for svc in care.SERVICES:
    r = svc.as_row()
    r["match_keys"] = sorted({care.key(svc.key), care.key(svc.label), *[care.key(x) for x in svc.synonyms]})
    rows.append(r)
catalog = spark.createDataFrame(
    rows,
    "key string, label string, pattern string, specialties array<string>, needs_hospital boolean, tau_km double, "
    "compatible_name_kinds array<string>, synonyms array<string>, note string, match_keys array<string>",
).withColumnRenamed("key", "service_key")
write_table(catalog, G("service_catalog"))
spark.sql(
    f"COMMENT ON TABLE {G('service_catalog')} IS 'Care Finder services: regex pattern matched against facility claims, "
    "specialty codes that count as indirect evidence, and tau_km (distance at which the distance score falls to 37%).'"
)
display(spark.table(G("service_catalog")).select("service_key", "label", "tau_km", "needs_hospital", "specialties", "note"))

# COMMAND ----------

# MAGIC %md ## Snippets: every claim that matches a service

# COMMAND ----------

parts = [
    fm.select("facility_id", F.lit(fld).alias("field"), F.posexplode(fld).alias("pos", "snippet"))
    for fld in ("procedure", "equipment", "capability")
]
parts.append(fm.where("description IS NOT NULL").select("facility_id", F.lit("description").alias("field"), F.lit(0).alias("pos"), F.col("description").alias("snippet")))
claims = parts[0]
for p in parts[1:]:
    claims = claims.unionByName(p)
claims = claims.withColumn("_lower", F.lower("snippet"))

direct = (
    claims.crossJoin(F.broadcast(catalog.select("service_key", "pattern")))
    .where(F.expr("_lower RLIKE pattern"))
    .withColumn("is_third_party", F.col("_lower").rlike(care.THIRD_PARTY_PATTERN))
    .withColumn("has_quantity", F.col("_lower").rlike(care.QUANTITY_PATTERN))
)
w_field = F.create_map(*[x for kv in care.FIELD_WEIGHTS.items() for x in (F.lit(kv[0]), F.lit(kv[1]))])
direct = direct.withColumn(
    "weight", F.round(w_field[F.col("field")] * F.when(F.col("is_third_party"), care.THIRD_PARTY_FACTOR).otherwise(1.0), 3)
).select("facility_id", "service_key", "field", "pos", "snippet", "weight", "is_third_party", "has_quantity")

spec = (
    fm.select("facility_id", F.posexplode("specialties").alias("pos", "snippet"))
    .join(F.broadcast(catalog.select("service_key", F.explode("specialties").alias("snippet"))), "snippet")
    .select(
        "facility_id", "service_key", F.lit("specialties").alias("field"), "pos", "snippet",
        F.lit(care.FIELD_WEIGHTS["specialties"]).alias("weight"), F.lit(False).alias("is_third_party"), F.lit(False).alias("has_quantity"),
    )
)
snippets = direct.unionByName(spec)
write_table(snippets, G("facility_evidence_snippets"))
spark.sql(
    f"COMMENT ON TABLE {G('facility_evidence_snippets')} IS 'Citations: each facility claim (field + exact text) that matched a service "
    "pattern, with its evidence weight. specialties rows are indirect evidence.'"
)
snippets = spark.table(G("facility_evidence_snippets"))
print(f"{snippets.count():,} matching snippets")

# COMMAND ----------

# MAGIC %md ## Evidence per facility × service

# COMMAND ----------

per_field = snippets.groupBy("facility_id", "service_key", "field").agg(
    F.max("weight").alias("best_weight"),
    F.count("*").alias("n"),
    F.max(F.col("has_quantity").cast("int")).alias("q"),
    F.min(F.col("is_third_party").cast("int")).alias("all_third_party"),
)

direct_fields_sql = "filter(fields, f -> f <> 'specialties')"
ev = (
    per_field.groupBy("facility_id", "service_key")
    .agg(
        (1 - F.exp(F.sum(F.log(1 - F.col("best_weight"))))).alias("_raw"),
        F.sort_array(F.collect_list("field")).alias("fields"),
        F.sum("n").alias("n_snippets"),
        F.sum(F.when(F.col("field") != "specialties", F.col("n")).otherwise(0)).alias("n_direct_snippets"),
        F.max("q").cast("boolean").alias("has_specifics"),
        F.min(F.when(F.col("field") != "specialties", F.col("all_third_party"))).alias("_all_tp"),
    )
    .withColumn("direct_fields", F.expr(direct_fields_sql))
    .withColumn("evidence_tier", F.when(F.size("direct_fields") > 0, "direct").otherwise("indirect"))
    .withColumn("only_third_party_text", F.coalesce(F.col("_all_tp") == 1, F.lit(False)))
    .withColumn(
        "evidence_score",
        F.round(F.least(F.lit(care.EVIDENCE_CAP), F.col("_raw") + F.when(F.col("has_specifics"), care.QUANTITY_BONUS).otherwise(0.0)), 3),
    )
    .drop("_raw", "_all_tp")
)

# Best 3 citations: direct before indirect, then weight, then specifics, then shorter text
rank_w = Window.partitionBy("facility_id", "service_key").orderBy(
    F.col("weight").desc(), F.col("has_quantity").desc(), F.length("snippet")
)
top = (
    snippets.withColumn("rn", F.row_number().over(rank_w))
    .where("rn <= 3")
    .groupBy("facility_id", "service_key")
    .agg(F.sort_array(F.collect_list(F.struct("rn", "field", "snippet", "is_third_party"))).alias("_top"))
    .withColumn("top_evidence", F.expr("transform(_top, x -> named_struct('field', x.field, 'text', x.snippet, 'third_party', x.is_third_party))"))
    .drop("_top")
)
ev = ev.join(top, ["facility_id", "service_key"], "left")

# COMMAND ----------

# MAGIC %md ## Type fit: does this kind of facility plausibly offer this service?

# COMMAND ----------

name_kind = F.lit(None).cast("string")
for kind, rx in reversed(list(care.NAME_KINDS.items())):  # first listed kind wins
    name_kind = F.when(F.lower(F.col("name")).rlike(rx), F.lit(kind)).otherwise(name_kind)

types = fm.select("facility_id", "name", "facility_type").withColumn("name_kind", name_kind)
fit_hosp = F.create_map(*[x for t, (h, _) in care.TYPE_FIT.items() if t for x in (F.lit(t), F.lit(h))])
fit_other = F.create_map(*[x for t, (_, o) in care.TYPE_FIT.items() if t for x in (F.lit(t), F.lit(o))])
unknown_h, unknown_o = care.TYPE_FIT[None]

ev = (
    ev.join(types, "facility_id")
    .join(F.broadcast(catalog.select("service_key", "label", "needs_hospital", "compatible_name_kinds")), "service_key")
    .withColumn(
        "_base",
        F.when(F.col("needs_hospital"), F.coalesce(fit_hosp[F.col("facility_type")], F.lit(unknown_h))).otherwise(
            F.coalesce(fit_other[F.col("facility_type")], F.lit(unknown_o))
        ),
    )
    .withColumn("name_conflict", F.col("name_kind").isNotNull() & ~F.array_contains("compatible_name_kinds", F.col("name_kind")))
    .withColumn("type_fit", F.round(F.col("_base") * F.when(F.col("name_conflict"), care.NAME_KIND_FIT).otherwise(1.0), 3))
    .withColumn(
        "type_fit_note",
        F.concat_ws(
            " ",
            F.when(F.col("_base") < 0.9, F.format_string("Listed as a %s, which rarely provides %s.", F.coalesce("facility_type", F.lit("facility of unknown type")), F.lower("label"))),
            F.when(F.col("name_conflict"), F.format_string("The name suggests a %s facility; the %s text may come from another facility merged into this record.", F.regexp_replace("name_kind", "_", " "), F.lower("label"))),
        ),
    )
    .withColumn("type_fit_note", F.when(F.length("type_fit_note") > 0, F.col("type_fit_note")))
    .drop("_base", "name", "facility_type", "needs_hospital", "compatible_name_kinds", "label")
)
write_table(ev, G("facility_service_evidence"))
spark.sql(
    f"COMMENT ON TABLE {G('facility_service_evidence')} IS 'One row per facility x service with any matching evidence: "
    "evidence_score (noisy-OR of field weights), tier (direct / indirect), fields that agree, top 3 citations, type fit.'"
)

# COMMAND ----------

display(spark.sql(f"""
  SELECT service_key,
         count(*) AS facilities_with_any_evidence,
         count_if(evidence_tier = 'direct') AS direct,
         count_if(size(direct_fields) >= 2) AS two_plus_fields,
         count_if(only_third_party_text) AS only_third_party_text,
         count_if(name_conflict) AS name_conflicts,
         round(avg(evidence_score), 3) AS avg_evidence
  FROM {G('facility_service_evidence')} GROUP BY 1 ORDER BY 2 DESC
"""))
