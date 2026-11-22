# Databricks notebook source
# MAGIC %md
# MAGIC # Gold 35 · Symptom → service map (`hc_gold.symptom_service_map`)
# MAGIC
# MAGIC For callers who don't know what kind of care they need. One row per warning sign × Care Finder service,
# MAGIC with urgency, a red-flag marker (call 108 first), what to tell the hospital, and the public source of the sign.
# MAGIC The map lives in `src/hc/symptoms.py` (shared with the app); this notebook publishes it so it is visible and
# MAGIC queryable in Databricks.
# MAGIC
# MAGIC It routes to the **kind of place**, never to a diagnosis. `general_care` = not one of the 16 services
# MAGIC (nearest district hospital or a doctor).

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

import importlib

import hc.symptoms as sy
from hc.io import write_table

importlib.reload(sy)
df = spark.createDataFrame(
    sy.rows(),
    "sign_id string, group string, who string, says string, phrases array<string>, service_key string, service_rank int, "
    "urgency string, red_flag boolean, advice string, tell_them string, basis string",
)
write_table(df, cfg.gold("symptom_service_map"))
spark.sql(
    f"COMMENT ON TABLE {cfg.gold('symptom_service_map')} IS 'Warning signs -> Care Finder services (routing, not diagnosis). "
    "red_flag = tell the caller to call 108 first. Source: src/hc/symptoms.py; basis = public warning-sign list.'"
)

# COMMAND ----------

display(spark.sql(f"""
  SELECT service_key, count(DISTINCT sign_id) AS signs, count_if(red_flag) AS red_flag_rows,
         concat_ws('; ', collect_set(says)) AS example_signs
  FROM {cfg.gold('symptom_service_map')} GROUP BY 1 ORDER BY 2 DESC
"""))
