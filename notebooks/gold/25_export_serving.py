# Databricks notebook source
# MAGIC %md
# MAGIC # Gold 25 · Export the serving tables to Parquet
# MAGIC
# MAGIC The FastAPI backend (`backend/`) loads these files into DuckDB at startup, so each query takes
# MAGIC milliseconds and needs no SQL warehouse. Everything here is a straight copy of gold tables. The
# MAGIC ranking rules stay in `src/hc/care.py`, which Databricks and the backend both import.
# MAGIC
# MAGIC | File | From | Grain |
# MAGIC |---|---|---|
# MAGIC | `care_finder_index/` | `hc_gold.care_finder_index` | facility × service |
# MAGIC | `location_lookup/` | `hc_gold.location_lookup` | place name |
# MAGIC | `service_catalog/` | `hc_gold.service_catalog` | service |
# MAGIC | `facilities/` | `hc_silver.facility_master` + `hc_gold.facility_trust` | facility (for the funnel counts) |
# MAGIC | `funnel_base.json` | bronze / silver row counts | one object |
# MAGIC
# MAGIC Download: `databricks fs cp -r --overwrite dbfs:/Volumes/workspace/hc_gold/serving backend/data --profile <p>`

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

import json

S, G, B = cfg.silver, cfg.gold, cfg.bronze
spark.sql(f"CREATE VOLUME IF NOT EXISTS {q(cfg.catalog, cfg.gold_schema, 'serving')} COMMENT 'Parquet exports for the Care Finder backend'")
OUT = f"/Volumes/{cfg.catalog}/{cfg.gold_schema}/serving"


def export(df, name):
    df.coalesce(1).write.mode("overwrite").parquet(f"{OUT}/{name}")
    print(f"{name}: {df.count():,} rows")


export(
    spark.table(G("care_finder_index")).select(
        "facility_id", "service_key", "service_label", "tau_km", "name", "facility_type", "address", "city", "district",
        "state", "pin", "phone", "website", "lat", "lon", "location_source", "n_sources", "source_urls",
        "evidence_score", "evidence_tier", "fields", "direct_fields", "n_snippets", "n_direct_snippets", "has_specifics",
        "only_third_party_text", "top_evidence", "name_kind", "name_conflict", "type_fit", "type_fit_note",
        "trust_score", "supporting_facts", "base_score", "confidence", "why_evidence", "confidence_reason", "cautions",
    ),
    "care_finder_index",
)
export(spark.table(G("location_lookup")), "location_lookup")
export(spark.table(G("service_catalog")), "service_catalog")

fac = spark.table(S("facility_master")).select(
    "facility_id", "name", "facility_type", "city", "state", "lat", "lon", "is_malformed", "capacity", "number_doctors"
).join(spark.table(G("facility_trust")).select("facility_id", "trust_score"), "facility_id", "left")
export(fac, "facilities")

base = {
    "raw_records": spark.table(B("vf_facilities")).count(),
    "unique_records": spark.table(S("vf_facilities")).count(),
    "usable_records": fac.where("NOT is_malformed AND lat IS NOT NULL").count(),
}
dbutils.fs.put(f"{OUT}/funnel_base.json", json.dumps(base), overwrite=True)
print(base)
