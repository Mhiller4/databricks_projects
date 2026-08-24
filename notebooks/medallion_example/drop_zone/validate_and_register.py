# Databricks notebook source
# MAGIC %md
# MAGIC # Medallion Example: Drop-Zone Validation
# MAGIC
# MAGIC Placeholder notebook showing the structure for:
# MAGIC 1) validating incoming files,
# MAGIC 2) recording file metadata,
# MAGIC 3) preparing for raw ingestion.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("drop_zone_schema", "")
dbutils.widgets.text("drop_zone_volume", "landing")

catalog = dbutils.widgets.get("catalog").strip()
drop_zone_schema = dbutils.widgets.get("drop_zone_schema").strip()
drop_zone_volume = dbutils.widgets.get("drop_zone_volume").strip()

if not catalog or not drop_zone_schema:
    raise ValueError("catalog and drop_zone_schema must be provided")

base_path = f"/Volumes/{catalog}/{drop_zone_schema}/{drop_zone_volume}/orders/incoming"
print(f"Template path: {base_path}")

# Placeholder: replace with source-specific validation rules.
print("Validation placeholder: schema checks, naming checks, duplicate checks")

# Placeholder: record metadata for observability and replay.
print("Registration placeholder: insert file rows into a manifest table")
