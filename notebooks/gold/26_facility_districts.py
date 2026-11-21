# Databricks notebook source
# MAGIC %md
# MAGIC # Gold 26 · Which Census 2011 district is each facility in? → `hc_gold.facility_district`
# MAGIC
# MAGIC Point-in-polygon on the facility's location (the one `facility_master` decided to use) against the 2011
# MAGIC district boundaries, with Databricks spatial SQL (`st_contains`). A bounding-box pre-filter keeps it fast.
# MAGIC Facilities with no location, or a point outside every polygon (coast, border), get no district.

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

from pyspark.sql import Window

from hc.io import write_table

S, G = cfg.silver, cfg.gold

fac = spark.table(S("facility_master")).where("lat IS NOT NULL AND NOT is_malformed").select(
    "facility_id", "lat", "lon", F.col("district").alias("district_text"), F.col("state").alias("state_text")
)
bnd = spark.table(S("district_boundaries_2011"))

cand = fac.join(
    F.broadcast(bnd.select("dist_key", "district_code", "district", "state", "geometry",
                           "bbox_lat_min", "bbox_lat_max", "bbox_lon_min", "bbox_lon_max")),
    F.col("lat").between(F.col("bbox_lat_min"), F.col("bbox_lat_max")) & F.col("lon").between(F.col("bbox_lon_min"), F.col("bbox_lon_max")),
)
inside = cand.where(F.expr("st_contains(st_geomfromgeojson(geometry), st_point(lon, lat, 4326))"))
w = Window.partitionBy("facility_id").orderBy("dist_key")  # boundaries don't overlap; tie-break is deterministic
out = (
    inside.withColumn("_rn", F.row_number().over(w)).where("_rn = 1")
    .select("facility_id", "dist_key", "district_code", F.col("district").alias("district_2011"), F.col("state").alias("state_2011"),
            "district_text", "state_text")
)
write_table(out, G("facility_district"))
spark.sql(f"COMMENT ON TABLE {G('facility_district')} IS 'Facility -> Census 2011 district (point in polygon on the facility location used by Care Finder).'")

# COMMAND ----------

n_loc = fac.count()
n_in = spark.table(G("facility_district")).count()
n_fixed = spark.table(G("facility_district")).where("district_text IS NULL").count()
print(f"{n_in:,} of {n_loc:,} located facilities placed in a district ({n_in / n_loc:.1%}); {n_fixed:,} had no district in the record")
