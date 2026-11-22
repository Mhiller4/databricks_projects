# Databricks notebook source
# MAGIC %md
# MAGIC # Silver 13 · National Health Portal hospital directory → `hc_silver.ext_hospital_directory`
# MAGIC
# MAGIC An independent, government-published list of ~30k hospitals. We use it to **corroborate** that our
# MAGIC facilities exist (gold/27) and to measure **coverage** per district (gold/28). It has almost no service
# MAGIC detail, so it never counts as evidence that a facility offers a service.
# MAGIC
# MAGIC Cleaning: "0", "NA" and "Error" mean missing. Coordinates are kept only inside India **and** when they
# MAGIC aren't a geocoded city centre (the same point used by more than `ext.CENTROID_REPEAT` hospitals).
# MAGIC `state_code` / `district_code` are Census 2011 codes (they join to the district boundaries).

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

from pyspark.sql import Window

from hc import care, ext, geo
from hc.io import write_table
from hc.text import LIST_SPLIT, clean_text

B, S = cfg.bronze, cfg.silver
BB = care.INDIA_BBOX
d = spark.table(B("ext_nhp_hospital_directory"))


def nz(c):
    """Normalise text (literal \\n, line breaks, invisible chars, HTML entities); placeholders -> NULL."""
    v = clean_text(F.col(c))
    return F.when(~F.lower(v).isin("", "0", "na", "n/a", "error", "null", "-"), v)


def arr(c):
    """Free-text lists use commas, semicolons, pipes AND literal \\n as separators."""
    raw = F.when(~F.lower(F.trim(F.col(c))).isin("", "0", "na", "n/a", "error", "null", "-"), F.col(c))
    parts = F.transform(F.split(raw, LIST_SPLIT), lambda x: F.regexp_replace(clean_text(x), r"[.]+$", ""))
    return F.array_distinct(F.filter(parts, lambda x: F.length(x) > 1))


lat = F.expr("try_cast(trim(get(split(location_coordinates, ','), 0)) AS DOUBLE)")
lon = F.expr("try_cast(trim(get(split(location_coordinates, ','), 1)) AS DOUBLE)")

out = d.select(
    nz("sr_no").alias("nhp_id"),
    nz("hospital_name").alias("name"),
    F.when(nz("hospital_category").rlike("(?i)public|gov"), "public")
     .when(nz("hospital_category").rlike("(?i)private"), "private").alias("ownership"),
    nz("hospital_care_type").alias("care_type"),
    nz("discipline_systems_of_medicine").alias("system_of_medicine"),
    F.concat_ws(", ", nz("address_original_first_line"), nz("location"), nz("town"), nz("village")).alias("address"),
    nz("state").alias("state"),
    nz("district").alias("district"),
    nz("subdistrict").alias("subdistrict"),
    geo.pin6(F.col("pincode")).alias("pin"),
    F.coalesce(nz("telephone"), nz("mobile_number"), nz("emergency_num")).alias("phone"),
    nz("ambulance_phone_no").alias("ambulance_phone"),
    nz("bloodbank_phone_no").alias("bloodbank_phone"),
    nz("website").alias("website"),
    arr("specialties").alias("specialties"),
    arr("facilities").alias("facilities"),
    F.expr("try_cast(nullif(total_num_beds, '0') AS INT)").alias("beds"),
    F.expr("try_cast(nullif(number_doctor, '0') AS INT)").alias("doctors"),
    F.expr("try_cast(nullif(establised_year, '0') AS INT)").alias("year_established"),
    nz("emergency_services").alias("emergency_services"),
    nz("empanelment_or_collaboration_with").alias("empanelment"),
    F.expr("try_cast(state_id AS INT)").alias("state_code"),
    F.expr("try_cast(district_id AS INT)").alias("district_code"),
    F.when(lat.between(BB["lat_min"], BB["lat_max"]) & lon.between(BB["lon_min"], BB["lon_max"]), lat).alias("lat_listed"),
    F.when(lat.between(BB["lat_min"], BB["lat_max"]) & lon.between(BB["lon_min"], BB["lon_max"]), lon).alias("lon_listed"),
)
w = Window.partitionBy("lat_listed", "lon_listed")
out = (
    out.withColumn("_n_same_point", F.when(F.col("lat_listed").isNotNull(), F.count("*").over(w)))
    .withColumn("coords_is_centroid", F.coalesce(F.col("_n_same_point") > ext.CENTROID_REPEAT, F.lit(False)))
    .withColumn("coords_valid", F.col("lat_listed").isNotNull() & ~F.col("coords_is_centroid"))
    .withColumn("lat", F.when(F.col("coords_valid"), F.col("lat_listed")))
    .withColumn("lon", F.when(F.col("coords_valid"), F.col("lon_listed")))
    .drop("_n_same_point")
    .where(F.col("name").isNotNull())
)
write_table(out, S("ext_hospital_directory"))
spark.sql(
    f"COMMENT ON TABLE {S('ext_hospital_directory')} IS 'National Health Portal hospital directory (Govt of India), cleaned. "
    "lat/lon only when real (inside India, not a repeated city-centre point). state_code/district_code = Census 2011.'"
)

# COMMAND ----------

display(spark.sql(f"""
  SELECT count(*) AS hospitals, count_if(pin IS NOT NULL) AS with_pin, count_if(lat_listed IS NOT NULL) AS with_coords,
         count_if(coords_is_centroid) AS coords_city_centre, count_if(coords_valid) AS coords_real,
         count_if(ownership = 'public') AS public, count_if(ownership = 'private') AS private,
         count_if(phone IS NOT NULL) AS with_phone, count_if(size(specialties) > 0) AS with_specialties,
         count(DISTINCT district_code) AS districts
  FROM {S('ext_hospital_directory')}
"""))
