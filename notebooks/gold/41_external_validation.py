# Databricks notebook source
# MAGIC %md
# MAGIC # 03 - External validation: National Hospital Directory + LaQshya
# MAGIC
# MAGIC Cross-checks the provided facilities against independent government lists. It **adds verification
# MAGIC labels**; it never adds facilities.
# MAGIC
# MAGIC | Level | Meaning |
# MAGIC |---|---|
# MAGIC | **Verified** | On the LaQshya list (government-certified labour room / maternity OT) |
# MAGIC | **Corroborated** | Matched in the National Hospital Directory, which also lists the service |
# MAGIC | **Contradicted** | Directory says the facility has no emergency services, but we claim an emergency service |
# MAGIC | **Listed** | Matched in the directory, service not listed there (absence is NOT evidence of no service) |
# MAGIC
# MAGIC ### Before running
# MAGIC 1. Download the National Hospital Directory CSV (AIKosh / data.gov.in, "with Geo Code and additional parameters").
# MAGIC 2. Optional: LaQshya master list (NHSRC PDF) converted to CSV with columns: `state, district, facility, unit` (unit = Labour Room / Maternity OT).
# MAGIC 3. Catalog > workspace > hc_bronze > Create volume `external` > upload the files. Set the paths below.
# MAGIC
# MAGIC Writes: `hc_bronze.ext_national_hospital_directory`, `hc_bronze.ext_laqshya`, `hc_gold.facility_external_matches`,
# MAGIC `hc_gold.facility_external_validation` (read by `find_care()`), `hc_gold.external_validation_report`.

# COMMAND ----------

from pyspark.sql import functions as F, Window

NHD_PATH = "/Volumes/workspace/hc_bronze/external/national_hospital_directory.csv"
LAQSHYA_PATH = "/Volumes/workspace/hc_bronze/external/laqshya.csv"     # optional
GOLD, BRONZE = "workspace.hc_gold", "workspace.hc_bronze"
FAC = "workspace.hc_silver.vf_facilities"

STOP = ["HOSPITAL", "HOSPITALS", "CLINIC", "PVT", "PRIVATE", "LTD", "LIMITED", "THE", "AND", "CENTRE", "CENTER",
        "NURSING", "HOME", "MEDICAL", "MULTISPECIALITY", "MULTISPECIALTY", "SUPER", "SPECIALITY", "SPECIALTY", "CARE",
        "HEALTH", "INSTITUTE", "RESEARCH", "SRI", "SHRI", "SMT", "DR", "OF", "GOVT", "GOVERNMENT", "DISTRICT", "DH",
        "CHC", "PHC", "SDH", "MAIN", "UNIT", "TRUST"]

def save(df, name):
    df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(name)
    print(f"wrote {name}: {spark.table(name).count():,} rows")

def exists(path):
    try:
        dbutils.fs.ls(path)
        return True
    except Exception:
        return False

def tokens(col):
    """Name -> distinctive tokens (generic words removed; falls back to all tokens if nothing is left)."""
    allt = F.array_distinct(F.filter(F.split(F.regexp_replace(F.upper(col), "[^A-Z0-9 ]", " "), " +"), lambda x: F.length(x) > 1))
    core = F.array_except(allt, F.array(*[F.lit(s) for s in STOP]))
    return F.when(F.size(core) > 0, core).otherwise(allt)

def jaccard(a, b):
    return F.size(F.array_intersect(a, b)) / F.greatest(F.size(F.array_union(a, b)), F.lit(1))

def key(c):
    return F.regexp_replace(F.upper(F.trim(c)), "[^A-Z0-9]", "")

def haversine_km(lat1, lon1, lat2, lon2):
    a = (F.pow(F.sin(F.radians(lat2 - lat1) / 2), 2)
         + F.cos(F.radians(lat1)) * F.cos(F.radians(lat2)) * F.pow(F.sin(F.radians(lon2 - lon1) / 2), 2))
    return 2 * 6371 * F.asin(F.sqrt(a))

def pick(columns, *cands):
    low = {c.lower(): c for c in columns}
    for cand in cands:
        for lc, c in low.items():
            if cand in lc:
                return c
    return None

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load and standardise the National Hospital Directory

# COMMAND ----------

assert exists(NHD_PATH), f"Upload the National Hospital Directory CSV to {NHD_PATH} first"
raw = spark.read.option("header", True).option("multiLine", True).option("escape", '"').csv(NHD_PATH)
save(raw, f"{BRONZE}.ext_national_hospital_directory")
c = raw.columns
m = dict(name=pick(c, "hospital_name", "name"), pin=pick(c, "pincode", "pin_code", "pin"),
         state=pick(c, "state_name", "state"), district=pick(c, "district_name", "district"),
         lat=pick(c, "latitude", "lat"), lon=pick(c, "longitude", "long", "lon"),
         spec=pick(c, "specialt", "speciali", "discipline"), facilities=pick(c, "facilit"),
         emergency=pick(c, "emergency"), category=pick(c, "category"), care_type=pick(c, "care_type", "type"))
print("detected columns:", m)
assert m["name"], "could not find a hospital name column"

col = lambda k, cast=None: (F.col(m[k]).cast(cast) if cast else F.col(m[k])) if m[k] else F.lit(None).cast(cast or "string")
nhd = (raw.select(
          F.monotonically_increasing_id().alias("nhd_id"),
          F.trim(col("name")).alias("nhd_name"),
          F.regexp_extract(col("pin").cast("string"), r"(\d{6})", 1).alias("pin6"),
          key(col("district")).alias("district_key"), key(col("state")).alias("state_key"),
          col("lat", "double").alias("lat"), col("lon", "double").alias("lon"),
          F.lower(F.concat_ws(" ; ", col("spec"), col("facilities"), col("category"), col("care_type"))).alias("nhd_text"),
          F.lower(F.trim(col("emergency"))).alias("nhd_emergency"))
       .where("nhd_name IS NOT NULL AND nhd_name <> ''")
       .withColumn("lat", F.when(F.col("lat").between(6, 37.5), F.col("lat")))
       .withColumn("lon", F.when(F.col("lon").between(68, 97.5), F.col("lon")))
       .withColumn("tok", tokens(F.col("nhd_name"))))

fac = (spark.table(FAC).select(
          F.col("unique_id").alias("facility_id"), F.col("name"),
          F.regexp_extract(F.col("address_zip_or_postcode").cast("string"), r"(\d{6})", 1).alias("pin6"),
          key(F.col("address_city")).alias("city_key"), "latitude", "longitude")
       .withColumn("tok", tokens(F.col("name"))))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Match: same PIN + similar name, or within 2 km + similar name
# MAGIC Name similarity = Jaccard overlap of distinctive name tokens (generic words like "hospital" removed).

# COMMAND ----------

f, n = fac.alias("f"), nhd.alias("n")
by_pin = (f.join(n, (F.col("f.pin6") == F.col("n.pin6")) & (F.col("f.pin6") != ""))
           .select("f.facility_id", "f.name", "n.nhd_id", "n.nhd_name", "n.nhd_text", "n.nhd_emergency",
                   jaccard(F.col("f.tok"), F.col("n.tok")).alias("sim"), F.lit("same PIN").alias("match_method"),
                   F.lit(None).cast("double").alias("km")))
by_geo = (f.join(n, (F.abs(F.col("f.latitude") - F.col("n.lat")) < 0.02) & (F.abs(F.col("f.longitude") - F.col("n.lon")) < 0.02))
           .withColumn("km", haversine_km(F.col("f.latitude"), F.col("f.longitude"), F.col("n.lat"), F.col("n.lon")))
           .where("km <= 2")
           .select("f.facility_id", "f.name", "n.nhd_id", "n.nhd_name", "n.nhd_text", "n.nhd_emergency",
                   jaccard(F.col("f.tok"), F.col("n.tok")).alias("sim"), F.lit("within 2 km").alias("match_method"), "km"))
cands = by_pin.unionByName(by_geo).where(
    ((F.col("match_method") == "same PIN") & (F.col("sim") >= 0.5)) |
    ((F.col("match_method") == "within 2 km") & (F.col("sim") >= 0.34)))
w = Window.partitionBy("facility_id").orderBy(F.desc("sim"), F.col("km").asc_nulls_last())
matches = cands.withColumn("_r", F.row_number().over(w)).where("_r = 1").drop("_r")
save(matches, f"{GOLD}.facility_external_matches")
matches = spark.table(f"{GOLD}.facility_external_matches")
display(matches.orderBy(F.rand(3)).select("name", "nhd_name", "match_method", F.round("sim", 2).alias("sim"), F.round("km", 2).alias("km")).limit(25))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Directory evidence per service
# MAGIC Uses Mekeli's `service_catalog` patterns and synonyms, plus the specialty words that imply the service.

# COMMAND ----------

SPECIALTY_WORDS = {   # directory specialty wording that supports each service
    "emergency_c_section": r"obstetric|gynaec|gynec|maternity|o\s*&\s*g|obg",
    "maternity_delivery": r"obstetric|gynaec|gynec|maternity|o\s*&\s*g|obg|labour",
    "nicu": r"nicu|neonat|newborn|sncu",
    "icu": r"\bicu\b|intensive|critical care",
    "dialysis": r"dialysis|nephrolog",
    "cardiac_cath": r"cath|cardiolog|angioplast",
    "cardiac_surgery": r"cardio.?thoracic|ctvs|cardiac surg",
    "trauma_care": r"trauma|casualty|orthop",
    "emergency_department": r"emergency|casualty|trauma",
    "blood_bank": r"blood bank|blood storage",
    "burn_care": r"burn",
    "chemotherapy": r"oncolog|cancer|chemo",
    "radiotherapy": r"radiotherap|radiation oncolog|linac",
    "ct_scan": r"\bct\b|ct scan|computed tomograph",
    "mri": r"\bmri\b|magnetic resonance",
    "cataract_surgery": r"ophthalm|eye|cataract",
}
spec_map = F.create_map(*[F.lit(x) for kv in SPECIALTY_WORDS.items() for x in kv])
EMERGENCY_SERVICES = ["emergency_department", "trauma_care", "emergency_c_section"]

svc = spark.table(f"{GOLD}.service_catalog").select("service_key", "pattern")
claimed = spark.table(f"{GOLD}.care_finder_index").select("facility_id", "service_key").distinct()

nhd_val = (claimed.join(matches, "facility_id").join(svc, "service_key")
    .withColumn("spec_pattern", spec_map[F.col("service_key")])
    .withColumn("lists_service", F.coalesce(F.expr("nhd_text RLIKE pattern"), F.lit(False))
                                 | F.coalesce(F.expr("nhd_text RLIKE spec_pattern"), F.lit(False)))
    .withColumn("says_no_emergency", F.col("nhd_emergency").isin("no", "n", "false", "0", "not available"))
    .withColumn("verification_level",
        F.when(F.col("service_key").isin(EMERGENCY_SERVICES) & F.col("says_no_emergency"), "Contradicted")
         .when(F.col("lists_service"), "Corroborated")
         .otherwise("Listed"))
    .select("facility_id", "service_key", "verification_level",
            F.lit("National Hospital Directory").alias("external_source"),
            F.col("nhd_name").alias("external_name"), "match_method", F.round("sim", 3).alias("match_score")))

# COMMAND ----------

# MAGIC %md
# MAGIC ## LaQshya (optional): certified labour rooms and maternity OTs
# MAGIC Matched within the same district by name similarity (LaQshya names look like "DH Tirupati", "Govt Maternity Hospital").
# MAGIC Maternity OT certified -> emergency C-section **Verified**; labour room certified -> maternity delivery **Verified**.

# COMMAND ----------

lq_val = None
if exists(LAQSHYA_PATH):
    lq_raw = spark.read.option("header", True).csv(LAQSHYA_PATH)
    save(lq_raw, f"{BRONZE}.ext_laqshya")
    lc = lq_raw.columns
    lm = dict(state=pick(lc, "state"), district=pick(lc, "district"), name=pick(lc, "facility", "name", "hospital"),
              unit=pick(lc, "unit", "type", "area"))
    print("LaQshya columns:", lm)
    lq = (lq_raw.select(key(F.col(lm["district"])).alias("district_key"), F.trim(F.col(lm["name"])).alias("lq_name"),
                        F.lower(F.coalesce(F.col(lm["unit"]), F.lit(""))).alias("unit"))
               .withColumn("tok", tokens(F.col("lq_name"))))
    # facility district from Mekeli's index (already resolved), fallback city
    fd = (spark.table(f"{GOLD}.care_finder_index").select("facility_id", "name", key(F.col("district")).alias("district_key"))
          .dropDuplicates(["facility_id"]).withColumn("tok", tokens(F.col("name"))))
    lqm = (fd.alias("a").join(lq.alias("b"), "district_key")
             .withColumn("sim", jaccard(F.col("a.tok"), F.col("b.tok")))
             .where("sim >= 0.5")
             .withColumn("service_key", F.when(F.col("unit").contains("ot") | F.col("unit").contains("theat"), "emergency_c_section")
                                          .otherwise("maternity_delivery")))
    wl = Window.partitionBy("facility_id", "service_key").orderBy(F.desc("sim"))
    lq_val = (lqm.withColumn("_r", F.row_number().over(wl)).where("_r = 1")
                 .select("facility_id", "service_key", F.lit("Verified").alias("verification_level"),
                         F.lit("LaQshya certification").alias("external_source"), F.col("lq_name").alias("external_name"),
                         F.lit("same district + name").alias("match_method"), F.round("sim", 3).alias("match_score")))
    # a maternity-OT certificate also implies the labour room
    lq_val = lq_val.unionByName(lq_val.where("service_key = 'emergency_c_section'").withColumn("service_key", F.lit("maternity_delivery")))
else:
    print(f"No LaQshya file at {LAQSHYA_PATH}: skipping (directory validation still runs)")

val = nhd_val if lq_val is None else nhd_val.unionByName(lq_val)
save(val, f"{GOLD}.facility_external_validation")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Report (for the slides)

# COMMAND ----------

n_fac = spark.table(FAC).count()
n_nhd = nhd.count()
n_match = spark.table(f"{GOLD}.facility_external_matches").count()
rep = [("facilities in provided data", n_fac), ("hospitals in National Hospital Directory", n_nhd),
       ("provided facilities matched in directory", n_match),
       ("match rate %", round(100 * n_match / n_fac, 1))]
report = spark.createDataFrame([(k, str(v)) for k, v in rep], "metric string, value string")
save(report, f"{GOLD}.external_validation_report")
display(report)
display(spark.table(f"{GOLD}.facility_external_validation").groupBy("external_source", "service_key", "verification_level")
        .count().orderBy("service_key", "verification_level"))
