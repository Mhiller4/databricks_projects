# Databricks notebook source
# MAGIC %md
# MAGIC # Gold 28 · Coverage and verified supply per district → `hc_gold.district_coverage`
# MAGIC
# MAGIC One row per Census 2011 district (641), for maps and planners:
# MAGIC
# MAGIC | Column group | Meaning |
# MAGIC |---|---|
# MAGIC | `n_directory_hospitals`, `n_directory_public` | hospitals the government directory lists in the district |
# MAGIC | `n_our_facilities`, `n_our_in_directory` | Virtue Foundation records located in the district, and how many matched the directory |
# MAGIC | `coverage_ratio` | `n_our_facilities / n_directory_hospitals`: how much of the listed hospital base our data covers (a blind-spot indicator, not a quality score) |
# MAGIC | `verified_<service>` | facilities with **direct** evidence and High/Medium confidence for the service |
# MAGIC | NFHS-5 indicators | joined by district + state name where the 2011 name still exists (`nfhs_matched`) |
# MAGIC
# MAGIC No population data is available here, so there are no per-capita rates.

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

from hc import care
from hc.io import write_table

S, G = cfg.silver, cfg.gold
SVC = [s.key for s in care.SERVICES]

bnd = spark.table(S("district_boundaries_2011")).select(
    "dist_key", "district_code", "district", "state", "district_key", "state_key", "centroid_lat", "centroid_lon"
)
fd = spark.table(G("facility_district"))

ours = fd.groupBy("dist_key").agg(F.countDistinct("facility_id").alias("n_our_facilities"))
in_dir = (
    fd.join(spark.table(G("facility_external_matches")).select("facility_id"), "facility_id")
    .groupBy("dist_key").agg(F.countDistinct("facility_id").alias("n_our_in_directory"))
)
nhp = spark.table(S("ext_hospital_directory")).groupBy(F.col("district_code")).agg(
    F.count("*").alias("n_directory_hospitals"), F.count_if(F.col("ownership") == "public").alias("n_directory_public")
)
verified = (
    spark.table(G("care_finder_index"))
    .where("evidence_tier = 'direct' AND confidence IN ('High', 'Medium')")
    .select("facility_id", "service_key").distinct()
    .join(fd.select("facility_id", "dist_key"), "facility_id")
    .groupBy("dist_key").pivot("service_key", SVC).agg(F.countDistinct("facility_id"))
)
for s in SVC:
    verified = verified.withColumnRenamed(s, f"verified_{s}")

NFHS_COLS = {
    "institutional_birth_5y_pct": "nfhs_institutional_births_pct",
    "births_delivered_by_csection_5y_pct": "nfhs_csection_births_pct",
    "hh_member_covered_health_insurance_pct": "nfhs_health_insurance_pct",
    "women_age_15_49_who_are_literate_pct": "nfhs_women_literate_pct",
    "child_u5_who_are_stunted_height_for_age_18_pct": "nfhs_child_stunting_pct",
    "mothers_who_had_at_least_4_anc_visits_lb5y_pct": "nfhs_4plus_anc_visits_pct",
    "hh_electricity_pct": "nfhs_electricity_pct",
}
alias = F.create_map(*[x for kv in care.STATE_ALIASES.items() for x in (F.lit(kv[0]), F.lit(kv[1]))])


def k(c):
    return F.regexp_replace(F.upper(F.trim(c)), "[^A-Z0-9]", "")


nfhs = (
    spark.table(S("vf_nfhs_5_district_health_indicators"))
    .select(k(F.col("district_name")).alias("district_key"), F.coalesce(alias[k(F.col("state_ut"))], k(F.col("state_ut"))).alias("state_key"),
            *[F.col(c).cast("double").alias(a) for c, a in NFHS_COLS.items()])
    .dropDuplicates(["district_key", "state_key"])
    .withColumn("nfhs_matched", F.lit(True))
)

out = (
    bnd.join(ours, "dist_key", "left").join(in_dir, "dist_key", "left").join(nhp, "district_code", "left")
    .join(verified, "dist_key", "left").join(nfhs, ["district_key", "state_key"], "left")
    .fillna(0, subset=["n_our_facilities", "n_our_in_directory", "n_directory_hospitals", "n_directory_public"] + [f"verified_{s}" for s in SVC])
    .fillna(False, subset=["nfhs_matched"])
    .withColumn("coverage_ratio", F.round(F.expr("try_divide(n_our_facilities, nullif(n_directory_hospitals, 0))"), 3))
)
write_table(out, G("district_coverage"))
spark.sql(
    f"COMMENT ON TABLE {G('district_coverage')} IS 'Per Census 2011 district: government-directory hospitals vs Virtue Foundation facilities "
    "(coverage_ratio), verified facilities per Care Finder service, and NFHS-5 indicators where the district name matches.'"
)

# COMMAND ----------

display(spark.sql(f"""
  SELECT count(*) AS districts,
         count_if(n_our_facilities = 0) AS districts_with_none_of_our_facilities,
         count_if(n_directory_hospitals > 0 AND n_our_facilities = 0) AS listed_hospitals_but_none_of_ours,
         count_if(verified_dialysis = 0) AS districts_without_verified_dialysis,
         count_if(verified_emergency_c_section = 0) AS districts_without_verified_c_section,
         count_if(nfhs_matched) AS nfhs_matched
  FROM {G('district_coverage')}
"""))
