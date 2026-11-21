# Databricks notebook source
# MAGIC %md
# MAGIC # Silver 15 · PM-JAY demand by state → `hc_silver.ext_pmjay_state_demand`
# MAGIC
# MAGIC PM-JAY (Ayushman Bharat) publishes each state's **top** procedures and specialties for 2025. One row per
# MAGIC (state, kind, item), with the matching Care Finder service when there is one (`src/hc/ext.py`).
# MAGIC
# MAGIC Caveats, carried into gold: top-N lists only (a missing procedure is not zero), counts are as published
# MAGIC (the column label mentions a "scaling factor 100000", which we don't apply).

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

import pandas as pd

from hc import care, ext
from hc.io import write_table

B, S = cfg.bronze, cfg.silver

proc = spark.table(B("ext_pmjay_procedures_by_state")).select(
    F.lit("procedure").alias("kind"), "state", F.col("procedure_name").alias("item"),
    F.col("count_of_top_procedure_uom_number_scaling_factor_100000").alias("count_raw"),
    F.to_date("as_on_date", "dd-MMM-yyyy").alias("as_of"),
).toPandas()
spec = spark.table(B("ext_pmjay_specialties_by_state")).select(
    F.lit("specialty").alias("kind"), "state", F.col("category_of_top_speciality_in_health").alias("item"),
    F.col("count_of_top_speciality_in_health_uom_number_scaling_factor_100000").alias("count_raw"),
    F.to_date("calendarday", "yyyy-MM-dd").alias("as_of"),
).toPandas()

pdf = pd.concat([proc, spec], ignore_index=True)
pdf["count"] = pd.to_numeric(pdf["count_raw"], errors="coerce")
pdf["service_key"] = [
    ext.map_pmjay(i, ext.PMJAY_PROCEDURE_TO_SERVICE if kd == "procedure" else ext.PMJAY_SPECIALTY_TO_SERVICE)
    for i, kd in zip(pdf["item"], pdf["kind"])
]
sk = care.key
pdf["state_key"] = [care.STATE_ALIASES.get(sk(s), sk(s)) for s in pdf["state"]]
pdf = pdf.drop(columns=["count_raw"])

out = spark.createDataFrame(pdf[["kind", "state", "state_key", "item", "service_key", "count", "as_of"]].astype(object).where(pdf.notna(), None),
                            "kind string, state string, state_key string, item string, service_key string, count double, as_of date")
write_table(out, S("ext_pmjay_state_demand"))
spark.sql(
    f"COMMENT ON TABLE {S('ext_pmjay_state_demand')} IS 'PM-JAY 2025 top procedures/specialties per state, mapped to Care Finder services. "
    "Top-N only: a missing item is not zero. Counts as published.'"
)

# COMMAND ----------

display(spark.sql(f"""
  SELECT kind, coalesce(service_key, '(not a Care Finder service)') AS service, round(sum(count)) AS total, count(DISTINCT state) AS states
  FROM {S('ext_pmjay_state_demand')} GROUP BY 1, 2 ORDER BY 1, 3 DESC
"""))
