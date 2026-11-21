# Databricks notebook source
# MAGIC %md
# MAGIC # Silver 11 · Auto-clean the kickoff (organizer) tables
# MAGIC
# MAGIC For each `hc_bronze.kickoff_*` table this runs `hc.clean.clean_dataframe`:
# MAGIC trim → null tokens → suppression flags → type inference → FIPS/ZIP standardization → drop empty
# MAGIC columns → de-duplicate. The result goes to `hc_silver.<same name>`, and every decision is logged to
# MAGIC `hc_gold.dq_cleaning_log`.
# MAGIC
# MAGIC **Workflow:** run once with no overrides, read the log, then fix what the heuristics got wrong with
# MAGIC `overrides_json`, keyed by table name:
# MAGIC ```json
# MAGIC {"kickoff_encounters": {
# MAGIC    "primary_key": ["encounter_id"],
# MAGIC    "types": {"admit_date": "date", "los_days": "double"},
# MAGIC    "keep_string": ["drg"],
# MAGIC    "rename": {"pt_zip": "patient_zip"},
# MAGIC    "drop": ["notes_internal"],
# MAGIC    "null_tokens": ["unk", "999"]}}
# MAGIC ```
# MAGIC Domain-specific cleaning (unit conversions, impossible values like age 200, code mapping) goes in the
# MAGIC cell at the bottom, after you have looked at the data.

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

import json

from hc.clean import clean_dataframe, write_cleaning_log
from hc.io import write_table

prefix = widget(dbutils, "table_prefix", "kickoff_", "bronze table prefix")
tables_arg = widget(dbutils, "tables", "", "tables (comma list; blank = all with prefix)")
overrides_all = json.loads(widget(dbutils, "overrides_json", "{}", "overrides JSON") or "{}")

if tables_arg:
    tables = [t.strip() for t in tables_arg.split(",") if t.strip()]
else:
    tables = sorted(r.tableName for r in spark.sql(f"SHOW TABLES IN {cfg.schema('bronze')} LIKE '{prefix}*'").collect())
if not tables:
    raise RuntimeError(f"No bronze tables matching {prefix}*. Run bronze/01_ingest_kickoff_data first.")
print("Cleaning:", tables)

# COMMAND ----------

for t in tables:
    df_clean, log = clean_dataframe(spark.table(cfg.bronze(t)), overrides_all.get(t, {}))
    write_table(df_clean, cfg.silver(t))
    spark.sql(f"COMMENT ON TABLE {cfg.silver(t)} IS 'Auto-cleaned from {cfg.bronze_schema}.{t}; see {cfg.gold_schema}.dq_cleaning_log'")
    write_cleaning_log(spark, cfg, t, log)
    print(f"{t}: {log[0]['detail']}  ->  {log[-1]['detail']}")

# COMMAND ----------

# MAGIC %md ### What the cleaner did (read this, then tune `overrides_json`)

# COMMAND ----------

in_list = ", ".join(f"'{t}'" for t in tables)
display(spark.sql(f"""
  SELECT table_name, column_name, action, detail, n_affected
  FROM {cfg.gold('dq_cleaning_log')}
  WHERE table_name IN ({in_list})
  ORDER BY table_name, step
"""))

# COMMAND ----------

# MAGIC %md ### Schema of the cleaned tables

# COMMAND ----------

for t in tables:
    print(f"\n== {cfg.silver(t)}")
    spark.table(cfg.silver(t)).printSchema()

# COMMAND ----------

# MAGIC %md
# MAGIC ### Domain-specific cleaning
# MAGIC The generic cleaner above only fixes types, null tokens, PIN codes and duplicates. The facility-specific
# MAGIC work (state names, PIN / coordinate checks, shifted-column rows, claim lists) is in
# MAGIC `silver/12_facility_master`.
