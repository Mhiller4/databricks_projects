# Databricks notebook source
# MAGIC %md
# MAGIC # Databricks Crash Course (Template)
# MAGIC
# MAGIC Audience: data engineers and analysts who are experienced in data work and new to Databricks.
# MAGIC
# MAGIC This notebook is a reference-style placeholder and is intentionally not tied to a production workflow.

# COMMAND ----------
# MAGIC %md
# MAGIC ## 1) Widgets and Parameter Input
# MAGIC
# MAGIC Widgets are lightweight runtime inputs for notebooks and jobs.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.dropdown("run_mode", "demo", ["demo", "dry_run", "full"])

catalog = dbutils.widgets.get("catalog").strip()
run_mode = dbutils.widgets.get("run_mode").strip()
print(f"catalog={catalog or '<empty>'}, run_mode={run_mode}")

# COMMAND ----------
# MAGIC %md
# MAGIC ## 2) Spark DataFrame Basics (Python)

# COMMAND ----------

demo_df = spark.createDataFrame(
    [
        (1, "A", 100.0),
        (2, "B", 250.0),
        (3, "A", 125.0),
    ],
    ["order_id", "segment", "amount"],
)

display(demo_df)

# COMMAND ----------
# MAGIC %md
# MAGIC ## 3) SQL in Notebooks
# MAGIC
# MAGIC Use `%sql` for direct SQL cells.

# COMMAND ----------
# MAGIC %sql
# MAGIC -- Placeholder SQL example
# MAGIC SELECT
# MAGIC   segment,
# MAGIC   COUNT(*) AS row_count,
# MAGIC   SUM(amount) AS total_amount
# MAGIC FROM VALUES
# MAGIC   (1, 'A', 100.0),
# MAGIC   (2, 'B', 250.0),
# MAGIC   (3, 'A', 125.0)
# MAGIC AS t(order_id, segment, amount)
# MAGIC GROUP BY segment
# MAGIC ORDER BY segment

# COMMAND ----------
# MAGIC %md
# MAGIC ## 4) Other Languages in Databricks Notebooks
# MAGIC
# MAGIC You can switch language per cell:
# MAGIC - `%python` for PySpark workflows
# MAGIC - `%sql` for SQL transformations
# MAGIC - `%scala` for JVM/Spark APIs
# MAGIC - `%r` for R analytics (if runtime supports it)
# MAGIC - `%sh` for shell commands (use carefully in governed environments)

# COMMAND ----------
# MAGIC %md
# MAGIC ## 5) dbutils Overview
# MAGIC
# MAGIC Common modules:
# MAGIC - `dbutils.widgets`: runtime inputs.
# MAGIC - `dbutils.fs`: DBFS/Volumes file operations.
# MAGIC - `dbutils.secrets`: retrieve secrets from configured secret scopes.
# MAGIC - `dbutils.notebook`: run one notebook from another notebook.

# COMMAND ----------

# Placeholder only: prints the landing location pattern.
if catalog:
    example_path = f"/Volumes/{catalog}/template_drop_zone/landing/orders/incoming"
    print(f"Example volume path: {example_path}")
else:
    print("Set widget 'catalog' to see a volume path example.")

# COMMAND ----------
# MAGIC %md
# MAGIC ## 6) Databricks Concepts: Quick Definitions
# MAGIC
# MAGIC - Unity Catalog: centralized governance for data, AI assets, and access controls.
# MAGIC - Asset Bundles (DAB): project-as-code model for jobs, pipelines, and deployment targets.
# MAGIC - Jobs: scheduled or triggered task orchestration in Databricks.
# MAGIC - Volumes: governed storage locations in Unity Catalog.
# MAGIC - Genie Space: a natural-language analytics interface for asking business questions over curated data models.

# COMMAND ----------
# MAGIC %md
# MAGIC ## 7) Next Learning Steps
# MAGIC
# MAGIC 1. Deploy this template bundle to `personal_dev`.
# MAGIC 2. Run `template_databricks_tooling_demo_job`.
# MAGIC 3. Walk the medallion jobs in order and replace placeholders with real logic.
