# Databricks notebook source
# MAGIC %md
# MAGIC # Non-Medallion Example: Reverse ETL Publish
# MAGIC
# MAGIC Placeholder notebook showing a publish pattern from curated outputs to an external destination.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("curated_schema", "")

catalog = dbutils.widgets.get("catalog").strip()
curated_schema = dbutils.widgets.get("curated_schema").strip()

if not all([catalog, curated_schema]):
    raise ValueError("catalog and curated_schema are required")

source_table = f"{catalog}.{curated_schema}.daily_sales_summary"
print(f"Reverse ETL source placeholder table: {source_table}")

# Placeholder publish options:
# 1) Write to operational database over JDBC.
# 2) Publish to API endpoint in batches.
# 3) Land outbound files for downstream applications.
print("Publish placeholder: replace with your system-specific integration")
