# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "6"
# ///
# MAGIC %md
# MAGIC # 04 - District gap analysis for planners
# MAGIC
# MAGIC For every district and service: **how far is the nearest facility with confident evidence**, and **how much
# MAGIC need is there** (NFHS-5)? High need + far from confident care = a planning priority.
# MAGIC
# MAGIC | Output | What it is |
# MAGIC |---|---|
# MAGIC | `hc_gold.district_service_access` | district x service: nearest confident facility (km, name), count within 25 / 50 km |
# MAGIC | `hc_gold.district_need` | district: need index per service family from NFHS-5 (0 = lowest need, 1 = highest) |
# MAGIC | `hc_gold.district_service_gaps` | district x service: access gap, need, **gap score**, priority tier, plain-language reason |
# MAGIC
# MAGIC **Confident** = AI-adjusted confidence High or Medium and not excluded (from `care_finder_index_v2`;
# MAGIC falls back to the rules confidence if 02 has not run). District centres come from `location_lookup`.
# MAGIC Distances are straight-line, so real travel is longer in hilly and rural areas.

# COMMAND ----------

from pyspark.sql import functions as F, Window
import re

GOLD = "workspace.hc_gold"
NFHS = "workspace.hc_silver.vf_nfhs_5_district_health_indicators"
SEARCH_DEG = 3.0          # only compare facilities within ~330 km of a district centre
NEAR_KM = (25, 50)
ACCESS_CAP_KM = 150       # nearest beyond this counts as no access (gap = 1)

def save(df, name):
    df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(name)
    print(f"wrote {name}: {spark.table(name).count():,} rows")

def key(c):
    return F.regexp_replace(F.upper(F.trim(c)), "[^A-Z0-9]", "")

def haversine_km(lat1, lon1, lat2, lon2):
    a = (F.pow(F.sin(F.radians(lat2 - lat1) / 2), 2)
         + F.cos(F.radians(lat1)) * F.cos(F.radians(lat2)) * F.pow(F.sin(F.radians(lon2 - lon1) / 2), 2))
    return 2 * 6371 * F.asin(F.sqrt(a))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Confident supply per service

# COMMAND ----------

if spark.catalog.tableExists(f"{GOLD}.care_finder_index_final"):
    idx = spark.table(f"{GOLD}.care_finder_index_final").where("NOT coalesce(excluded, false)")
    conf_col = "adjusted_confidence"
    print("using care_finder_index_final (AI review + trained model)")
elif spark.catalog.tableExists(f"{GOLD}.care_finder_index_v2"):
    idx = spark.table(f"{GOLD}.care_finder_index_v2").where("NOT coalesce(excluded, false)")
    conf_col = "adjusted_confidence"
else:
    print("care_finder_index_v2 not found: using rules confidence from care_finder_index")
    idx = spark.table(f"{GOLD}.care_finder_index")
    conf_col = "confidence"

supply = (idx.where(F.col(conf_col).isin("High", "Medium") & F.col("lat").isNotNull())
             .select("service_key", "facility_id", "name", "lat", "lon", F.col(conf_col).alias("conf"))
             .dropDuplicates(["service_key", "facility_id"]))
display(supply.groupBy("service_key").count().orderBy("service_key"))

districts = (spark.table(f"{GOLD}.location_lookup").where("kind = 'district' AND lat IS NOT NULL")
             .select(F.col("display_name").alias("district"), "state", "name_key", "state_key",
                     F.col("lat").alias("d_lat"), F.col("lon").alias("d_lon")))
services = spark.table(f"{GOLD}.service_catalog").select("service_key", "label")
print("districts:", districts.count())

# COMMAND ----------

# MAGIC %md
# MAGIC ## Nearest confident facility from each district centre

# COMMAND ----------

base = districts.crossJoin(services.select(F.col("service_key").alias("svc")))
bbox = (F.abs(F.col("s.lat") - F.col("d_lat")) < SEARCH_DEG) & (F.abs(F.col("s.lon") - F.col("d_lon")) < SEARCH_DEG)
pairs = (base.join(supply.alias("s"), (F.col("s.service_key") == F.col("svc")) & bbox, "left")
             .withColumn("km", haversine_km(F.col("d_lat"), F.col("d_lon"), F.col("s.lat"), F.col("s.lon"))))

access = (pairs.groupBy("district", "state", "name_key", "state_key", "d_lat", "d_lon", F.col("svc").alias("service_key"))
          .agg(F.min("km").alias("nearest_km"),
               F.min_by(F.col("s.name"), F.col("km")).alias("nearest_facility"),
               F.sum(F.when(F.col("km") <= NEAR_KM[0], 1).otherwise(0)).alias(f"n_within_{NEAR_KM[0]}km"),
               F.sum(F.when(F.col("km") <= NEAR_KM[1], 1).otherwise(0)).alias(f"n_within_{NEAR_KM[1]}km"))
          .withColumn("nearest_km", F.round("nearest_km", 1)))
save(access, f"{GOLD}.district_service_access")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Need from NFHS-5
# MAGIC Columns are found by name, so the notebook adapts to the exact NFHS-5 column names. Each indicator is
# MAGIC turned into a percentile across districts, oriented so **higher = more need**, then averaged per family.

# COMMAND ----------

nfhs = spark.table(NFHS)
cols = nfhs.columns

# (regex on column name, direction): +1 = higher value means more need, -1 = lower value means more need
NEED_FAMILIES = {
    "maternal": [(r"institutional_birth", -1), (r"(caesarean|c_section|csection)", -1),
                 (r"at_least_4_anc", -1), (r"anc_visit_in_the_first_trimester", -1),
                 (r"(skilled|health_personnel)", -1), (r"out_of_pocket.*deliver", +1),
                 (r"pregnant_women.*anaemic|anaemic.*pregnant", +1)],
    "newborn": [(r"institutional_birth", -1), (r"born_at_home_who_were_taken", -1),
                (r"(low_birth|birth_weight)", +1), (r"(stunted|wasted)", +1)],
    "ncd": [(r"(high|very_high).*blood_sugar|blood_sugar.*(high|very_high)", +1),
            (r"(elevated|high).*blood_pressure|hypertens", +1)],
    "access": [(r"covered_health_insurance", -1), (r"women_age_15_49_who_are_literate", -1)],
}
SERVICE_FAMILY = {
    "emergency_c_section": ["maternal", "access"], "maternity_delivery": ["maternal", "access"],
    "nicu": ["newborn", "access"], "blood_bank": ["maternal", "access"],
    "dialysis": ["ncd", "access"], "cardiac_cath": ["ncd", "access"], "cardiac_surgery": ["ncd", "access"],
}  # every other service uses ["access"]

numeric = {c: t for c, t in nfhs.dtypes}
chosen = {}
for fam, pats in NEED_FAMILIES.items():
    chosen[fam] = []
    for pat, direction in pats:
        for c in cols:
            if re.search(pat, c) and not c.endswith("_is_suppressed") and c not in [x for x, _ in chosen[fam]]:
                chosen[fam].append((c, direction))
    print(f"{fam}: {[c for c, _ in chosen[fam]]}")

need_cols = sorted({c for fam in chosen for c, _ in chosen[fam]})
d = nfhs.select(F.col("district_name"), F.col("state_ut"), *[F.col(c).cast("double").alias(c) for c in need_cols])
d = d.dropDuplicates(["district_name", "state_ut"])
for fam, items in chosen.items():
    pct_cols = []
    for c, direction in items:
        pc = f"_p_{fam}_{c}"[:120]
        d = d.withColumn(pc, F.percent_rank().over(Window.orderBy(F.col(c).asc_nulls_last() if direction > 0 else F.col(c).desc_nulls_last())))
        d = d.withColumn(pc, F.when(F.col(c).isNull(), None).otherwise(F.col(pc)))
        pct_cols.append(pc)
    if pct_cols:
        n = sum(F.when(F.col(p).isNotNull(), 1).otherwise(0) for p in pct_cols)
        s = sum(F.coalesce(F.col(p), F.lit(0.0)) for p in pct_cols)
        d = d.withColumn(f"need_{fam}", F.round(F.when(n > 0, s / n), 3))
    else:
        d = d.withColumn(f"need_{fam}", F.lit(None).cast("double"))

STATE_ALIASES = {"ANDAMANNICOBARISLANDS": "ANDAMANANDNICOBARISLANDS", "JAMMUKASHMIR": "JAMMUANDKASHMIR",
                 "DADRANAGARHAVELIDAMANDIU": "DADRAANDNAGARHAVELIANDDAMANANDDIU", "NCTOFDELHI": "DELHI",
                 "ORISSA": "ODISHA", "PONDICHERRY": "PUDUCHERRY", "UTTARANCHAL": "UTTARAKHAND"}
alias = F.create_map(*[F.lit(x) for kv in STATE_ALIASES.items() for x in kv])
sk = key(F.regexp_replace(F.col("state_ut"), "&", "and"))
need = (d.withColumn("name_key", key(F.col("district_name")))
         .withColumn("state_key", F.coalesce(alias[sk], sk))
         .select("district_name", "state_ut", "name_key", "state_key", *[f"need_{f}" for f in NEED_FAMILIES]))
save(need, f"{GOLD}.district_need")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Gap score and priorities
# MAGIC `access_gap = min(nearest_km, 150) / 150` (1 = nothing confident within 150 km)
# MAGIC `need = mean of the service's need families` (falls back to access-only if NFHS-5 has no match)
# MAGIC **`gap_score = 0.6 x access_gap + 0.4 x need`**. Access weighs more because the dataset is about facilities;
# MAGIC need tells planners where a gap hurts most.

# COMMAND ----------

acc = spark.table(f"{GOLD}.district_service_access")
need = spark.table(f"{GOLD}.district_need")

joined = acc.join(need, ["name_key", "state_key"], "left")
# second chance: district name only, when the state key differs in spelling and the name is unique
need_by_name = (need.groupBy("name_key").agg(F.count("*").alias("_n"), *[F.first(f"need_{f}").alias(f"_n_{f}") for f in NEED_FAMILIES])
                    .where("_n = 1").drop("_n"))
joined = joined.join(need_by_name, "name_key", "left")
for f in NEED_FAMILIES:
    joined = joined.withColumn(f"need_{f}", F.coalesce(F.col(f"need_{f}"), F.col(f"_n_{f}"))).drop(f"_n_{f}")

fam_map = F.create_map(*[x for k, v in SERVICE_FAMILY.items() for x in (F.lit(k), F.array(*[F.lit(f) for f in v]))])
fams = F.coalesce(fam_map[F.col("service_key")], F.array(F.lit("access")))
# average of the families that apply and have data
vals = F.filter(F.array(*[F.when(F.array_contains(fams, f), F.col(f"need_{f}")) for f in NEED_FAMILIES]), lambda x: x.isNotNull())
need_avg = F.when(F.size(vals) > 0, F.aggregate(vals, F.lit(0.0), lambda a, x: a + x) / F.size(vals))

gaps = (joined
    .withColumn("need", F.round(need_avg, 3))
    .withColumn("access_gap", F.round(F.least(F.coalesce(F.col("nearest_km"), F.lit(ACCESS_CAP_KM)), F.lit(ACCESS_CAP_KM)) / ACCESS_CAP_KM, 3))
    .withColumn("gap_score", F.round(F.when(F.col("need").isNull(), F.col("access_gap"))
                                      .otherwise(0.6 * F.col("access_gap") + 0.4 * F.col("need")), 3))
    .withColumn("priority",
        F.when((F.col("access_gap") >= 0.5) & (F.coalesce(F.col("need"), F.lit(0.5)) >= 0.6), "1 - urgent")
         .when(F.col("gap_score") >= 0.5, "2 - high")
         .when(F.col("gap_score") >= 0.3, "3 - watch")
         .otherwise("4 - covered"))
    .join(services, "service_key")
    .withColumn("reason", F.concat(
        F.when(F.col("nearest_km").isNull(), F.format_string("No facility with confident evidence for %s within ~300 km", F.col("label")))
         .otherwise(F.format_string("Nearest confident %s: %s, %.0f km", F.col("label"), F.col("nearest_facility"), F.col("nearest_km"))),
        F.when(F.col("need").isNotNull(), F.format_string("; need higher than %.0f%% of districts (NFHS-5)", F.col("need") * 100))
         .otherwise(F.lit("; no NFHS-5 need data for this district or service")))))
save(gaps, f"{GOLD}.district_service_gaps")

print("NFHS-5 match rate:", round(gaps.where("need IS NOT NULL").select("name_key", "state_key").distinct().count()
                                    / gaps.select("name_key", "state_key").distinct().count() * 100, 1), "%")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Results for the slides

# COMMAND ----------

display(spark.sql(f"""
SELECT label AS service, priority, count(*) AS districts
FROM {GOLD}.district_service_gaps
WHERE service_key IN ('emergency_c_section', 'nicu', 'dialysis', 'icu', 'blood_bank')
GROUP BY ALL ORDER BY service, priority"""))

# COMMAND ----------

display(spark.sql(f"""
SELECT district, state, label AS service, nearest_km, nearest_facility, need, gap_score, priority, reason
FROM {GOLD}.district_service_gaps
WHERE service_key = 'emergency_c_section'
ORDER BY gap_score DESC LIMIT 25"""))

# COMMAND ----------

# Map: district centres coloured by C-section gap score (save the image for the slide)
import matplotlib.pyplot as plt
pdf = spark.table(f"{GOLD}.district_service_gaps").where("service_key = 'emergency_c_section'").select("d_lat", "d_lon", "gap_score").toPandas()
fig, ax = plt.subplots(figsize=(7, 8))
sc = ax.scatter(pdf.d_lon, pdf.d_lat, c=pdf.gap_score, cmap="Reds", s=18, vmin=0, vmax=1)
fig.colorbar(sc, ax=ax, label="Gap score (0 = covered, 1 = far from confident care + high need)")
ax.set_title("Emergency C-section: where confident care is far and need is high")
ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude"); ax.set_aspect("equal")
display(fig)