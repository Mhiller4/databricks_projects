# Databricks notebook source
# MAGIC %md
# MAGIC # Gold 29 · PM-JAY demand vs verified supply, by state → `hc_gold.pmjay_state_demand_vs_supply`
# MAGIC
# MAGIC Demand: 2025 PM-JAY (Ayushman Bharat) procedure counts mapped to Care Finder services (silver/15).
# MAGIC Supply: facilities in the state with **direct** evidence and High/Medium confidence for that service.
# MAGIC `demand_per_verified_facility` ranks where a verified facility carries the most demand, which is where
# MAGIC better data, or more capacity, matters most.
# MAGIC
# MAGIC Caveats (also in the table comment): PM-JAY lists only each state's **top** procedures, so a missing
# MAGIC state-service pair means "not in the top list", not zero. Supply is what *this dataset* can verify.

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

from pyspark.sql import Window

from hc import care
from hc.io import write_table

S, G = cfg.silver, cfg.gold
alias = F.create_map(*[x for kv in care.STATE_ALIASES.items() for x in (F.lit(kv[0]), F.lit(kv[1]))])


def state_key(c):
    k = F.regexp_replace(F.upper(F.trim(c)), "[^A-Z0-9]", "")
    return F.coalesce(alias[k], k)


pm = spark.table(S("ext_pmjay_state_demand")).where("service_key IS NOT NULL")
demand = pm.where("kind = 'procedure'").groupBy("state_key", "service_key").agg(
    F.first("state").alias("pmjay_state"), F.sum("count").alias("pmjay_procedures_2025"),
    F.concat_ws("; ", F.collect_set("item")).alias("pmjay_items"),
)
spec = pm.where("kind = 'specialty'").groupBy("state_key", "service_key").agg(F.sum("count").alias("pmjay_specialty_cases_2025"))

fm = spark.table(S("facility_master")).select("facility_id", "state", state_key(F.col("state")).alias("state_key"))
supply = (
    spark.table(G("care_finder_index")).where("evidence_tier = 'direct' AND confidence IN ('High', 'Medium')")
    .select("facility_id", "service_key").distinct()
    .join(fm, "facility_id")
    .groupBy("state_key", "service_key").agg(F.first("state").alias("state"), F.countDistinct("facility_id").alias("verified_facilities"))
)

out = (
    demand.join(spec, ["state_key", "service_key"], "full").join(supply, ["state_key", "service_key"], "left")
    .withColumn("state", F.coalesce("state", "pmjay_state"))
    .fillna(0, subset=["verified_facilities"])
    .withColumn("demand_per_verified_facility",
                F.round(F.expr("try_divide(pmjay_procedures_2025, nullif(verified_facilities, 0))")))
    .where("pmjay_procedures_2025 IS NOT NULL OR pmjay_specialty_cases_2025 IS NOT NULL")
)
w = Window.partitionBy("service_key").orderBy(F.col("verified_facilities").asc(), F.col("pmjay_procedures_2025").desc_nulls_last())
out = out.withColumn("gap_rank_within_service", F.row_number().over(w)).drop("pmjay_state")
write_table(out, G("pmjay_state_demand_vs_supply"))
spark.sql(
    f"COMMENT ON TABLE {G('pmjay_state_demand_vs_supply')} IS 'PM-JAY 2025 demand (top procedures per state, mapped to Care Finder services) vs "
    "facilities this dataset verifies (direct evidence, High/Medium). Top-N lists only: a missing pair is not zero.'"
)

# COMMAND ----------

display(spark.sql(f"""
  SELECT state, service_key, pmjay_procedures_2025, verified_facilities, demand_per_verified_facility
  FROM {G('pmjay_state_demand_vs_supply')} WHERE service_key = 'dialysis' AND pmjay_procedures_2025 IS NOT NULL
  ORDER BY demand_per_verified_facility DESC NULLS FIRST
"""))
