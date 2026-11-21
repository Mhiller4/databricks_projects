# Databricks notebook source
# MAGIC %md
# MAGIC # 00 · Create schemas + landing volume
# MAGIC
# MAGIC Idempotent. Creates (in catalog `workspace` on Free Edition):
# MAGIC
# MAGIC | Object | Purpose |
# MAGIC |---|---|
# MAGIC | `hc_bronze` | raw tables, exactly as received (all strings + lineage columns) |
# MAGIC | `hc_bronze.landing` (volume) | raw files, if the data ever arrives as files: `kickoff/...` |
# MAGIC | `hc_silver` | cleaned, typed, standardized, joinable tables |
# MAGIC | `hc_gold` | analysis/model-ready tables, data-quality scorecards, decision outputs |
# MAGIC
# MAGIC We create schemas in SQL instead of managing them as bundle resources, so `bundle destroy`
# MAGIC never drops data and teammates working in the UI get the same layout.

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

comments = {
    "bronze": "Raw data as received: all-string columns + _source_file/_ingested_at lineage",
    "silver": "Cleaned, typed, standardized (PIN, state, coordinates) tables; one documented grain per table",
    "gold": "Analysis- and model-ready tables, DQ scorecards, and decision outputs",
}
for layer, comment in comments.items():
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {cfg.schema(layer)} COMMENT '{comment}'")
    print("schema ok:", cfg.schema(layer))

spark.sql(
    f"CREATE VOLUME IF NOT EXISTS {q(cfg.catalog, cfg.bronze_schema, cfg.landing_volume)} "
    "COMMENT 'Landing zone for raw files (kickoff/)'"
)
for sub in (cfg.kickoff_landing,):
    os.makedirs(sub, exist_ok=True)
    print("folder ok:", sub)

# COMMAND ----------

display(spark.sql(f"SHOW SCHEMAS IN {q(cfg.catalog)} LIKE 'hc_*'"))
