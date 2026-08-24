# Databricks notebook source
# MAGIC %md
# MAGIC # Medallion Example: Raw Ingestion
# MAGIC
# MAGIC Placeholder notebook for loading landed data into a raw Delta table.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("drop_zone_schema", "")
dbutils.widgets.text("drop_zone_volume", "landing")
dbutils.widgets.text("raw_schema", "")

catalog = dbutils.widgets.get("catalog").strip()
drop_zone_schema = dbutils.widgets.get("drop_zone_schema").strip()
drop_zone_volume = dbutils.widgets.get("drop_zone_volume").strip()
raw_schema = dbutils.widgets.get("raw_schema").strip()

if not all([catalog, drop_zone_schema, raw_schema]):
    raise ValueError("catalog, drop_zone_schema, and raw_schema are required")

source_path = f"/Volumes/{catalog}/{drop_zone_schema}/{drop_zone_volume}/orders/incoming"
target_table = f"{catalog}.{raw_schema}.orders_raw"

print(f"Source placeholder path: {source_path}")
print(f"Target placeholder table: {target_table}")

# Placeholder read/write pattern:
# df = spark.read.format("csv").option("header", True).load(source_path)
# df = df.withColumn("ingestion_ts", current_timestamp())
# df.write.format("delta").mode("append").saveAsTable(target_table)
