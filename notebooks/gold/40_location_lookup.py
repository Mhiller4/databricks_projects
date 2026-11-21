# Databricks notebook source
# MAGIC %md
# MAGIC # Gold 40 · `location_lookup`: what the user types → a point on the map
# MAGIC
# MAGIC One row per (kind, name, state). Used by `resolve_location()` (gold/43).
# MAGIC
# MAGIC | kind | from | priority |
# MAGIC |---|---|---|
# MAGIC | `pin` | India Post directory: median of post-office points per PIN | 1 |
# MAGIC | `city` | facility records with trusted coordinates: median per city (where the hospitals are) | 2 |
# MAGIC | `district` | India Post directory: median per district (can sit in the countryside) | 3 |
# MAGIC | `post_office` | India Post office names (suffixes like "B.O" removed) | 4 |
# MAGIC | `state` | India Post directory | 5 |
# MAGIC
# MAGIC Medians, not means: about 1 in 20 directory points are in the wrong place (a Patna PIN plotted in
# MAGIC Uttar Pradesh), and a median ignores them. Old and new names (Bangalore / Bengaluru, Gurgaon / Gurugram) are added as aliases.

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

from hc import care
from hc.io import write_table

S, G = cfg.silver, cfg.gold
B = care.INDIA_BBOX


def k(c):
    return F.regexp_replace(F.upper(F.trim(c)), "[^A-Z0-9]", "")


pins = spark.table(S("vf_india_post_pincode_directory")).where(
    F.col("latitude").between(B["lat_min"], B["lat_max"]) & F.col("longitude").between(B["lon_min"], B["lon_max"]) & (F.length("statename") > 0)
)
pins = pins.select(
    "pincode", "latitude", "longitude",
    F.initcap("district").alias("district"),
    F.initcap("statename").alias("state"),
    F.initcap(F.trim(F.regexp_replace("officename", r"(?i)\s+(b\.?\s?o|s\.?\s?o|h\.?\s?o|g\.?\s?p\.?\s?o|bo|so|ho|gpo)\.?$", ""))).alias("office"),
)

pin_rows = (
    pins.groupBy("pincode")
    .agg(
        F.percentile_approx("latitude", 0.5).alias("lat"),
        F.percentile_approx("longitude", 0.5).alias("lon"),
        F.count("*").alias("n_points"),
        F.mode("district").alias("district"),
        F.mode("state").alias("state"),
    )
    .select(
        F.lit("pin").alias("kind"), F.lit(1).alias("priority"), F.col("pincode").alias("name_key"),
        F.format_string("PIN %s (%s, %s)", "pincode", "district", "state").alias("display_name"),
        "district", "state", "lat", "lon", "n_points",
    )
)

district_rows = (
    pins.groupBy(k(F.col("district")).alias("name_key"), "state")
    .agg(F.percentile_approx("latitude", 0.5).alias("lat"), F.percentile_approx("longitude", 0.5).alias("lon"),
         F.count("*").alias("n_points"), F.first("district").alias("district"))
    .select(F.lit("district").alias("kind"), F.lit(3).alias("priority"), "name_key",
            F.format_string("%s district, %s", "district", "state").alias("display_name"), "district", "state", "lat", "lon", "n_points")
)

fac = spark.table(S("facility_master")).where(
    "location_source = 'listed coordinates' AND coalesce(pin_distance_km, 0) <= 50 AND city IS NOT NULL AND state IS NOT NULL AND NOT is_malformed"
)
city_rows = (
    fac.groupBy(k(F.col("city")).alias("name_key"), "state")
    .agg(F.percentile_approx("lat", 0.5).alias("lat"), F.percentile_approx("lon", 0.5).alias("lon"),
         F.count("*").alias("n_points"), F.mode(F.initcap("city")).alias("city"), F.mode("district").alias("district"))
    .where("name_key <> ''")
    .select(F.lit("city").alias("kind"), F.lit(2).alias("priority"), "name_key",
            F.format_string("%s, %s", "city", "state").alias("display_name"), "district", "state", "lat", "lon", "n_points")
)

office_rows = (
    pins.where(F.length("office") > 0)
    .groupBy(k(F.col("office")).alias("name_key"), "state")
    .agg(F.percentile_approx("latitude", 0.5).alias("lat"), F.percentile_approx("longitude", 0.5).alias("lon"),
         F.count("*").alias("n_points"), F.first("office").alias("office"), F.first("district").alias("district"))
    .select(F.lit("post_office").alias("kind"), F.lit(4).alias("priority"), "name_key",
            F.format_string("%s (post office), %s district, %s", "office", "district", "state").alias("display_name"), "district", "state", "lat", "lon", "n_points")
)

state_rows = (
    pins.groupBy(k(F.col("state")).alias("name_key"), "state")
    .agg(F.percentile_approx("latitude", 0.5).alias("lat"), F.percentile_approx("longitude", 0.5).alias("lon"), F.count("*").alias("n_points"))
    .select(F.lit("state").alias("kind"), F.lit(5).alias("priority"), "name_key",
            F.concat(F.col("state"), F.lit(" (whole state: pick a city or PIN for better results)")).alias("display_name"),
            F.lit(None).cast("string").alias("district"), "state", "lat", "lon", "n_points")
)

lookup = district_rows.unionByName(city_rows).unionByName(office_rows).unionByName(state_rows)

# Old/new place-name aliases: copy the canonical rows under the alias key
alias_df = spark.createDataFrame(list(care.PLACE_ALIASES.items()), "alias_key string, canonical_key string")
alias_rows = (
    lookup.where(F.col("kind").isin("district", "city"))
    .join(F.broadcast(alias_df), F.col("name_key") == F.col("canonical_key"))
    .withColumn("name_key", F.col("alias_key"))
    .withColumn("display_name", F.concat(F.col("display_name"), F.lit(" [alias]")))
    .drop("alias_key", "canonical_key")
)
lookup = (
    pin_rows.unionByName(lookup)
    .unionByName(alias_rows)
    .dropDuplicates(["kind", "name_key", "state"])
    .withColumn("state_key", k(F.col("state")))
    .withColumn("lat", F.round("lat", 5))
    .withColumn("lon", F.round("lon", 5))
)
write_table(lookup, G("location_lookup"))
spark.sql(f"COMMENT ON TABLE {G('location_lookup')} IS 'PIN / district / city / post office / state name keys to a median point. Used by resolve_location().'")

display(spark.table(G("location_lookup")).groupBy("kind").count().orderBy("kind"))
