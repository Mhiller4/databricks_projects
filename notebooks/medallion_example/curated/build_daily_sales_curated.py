# Databricks notebook source
# MAGIC %md
# MAGIC # Medallion Example: Curated Output
# MAGIC
# MAGIC Placeholder notebook for business-facing curated outputs.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("enriched_schema", "")
dbutils.widgets.text("curated_schema", "")

catalog = dbutils.widgets.get("catalog").strip()
enriched_schema = dbutils.widgets.get("enriched_schema").strip()
curated_schema = dbutils.widgets.get("curated_schema").strip()

if not all([catalog, enriched_schema, curated_schema]):
    raise ValueError("catalog, enriched_schema, and curated_schema are required")

source_table = f"{catalog}.{enriched_schema}.orders_enriched"
target_view = f"{catalog}.{curated_schema}.daily_sales_summary"

print(f"Source placeholder table: {source_table}")
print(f"Target placeholder view: {target_view}")

# Placeholder curated SQL:
# spark.sql(f"""
# CREATE OR REPLACE VIEW {target_view} AS
# SELECT
#   date(order_timestamp) AS order_date,
#   count(*) AS order_count,
#   sum(order_total) AS sales_total
# FROM {source_table}
# GROUP BY date(order_timestamp)
# """)
