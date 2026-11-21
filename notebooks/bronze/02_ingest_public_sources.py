# Databricks notebook source
# MAGIC %md
# MAGIC # Bronze 02 · Public source files → bronze tables
# MAGIC
# MAGIC One bronze table per source (`hc_bronze.<key>`): all columns as strings, names sanitized,
# MAGIC plus `_source_file` and `_ingested_at`. Original column names go to `hc_bronze._column_map`.

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

from hc.io import ingest_file_to_bronze
from hc.sources import select_sources

selection = widget(dbutils, "sources", "all", "sources (comma list or all)")

results = []
for src in select_sources(selection):
    path = f"{cfg.public_landing}/{src.key}/{src.filename}"
    if not os.path.exists(path):
        results.append((src.key, None, "MISSING FILE: run bronze/01 first"))
        continue
    comment = f"{src.title} ({src.publisher}). Grain: {src.grain}. Join key: {src.join_key}. Source: {src.homepage}"
    n = ingest_file_to_bronze(spark, cfg, path, src.key, comment=comment, delimiter=src.delimiter)
    results.append((src.key, n, "ok"))
    print(f"{src.key:<28} {n:>10,} rows")

display(spark.createDataFrame(results, "table string, rows bigint, status string"))

# COMMAND ----------

failed = [r[0] for r in results if r[2] != "ok"]
if failed:
    raise RuntimeError(f"Not ingested: {failed}")
