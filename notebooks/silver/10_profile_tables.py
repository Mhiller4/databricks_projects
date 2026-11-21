# Databricks notebook source
# MAGIC %md
# MAGIC # Silver 10 · Data-quality profile (the "how messy is it?" scorecard)
# MAGIC
# MAGIC Profiles every table in a layer (or the tables you list) into:
# MAGIC * `hc_gold.dq_profile`: per column: type, % null, distinct values, min/max, mean/sd/median, top values
# MAGIC * `hc_gold.dq_table_summary`: per table: rows, columns, % null cells, mostly-null columns, duplicate rows
# MAGIC
# MAGIC Run it on **bronze** before cleaning and **silver** after. The before/after comparison is the
# MAGIC Exploration story ("we took X% null cells and Y duplicate rows down to ...").

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

from hc.profile import profile_df, write_profile

layer = widget(dbutils, "layer", "bronze", "layer (bronze/silver/gold)").lower()
tables_arg = widget(dbutils, "tables", "", "tables (comma list; blank = all in layer)")
name_filter = widget(dbutils, "name_like", "*", "table name filter, e.g. kickoff_*")

schema_fqn = cfg.schema(layer)
if tables_arg:
    tables = [t.strip() for t in tables_arg.split(",") if t.strip()]
else:
    rows = spark.sql(f"SHOW TABLES IN {schema_fqn} LIKE '{name_filter}'").collect()
    tables = sorted(r.tableName for r in rows if not r.isTemporary and not r.tableName.startswith(("_", "dq_")))
print(f"Profiling {len(tables)} tables in {schema_fqn}: {tables}")

# COMMAND ----------

summaries = []
for t in tables:
    df = spark.table(f"{schema_fqn}.{q(t)}")
    rows, summary = profile_df(df, layer, t)
    write_profile(spark, cfg, layer, t, rows, summary)
    summaries.append(summary)
    print(f"{t:<40} rows={summary[2]:>10,}  cols={summary[3]:>4}  null_cells={summary[4] or 0:6.1%}")

# COMMAND ----------

# MAGIC %md ### Table scorecard

# COMMAND ----------

display(spark.sql(f"""
  SELECT layer, table_name, n_rows, n_columns, round(100 * pct_cells_null, 1) AS pct_cells_null,
         n_columns_mostly_null, n_duplicate_rows
  FROM {cfg.gold('dq_table_summary')}
  WHERE layer = '{layer}'
  ORDER BY pct_cells_null DESC
"""))

# COMMAND ----------

# MAGIC %md ### Worst columns (most missing)

# COMMAND ----------

display(spark.sql(f"""
  SELECT table_name, column_name, data_type, round(100 * null_pct, 1) AS pct_null, n_distinct_approx,
         min_value, max_value, top_values
  FROM {cfg.gold('dq_profile')}
  WHERE layer = '{layer}'
  ORDER BY null_pct DESC
  LIMIT 100
"""))

# COMMAND ----------

# MAGIC %md ### Bronze vs silver (run after both layers are profiled)

# COMMAND ----------

display(spark.sql(f"""
  SELECT coalesce(s.table_name, b.table_name) AS table_name,
         b.n_rows AS bronze_rows, s.n_rows AS silver_rows,
         round(100 * b.pct_cells_null, 1) AS bronze_pct_null, round(100 * s.pct_cells_null, 1) AS silver_pct_null,
         b.n_duplicate_rows AS bronze_dups, s.n_duplicate_rows AS silver_dups
  FROM (SELECT * FROM {cfg.gold('dq_table_summary')} WHERE layer = 'bronze') b
  FULL OUTER JOIN (SELECT * FROM {cfg.gold('dq_table_summary')} WHERE layer = 'silver') s
    ON s.table_name = b.table_name
  ORDER BY table_name
"""))
