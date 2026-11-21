# Databricks notebook source
# MAGIC %md
# MAGIC # Silver 14 · District boundaries (Census 2011) → `hc_silver.district_boundaries_2011`
# MAGIC
# MAGIC 641 district polygons. Used to put every facility in a district (gold/26), for district maps, and to join
# MAGIC NFHS-5. NFHS-5 lists 706 districts because many were split after 2011, so the name match below is
# MAGIC partial; the match rate is printed.
# MAGIC
# MAGIC Geometry stays as GeoJSON text; bounding boxes (`bbox_*`) make the point-in-polygon join fast.

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

from hc import care
from hc.io import write_table

B, S = cfg.bronze, cfg.silver


def k(c):
    return F.regexp_replace(F.upper(F.trim(c)), "[^A-Z0-9]", "")


alias = F.create_map(*[x for kv in care.STATE_ALIASES.items() for x in (F.lit(kv[0]), F.lit(kv[1]))])


def state_key(c):
    return F.coalesce(alias[k(c)], k(c))


b = spark.table(B("ext_district_boundaries_2011")).select(
    F.col("dist_key").cast("int").alias("dist_key"),
    F.col("censuscode").cast("int").alias("district_code"),
    F.col("st_code").cast("int").alias("state_code"),
    F.trim("district").alias("district"),
    F.trim("st_nm").alias("state"),
    "geometry",
)
g = F.expr("st_geomfromgeojson(geometry)")
b = (
    b.withColumn("_g", g)
    .withColumn("centroid_lon", F.expr("st_x(st_centroid(_g))"))
    .withColumn("centroid_lat", F.expr("st_y(st_centroid(_g))"))
    .withColumn("bbox_lon_min", F.expr("st_xmin(_g)"))
    .withColumn("bbox_lon_max", F.expr("st_xmax(_g)"))
    .withColumn("bbox_lat_min", F.expr("st_ymin(_g)"))
    .withColumn("bbox_lat_max", F.expr("st_ymax(_g)"))
    .drop("_g")
    .withColumn("district_key", k(F.col("district")))
    .withColumn("state_key", state_key(F.col("state")))
)
write_table(b, S("district_boundaries_2011"))
spark.sql(
    f"COMMENT ON TABLE {S('district_boundaries_2011')} IS 'India district polygons (Census 2011 codes). geometry = GeoJSON text; "
    "bbox_* and centroid_* precomputed.'"
)

# COMMAND ----------

# MAGIC %md ## How well do NFHS-5 district names match the 2011 boundaries?

# COMMAND ----------

nfhs = spark.table(S("vf_nfhs_5_district_health_indicators")).select(
    k(F.col("district_name")).alias("district_key"), state_key(F.col("state_ut")).alias("state_key"), "district_name", "state_ut"
)
m = nfhs.join(spark.table(S("district_boundaries_2011")).select("district_key", "state_key", "dist_key"), ["district_key", "state_key"], "left")
display(m.agg(F.count("*").alias("nfhs_districts"), F.count("dist_key").alias("matched_to_2011_boundary")))
display(m.where("dist_key IS NULL").select("state_ut", "district_name").orderBy("state_ut").limit(50))
