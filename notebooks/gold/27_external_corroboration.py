# Databricks notebook source
# MAGIC %md
# MAGIC # Gold 27 · Is the facility also in the government's hospital directory?
# MAGIC
# MAGIC | Output | What |
# MAGIC |---|---|
# MAGIC | `hc_gold.facility_external_matches` | one row per our facility that matches a National Health Portal directory hospital |
# MAGIC | `hc_gold.ext_directory_unmatched` | directory hospitals not in our data, with the best location we have for them |
# MAGIC
# MAGIC **Match rule** (`src/hc/ext.py`, unit-tested): same 6-digit PIN, and names agree (60% of the shorter
# MAGIC name's distinctive words, with at least one word that isn't generic like "City" or "Shree"; or identical
# MAGIC once spaces are removed). When both sides have real coordinates they must also be within 5 km.
# MAGIC A match is evidence that **the facility exists**, from an independent source. It says nothing about
# MAGIC services: gold/22 uses it to waive the "few web sources" penalty and adds a supporting fact.

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

import math

import pandas as pd

from hc import ext
from hc.io import write_table

S, G = cfg.silver, cfg.gold

ours = spark.table(S("facility_master")).where("pin IS NOT NULL AND NOT is_malformed").select(
    "facility_id", "name", "pin", "lat", "lon", "location_source"
)
nhp = spark.table(S("ext_hospital_directory")).where("pin IS NOT NULL").select(
    "nhp_id", F.col("name").alias("nhp_name"), "pin", F.col("lat").alias("nhp_lat"), F.col("lon").alias("nhp_lon"),
    "ownership", "care_type", "district_code", F.col("district").alias("nhp_district"), F.col("state").alias("nhp_state"),
)
pairs = ours.join(nhp, "pin").toPandas()
print(f"{len(pairs):,} same-PIN candidate pairs")


def km(a_lat, a_lon, b_lat, b_lon):
    la1, lo1, la2, lo2 = map(math.radians, (a_lat, a_lon, b_lat, b_lon))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def score(r):
    if not ext.names_match(r["name"], r["nhp_name"]):
        return None
    real_ours = r["location_source"] == "listed coordinates" and pd.notna(r["lat"])
    if real_ours and pd.notna(r["nhp_lat"]):
        d = km(r["lat"], r["lon"], r["nhp_lat"], r["nhp_lon"])
        if d > ext.MATCH_MAX_KM:
            return None
        r["distance_km"] = round(d, 2)
    r["overlap"] = round(ext.token_overlap(ext.name_tokens(r["name"]), ext.name_tokens(r["nhp_name"])), 3)
    return r


hits = [x for x in (score(dict(r)) for _, r in pairs.iterrows()) if x]
m = pd.DataFrame(hits) if hits else pd.DataFrame(columns=list(pairs.columns) + ["distance_km", "overlap"])
if "distance_km" not in m:
    m["distance_km"] = None
m = m.sort_values(["facility_id", "overlap"], ascending=[True, False]).drop_duplicates("facility_id")
m["method"] = ["same PIN + name + within 5 km" if pd.notna(d) else "same PIN + name" for d in m["distance_km"]]

cols = ["facility_id", "nhp_id", "name", "nhp_name", "pin", "overlap", "distance_km", "method", "ownership", "care_type",
        "district_code", "nhp_district", "nhp_state"]
schema = ("facility_id string, nhp_id string, name string, nhp_name string, pin string, overlap double, distance_km double, "
          "method string, ownership string, care_type string, district_code int, nhp_district string, nhp_state string")
mdf = spark.createDataFrame(m[cols].astype(object).where(m[cols].notna(), None), schema)
write_table(mdf, G("facility_external_matches"))
spark.sql(
    f"COMMENT ON TABLE {G('facility_external_matches')} IS 'Our facilities that also appear in the National Health Portal hospital directory "
    "(same PIN + name match, src/hc/ext.py). Independent evidence that the facility exists; not evidence of services.'"
)

# COMMAND ----------

# MAGIC %md ## Directory hospitals we don't have (for coverage, and a future "listed nearby, unverified" list)

# COMMAND ----------

matched_ids = spark.table(G("facility_external_matches")).select("nhp_id")
pin_pts = spark.table(G("location_lookup")).where("kind = 'pin'").select(
    F.col("name_key").alias("pin"), F.col("lat").alias("pin_lat"), F.col("lon").alias("pin_lon")
)
un = (
    spark.table(S("ext_hospital_directory")).join(matched_ids, "nhp_id", "left_anti")
    .join(F.broadcast(pin_pts), "pin", "left")
    .withColumn("location_source", F.when(F.col("coords_valid"), "listed coordinates").when(F.col("pin_lat").isNotNull(), "PIN code area"))
    .withColumn("lat", F.coalesce("lat", "pin_lat"))
    .withColumn("lon", F.coalesce("lon", "pin_lon"))
    .select("nhp_id", "name", "ownership", "care_type", "address", "district", "state", "district_code", "pin", "phone",
            "lat", "lon", "location_source", "specialties")
)
write_table(un, G("ext_directory_unmatched"))
spark.sql(
    f"COMMENT ON TABLE {G('ext_directory_unmatched')} IS 'National Health Portal directory hospitals that are not in the Virtue Foundation data. "
    "Existence listed by government; services unknown. location_source says how lat/lon was set.'"
)

# COMMAND ----------

n_ours = ours.count()
n_m = spark.table(G("facility_external_matches")).count()
print(f"matched {n_m:,} of {n_ours:,} facilities with a PIN ({n_m / n_ours:.1%})")
display(spark.table(G("facility_external_matches")).orderBy(F.rand(7)).limit(25))
