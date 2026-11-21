# Databricks notebook source
# MAGIC %md
# MAGIC # Gold 20 · `county_context`: one row per US county, every public source joined
# MAGIC
# MAGIC This is the table that makes the Exploration score: whatever the organizers give us, if we can get it
# MAGIC to a county (FIPS, ZIP, or state + county name) we can join ~120 columns of social vulnerability,
# MAGIC chronic disease, workforce shortage, hospital supply, rurality, and overdose mortality.
# MAGIC
# MAGIC Also used directly by the dashboard and the Genie space (column comments set below).

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

from hc.io import write_table

S, G = cfg.silver, cfg.gold

od_annual = spark.table(S("overdose_county_annual"))
latest_year = od_annual.where("overdose_deaths IS NOT NULL").agg(F.max("year")).first()[0]
print("Latest complete overdose year:", latest_year)

od = od_annual.groupBy("fips").agg(
    F.max(F.when(F.col("year") == latest_year, F.col("overdose_deaths"))).alias("overdose_deaths_latest"),
    F.max(F.when(F.col("year") == latest_year, F.col("is_suppressed").cast("int"))).alias("_supp"),
    F.max(F.when(F.col("year") == latest_year - 1, F.col("overdose_deaths"))).alias("overdose_deaths_prior"),
    F.max("nchs_urban_rural_2013").alias("nchs_urban_rural_2013"),
).withColumn("overdose_suppressed_latest", F.col("_supp") == 1).drop("_supp")

hosp = spark.table(S("hospitals")).where("fips IS NOT NULL").groupBy("fips").agg(
    F.count("*").alias("n_hospitals"),
    F.sum(F.col("hospital_type").isin("Acute Care Hospitals").cast("int")).alias("n_acute_care_hospitals"),
    F.sum((F.col("hospital_type") == "Critical Access Hospitals").cast("int")).alias("n_critical_access_hospitals"),
    F.sum(F.col("has_emergency_services").cast("int")).alias("n_hospitals_with_er"),
    F.sum(F.col("is_birthing_friendly").cast("int")).alias("n_birthing_friendly_hospitals"),
    F.round(F.avg("overall_star_rating"), 2).alias("avg_hospital_star_rating"),
    F.sum("n_mort_worse").alias("n_mortality_measures_worse_than_national"),
)

ctx = (
    spark.table(S("svi_county"))
    .join(spark.table(S("rucc_county")).drop("population_2020"), "fips", "left")
    .join(spark.table(S("places_county_wide")), "fips", "left")
    .join(spark.table(S("hpsa_county")), "fips", "left")
    .join(hosp, "fips", "left")
    .join(od, "fips", "left")
)
per100k = lambda c: F.round(F.col(c) / F.col("population") * 100_000, 2)  # noqa: E731
ctx = (
    ctx.fillna(0, subset=["n_hospitals", "n_acute_care_hospitals", "n_critical_access_hospitals", "n_hospitals_with_er", "n_birthing_friendly_hospitals"])
    .fillna(False, subset=["hpsa_pc_has_geographic", "hpsa_pc_whole_county", "hpsa_mh_has_geographic", "hpsa_mh_whole_county"])
    .withColumn("overdose_deaths_per_100k", per100k("overdose_deaths_latest"))
    .withColumn("overdose_change_pct", F.round((F.col("overdose_deaths_latest") / F.col("overdose_deaths_prior") - 1) * 100, 1))
    .withColumn("hospitals_per_100k", per100k("n_hospitals"))
    .withColumn("er_hospitals_per_100k", per100k("n_hospitals_with_er"))
    .withColumn("has_no_hospital", F.col("n_hospitals") == 0)
    .withColumn("has_no_birthing_hospital", F.col("n_birthing_friendly_hospitals") == 0)
    .withColumn("overdose_year", F.lit(latest_year))
)

dupes = ctx.groupBy("fips").count().where("count > 1").count()
assert dupes == 0, f"{dupes} duplicate FIPS in county_context"
write_table(ctx, G("county_context"))
print(f"county_context: {spark.table(G('county_context')).count():,} counties x {len(ctx.columns)} columns")

# COMMAND ----------

# MAGIC %md ## Column comments (Genie and dashboards read these)

# COMMAND ----------

COMMENTS = {
    "fips": "5-digit county FIPS code (join key)",
    "population": "Total population, ACS 2018-2022 (SVI E_TOTPOP)",
    "svi_overall_pctile": "CDC Social Vulnerability Index overall national percentile, 0-1, higher = more vulnerable",
    "pct_uninsured": "Percent of people without health insurance",
    "pct_below_150pct_poverty": "Percent of people below 150% of the federal poverty line",
    "rucc_2023": "USDA Rural-Urban Continuum Code 2023: 1-3 metro, 4-9 nonmetro",
    "is_rural": "True when RUCC 2023 is 4-9 (nonmetro)",
    "hpsa_pc_max_score": "Highest HRSA primary-care shortage score in the county (0-25, higher = worse)",
    "hpsa_pc_whole_county": "Entire county is a geographic primary-care shortage area",
    "hpsa_mh_max_score": "Highest HRSA mental-health shortage score in the county (0-25, higher = worse)",
    "hpsa_mh_whole_county": "Entire county is a geographic mental-health shortage area",
    "n_hospitals": "Number of CMS-listed hospitals in the county",
    "has_no_hospital": "County has no CMS-listed hospital",
    "has_no_birthing_hospital": "No hospital in the county meets CMS birthing-friendly criteria",
    "avg_hospital_star_rating": "Mean CMS overall star rating (1-5) of rated hospitals in the county",
    "overdose_deaths_latest": "Provisional drug overdose deaths in overdose_year (NULL when suppressed, 1-9 deaths)",
    "overdose_suppressed_latest": "Overdose count suppressed by NCHS (1-9 deaths); not missing at random",
    "overdose_deaths_per_100k": "Crude overdose death rate per 100,000 population in overdose_year",
    "overdose_change_pct": "Percent change in overdose deaths vs the prior year",
}
for r in spark.table(S("places_measure_dictionary")).collect():
    COMMENTS[r.col_name] = f"CDC PLACES age-adjusted % of adults: {r.measure} ({r.latest_year})"

for col, text in COMMENTS.items():
    if col in ctx.columns:
        spark.sql(f"ALTER TABLE {G('county_context')} ALTER COLUMN `{col}` COMMENT '{text.replace(chr(39), '')}'")
spark.sql(
    f"COMMENT ON TABLE {G('county_context')} IS 'One row per US county joining CDC SVI, CDC PLACES, HRSA HPSA, CMS hospitals, "
    "USDA RUCC and CDC VSRR overdose deaths. Join any county-level data on fips.'"
)

# COMMAND ----------

# MAGIC %md ## Quick look

# COMMAND ----------

display(spark.sql(f"""
  SELECT state_abbr, county_name, population, round(svi_overall_pctile, 2) AS svi, is_rural, hpsa_pc_max_score,
         n_hospitals, overdose_deaths_latest, overdose_deaths_per_100k
  FROM {G('county_context')}
  WHERE overdose_deaths_per_100k IS NOT NULL
  ORDER BY overdose_deaths_per_100k DESC
  LIMIT 25
"""))
