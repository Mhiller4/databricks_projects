# Databricks notebook source
# MAGIC %md
# MAGIC # Medallion Example: Enriched Merge
# MAGIC
# MAGIC Placeholder notebook for transforming raw records and merging into enriched tables.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("raw_schema", "")
dbutils.widgets.text("enriched_schema", "")

catalog = dbutils.widgets.get("catalog").strip()
raw_schema = dbutils.widgets.get("raw_schema").strip()
enriched_schema = dbutils.widgets.get("enriched_schema").strip()

if not all([catalog, raw_schema, enriched_schema]):
    raise ValueError("catalog, raw_schema, and enriched_schema are required")

source_table = f"{catalog}.{raw_schema}.orders_raw"
target_table = f"{catalog}.{enriched_schema}.orders_enriched"

print(f"Source placeholder table: {source_table}")
print(f"Target placeholder table: {target_table}")

# Placeholder merge pattern for Type 1 behavior:
# spark.sql(f"""
# MERGE INTO {target_table} AS target
# USING (
#   SELECT order_id, customer_id, order_total, current_timestamp() AS updated_at
#   FROM {source_table}
# ) AS source
# ON target.order_id = source.order_id
# WHEN MATCHED THEN UPDATE SET *
# WHEN NOT MATCHED THEN INSERT *
# """)
