# Databricks notebook source
# MAGIC %md
# MAGIC # Silver 13 · `facility_master`: one trustworthy-as-possible row per facility
# MAGIC
# MAGIC Input: `hc_silver.vf_facilities` (auto-cleaned) + `hc_silver.vf_india_post_pincode_directory`.
# MAGIC
# MAGIC | Problem in the raw data | What this notebook does |
# MAGIC |---|---|
# MAGIC | 253 spellings of 36 states, cities in the state field | canonical state: the text if valid (with aliases), else the text looked up as a district, else the PIN's state |
# MAGIC | lists stored as JSON text with repeats | parsed into arrays, de-duplicated, empty strings dropped |
# MAGIC | missing / out-of-India coordinates | location falls back to the PIN code's median post-office point, and says so |
# MAGIC | coordinates far from the PIN area | distance to the PIN centroid kept (`pin_distance_km`) for the trust score |
# MAGIC | rows with shifted columns | `is_malformed` flag |
# MAGIC | the same facility listed twice | `dup_reason` (shared `cluster_id`, or same name + PIN) |
# MAGIC
# MAGIC Nothing is deleted here: every record stays, with flags. The trust score (gold/42) decides how much they count.

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

from hc import care
from hc.geo import haversine_km
from hc.io import write_table

S = cfg.silver
B = care.INDIA_BBOX


def k(c):
    """SQL twin of care.key(): upper-case alphanumerics."""
    return F.regexp_replace(F.upper(F.trim(c)), "[^A-Z0-9]", "")


def s(c):
    """Trim, strip wrapping quotes, empty -> NULL."""
    v = F.trim(F.regexp_replace(F.col(c).cast("string"), '^"+|"+$', ""))
    return F.when(F.length(v) > 0, v)


def arr(c):
    parsed = F.coalesce(F.from_json(F.col(c), "array<string>"), F.array().cast("array<string>"))
    return F.array_distinct(F.filter(F.transform(parsed, lambda x: F.trim(x)), lambda x: F.length(x) > 0))


def first(a):
    """First element or NULL (element_at on an empty array errors under ANSI mode)."""
    return F.when(F.size(a) > 0, F.element_at(a, 1))


def in_india(lat, lon):
    return lat.between(B["lat_min"], B["lat_max"]) & lon.between(B["lon_min"], B["lon_max"])


raw = spark.table(S("vf_facilities"))
pins = spark.table(S("vf_india_post_pincode_directory"))

# COMMAND ----------

# MAGIC %md ## PIN reference: median point and majority district/state per PIN (the directory's own coordinates are noisy)

# COMMAND ----------

pin_pts = pins.where(in_india(F.col("latitude"), F.col("longitude")))
pin_geo = pin_pts.groupBy("pincode").agg(
    F.percentile_approx("latitude", 0.5).alias("pin_lat"),
    F.percentile_approx("longitude", 0.5).alias("pin_lon"),
    F.count("*").alias("pin_n_offices"),
)
pin_admin = (
    pins.where(F.length("statename") > 0)
    .groupBy("pincode", "district", "statename")
    .count()
    .groupBy("pincode")
    .agg(F.max_by(F.struct("district", "statename"), "count").alias("a"))
    .select("pincode", F.initcap("a.district").alias("pin_district"), F.col("a.statename").alias("pin_state_raw"))
)
pin_ref = pin_admin.join(pin_geo, "pincode", "left").withColumnRenamed("pincode", "pin")

# Canonical state names come from the directory (36 states / UTs)
states = (
    pins.where(F.length("statename") > 0)
    .select(k(F.col("statename")).alias("state_key"), F.initcap("statename").alias("state_name"))
    .dropDuplicates(["state_key"])
)
aliases = spark.createDataFrame(list(care.STATE_ALIASES.items()), "alias_key string, state_key string")
district_state = (
    pins.where(F.length("statename") > 0)
    .select(k(F.col("district")).alias("district_key"), k(F.col("statename")).alias("state_key"))
    .distinct()
    .groupBy("district_key")
    .agg(F.count("*").alias("n"), F.first("state_key").alias("state_key"))
    .where("n = 1")  # only districts whose name is unique to one state
    .drop("n")
)
print(f"{pin_ref.count():,} PINs · {states.count()} states/UTs · {district_state.count():,} unambiguous district names")

# COMMAND ----------

# MAGIC %md ## Facility rows

# COMMAND ----------

UUID = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
KNOWN_TYPES = ["hospital", "clinic", "dentist", "doctor", "pharmacy", "farmacy"]

f = raw.select(
    F.col("unique_id").alias("facility_id"),
    s("name").alias("name"),
    F.lower(s("facility_type_id")).alias("_type_raw"),
    F.lower(s("operator_type_id")).alias("operator_type"),
    s("address_line1").alias("address_line1"),
    s("address_line2").alias("address_line2"),
    s("address_line3").alias("address_line3"),
    s("address_city").alias("city"),
    s("address_state_or_region").alias("state_text"),
    F.col("address_zip_or_postcode").alias("pin"),
    F.coalesce(s("official_phone"), first(arr("phone_numbers"))).alias("phone"),
    F.coalesce(s("official_website"), first(arr("websites"))).alias("website"),
    s("email").alias("email"),
    "year_established",
    "number_doctors",
    "capacity",
    s("description").alias("description"),
    arr("specialties").alias("specialties"),
    arr("capability").alias("capability"),
    arr("procedure").alias("procedure"),
    arr("equipment").alias("equipment"),
    arr("source_urls").alias("source_urls"),
    F.col("latitude").alias("lat_listed"),
    F.col("longitude").alias("lon_listed"),
    s("cluster_id").alias("cluster_id"),
    F.col("recency_of_page_update").alias("page_updated"),
)
f = (
    f.withColumn("is_malformed", ~F.col("facility_id").rlike(UUID) | (F.col("_type_raw").isNotNull() & ~F.col("_type_raw").isin(KNOWN_TYPES)))
    .withColumn(
        "facility_type",
        F.when(F.col("_type_raw").isin("farmacy", "pharmacy"), "pharmacy").when(F.col("_type_raw").isin(KNOWN_TYPES), F.col("_type_raw")),
    )
    .drop("_type_raw")
    .withColumn("n_sources", F.size("source_urls"))
)

# COMMAND ----------

# MAGIC %md ## Location: validate coordinates, compare with the PIN, fall back to the PIN centroid

# COMMAND ----------

f = f.join(F.broadcast(pin_ref), "pin", "left")
coords_valid = F.col("lat_listed").isNotNull() & in_india(F.col("lat_listed"), F.col("lon_listed"))
f = (
    f.withColumn("coords_valid", coords_valid)
    .withColumn("coords_outside_india", F.col("lat_listed").isNotNull() & ~coords_valid)
    .withColumn("pin_found", F.col("pin_state_raw").isNotNull())
    .withColumn(
        "pin_distance_km",
        F.when(coords_valid & F.col("pin_lat").isNotNull(), F.round(haversine_km(F.col("lat_listed"), F.col("lon_listed"), F.col("pin_lat"), F.col("pin_lon")), 1)),
    )
)

# Tie-break when coordinates and PIN disagree (> PIN_COORD_CONFLICT_KM): the listed city is a third
# witness. City reference point = median of facilities in that city whose coordinates AND PIN agree.
# Use whichever of (coordinates, PIN area) is closer to it; with no city reference, prefer the PIN
# (typed by a person) over coordinates (geocoded from web text). Inspection: in most conflicts the
# PIN and the city agree and the coordinates are hundreds of km off.
f = f.withColumn("_city_key", k(F.col("city")))
city_ref = (
    f.where((F.col("pin_distance_km") <= 10) & (F.col("_city_key") != ""))
    .groupBy("_city_key", "pin_state_raw")
    .agg(F.percentile_approx("lat_listed", 0.5).alias("_city_lat"), F.percentile_approx("lon_listed", 0.5).alias("_city_lon"), F.count("*").alias("_city_n"))
    .where("_city_n >= 2")
)
f = f.join(F.broadcast(city_ref), ["_city_key", "pin_state_raw"], "left")
conflict = F.col("pin_distance_km") > care.PIN_COORD_CONFLICT_KM
d_coords_city = haversine_km(F.col("lat_listed"), F.col("lon_listed"), F.col("_city_lat"), F.col("_city_lon"))
d_pin_city = haversine_km(F.col("pin_lat"), F.col("pin_lon"), F.col("_city_lat"), F.col("_city_lon"))
use_pin = conflict & (F.col("_city_lat").isNull() | (d_pin_city < d_coords_city))
f = (
    f.withColumn("location_conflict_resolved_by", F.when(conflict, F.when(F.col("_city_lat").isNull(), "no city reference: PIN preferred").when(use_pin, "city agrees with PIN").otherwise("city agrees with coordinates")))
    .withColumn("lat", F.when(coords_valid & ~use_pin, F.col("lat_listed")).otherwise(F.col("pin_lat")))
    .withColumn("lon", F.when(coords_valid & ~use_pin, F.col("lon_listed")).otherwise(F.col("pin_lon")))
    .withColumn(
        "location_source",
        F.when(coords_valid & ~use_pin, "listed coordinates")
        .when(use_pin & F.col("pin_lat").isNotNull(), "PIN code area (listed coordinates disagree)")
        .when(F.col("pin_lat").isNotNull(), "PIN code area (approximate)"),
    )
    .drop("_city_key", "_city_lat", "_city_lon", "_city_n")
)

# COMMAND ----------

# MAGIC %md ## State: text (with aliases) → text as a district → PIN's state

# COMMAND ----------

f = f.withColumn("_sk", k(F.col("state_text")))
f = (
    f.join(F.broadcast(aliases), f["_sk"] == aliases["alias_key"], "left")
    .withColumn("_sk", F.coalesce(F.col("state_key"), F.col("_sk")))
    .drop("alias_key", "state_key")
)
st = states.withColumnRenamed("state_key", "_sk").withColumnRenamed("state_name", "_state_from_text")
f = f.join(F.broadcast(st), "_sk", "left")
ds = district_state.join(states, "state_key").select(F.col("district_key").alias("_sk"), F.col("state_name").alias("_state_from_district"))
f = f.join(F.broadcast(ds), "_sk", "left")
f = (
    f.withColumn("pin_state", F.initcap("pin_state_raw"))
    .withColumn("state", F.coalesce("_state_from_text", "_state_from_district", "pin_state"))
    .withColumn(
        "state_source",
        F.when(F.col("_state_from_text").isNotNull(), "address").when(F.col("_state_from_district").isNotNull(), "address (city/district name)").when(F.col("pin_state").isNotNull(), "PIN code"),
    )
    .withColumn(
        "state_conflict",
        F.coalesce(F.col("_state_from_text"), F.col("_state_from_district")).isNotNull()
        & F.col("pin_state").isNotNull()
        & (k(F.coalesce(F.col("_state_from_text"), F.col("_state_from_district"))) != k(F.col("pin_state"))),
    )
    .withColumn("district", F.col("pin_district"))
    .drop("_sk", "_state_from_text", "_state_from_district", "pin_state_raw")
)

# COMMAND ----------

# MAGIC %md ## Possible duplicates

# COMMAND ----------

f = f.withColumn("_name_key", k(F.col("name")))
by_cluster = f.where("cluster_id IS NOT NULL").groupBy("cluster_id").agg(F.count("*").alias("_n_cluster"))
by_name_pin = f.where("_name_key <> '' AND pin IS NOT NULL").groupBy("_name_key", "pin").agg(F.count("*").alias("_n_name_pin"))
f = (
    f.join(by_cluster, "cluster_id", "left")
    .join(by_name_pin, ["_name_key", "pin"], "left")
    .withColumn(
        "dup_reason",
        F.when(F.col("_n_cluster") > 1, F.format_string("shares cluster_id with %d other record(s)", F.col("_n_cluster") - 1)).when(
            F.col("_n_name_pin") > 1, F.format_string("same name and PIN as %d other record(s)", F.col("_n_name_pin") - 1)
        ),
    )
    .drop("_name_key", "_n_cluster", "_n_name_pin")
)

addr = F.concat_ws(", ", "address_line1", "address_line2", "address_line3", "city", "state", "pin")
master = f.withColumn("address", F.when(F.length(addr) > 0, addr)).select(
    "facility_id", "name", "facility_type", "operator_type", "address", "city", "district", "state", "state_source",
    "state_text", "pin", "phone", "website", "email",
    "lat", "lon", "location_source", "location_conflict_resolved_by", "lat_listed", "lon_listed", "pin_lat", "pin_lon", "pin_distance_km",
    "coords_valid", "coords_outside_india", "pin_found", "pin_state", "state_conflict",
    "year_established", "number_doctors", "capacity", "description",
    "specialties", "capability", "procedure", "equipment", "source_urls", "n_sources",
    "cluster_id", "dup_reason", "is_malformed", "page_updated",
)
assert master.count() == raw.count(), "row count changed"
write_table(master, S("facility_master"))
spark.sql(
    f"COMMENT ON TABLE {S('facility_master')} IS 'One row per Virtue Foundation facility record: canonical state, "
    "validated location (falls back to PIN area), parsed claim lists, and data-quality flags. Nothing removed.'"
)

# COMMAND ----------

display(spark.sql(f"""
  SELECT count(*) AS facilities,
         count_if(location_source = 'listed coordinates') AS located_by_coordinates,
         count_if(location_source LIKE 'PIN%') AS located_by_pin,
         count_if(lat IS NULL) AS no_location,
         count_if(pin_distance_km > {care.PIN_COORD_CONFLICT_KM}) AS pin_coord_conflicts,
         count_if(location_conflict_resolved_by = 'city agrees with PIN') AS conflicts_city_agrees_pin,
         count_if(location_conflict_resolved_by = 'city agrees with coordinates') AS conflicts_city_agrees_coords,
         count_if(state_conflict) AS state_conflicts,
         count_if(state IS NULL) AS no_state,
         count(DISTINCT state) AS distinct_states,
         count_if(dup_reason IS NOT NULL) AS possible_duplicates,
         count_if(is_malformed) AS malformed
  FROM {S('facility_master')}
"""))
