# Databricks notebook source
# MAGIC %md
# MAGIC # Silver 12 · Clean the public sources (source-specific rules)
# MAGIC
# MAGIC Each public source has known quirks, so it gets explicit cleaning rules here instead of the
# MAGIC generic heuristics. Every output table has a stated grain and a 5-digit `fips` (or ZIP) key.
# MAGIC
# MAGIC | Silver table | Grain | Messy-data fixes |
# MAGIC |---|---|---|
# MAGIC | `county_lookup` | state key × county-name key | name normalization for FIPS-less sources |
# MAGIC | `svi_county` | county | `-999` → NULL, friendly names, numeric types |
# MAGIC | `places_county_long` / `places_county_wide` | county × measure / county | long→wide pivot, latest year per measure |
# MAGIC | `places_measure_dictionary` | measure | column ↔ question text |
# MAGIC | `overdose_county_monthly` / `overdose_county_annual` | county × month / county × year | FIPS padding, suppression flags |
# MAGIC | `hpsa_county` | county | active designations only, PC + MH combined |
# MAGIC | `hospitals` | hospital | FIPS via state+county name, fallback ZIP; 'Not Available' → NULL |
# MAGIC | `rucc_county` | county | long→wide pivot, rural flag |
# MAGIC | `zip_county_xwalk` | ZCTA × county | land-area share, primary county |

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

from hc.geo import attach_fips_by_name, attach_fips_by_zip, county_key, fips5, state_key, zip5
from hc.io import write_table
from pyspark.sql import Window

B, S = cfg.bronze, cfg.silver


def save(df, table, comment):
    write_table(df, S(table))
    spark.sql(f"COMMENT ON TABLE {S(table)} IS '{comment.replace(chr(39), chr(92) + chr(39))}'")
    n = spark.table(S(table)).count()
    print(f"{table:<28} {n:>10,} rows")
    return n


def num(c):
    """string -> double; SVI/CDC sentinel -999 -> NULL."""
    v = F.expr(f"try_cast(regexp_replace(`{c}`, '[,$% ]', '') AS DOUBLE)")
    return F.when(v > -999, v)

# COMMAND ----------

# MAGIC %md ## SVI (county spine)

# COMMAND ----------

SVI_FRIENDLY = {
    "e_totpop": "population", "area_sqmi": "area_sq_mi",
    "ep_pov150": "pct_below_150pct_poverty", "ep_unemp": "pct_unemployed", "ep_hburd": "pct_housing_cost_burdened",
    "ep_nohsdp": "pct_no_high_school_diploma", "ep_uninsur": "pct_uninsured", "ep_age65": "pct_age_65_plus",
    "ep_age17": "pct_age_17_under", "ep_disabl": "pct_with_disability", "ep_sngpnt": "pct_single_parent_households",
    "ep_limeng": "pct_limited_english", "ep_minrty": "pct_racial_ethnic_minority", "ep_munit": "pct_multi_unit_housing",
    "ep_mobile": "pct_mobile_homes", "ep_crowd": "pct_crowded_housing", "ep_noveh": "pct_no_vehicle",
    "ep_groupq": "pct_group_quarters", "ep_noint": "pct_no_internet", "ep_afam": "pct_black", "ep_hisp": "pct_hispanic",
    "ep_asian": "pct_asian", "ep_aian": "pct_american_indian_alaska_native", "ep_nhpi": "pct_native_hawaiian_pacific_islander",
    "ep_twomore": "pct_two_or_more_races",
    "rpl_theme1": "svi_socioeconomic_pctile", "rpl_theme2": "svi_household_disability_pctile",
    "rpl_theme3": "svi_minority_language_pctile", "rpl_theme4": "svi_housing_transport_pctile",
    "rpl_themes": "svi_overall_pctile",
}
svi_b = spark.table(B("svi_county_2022"))
sentinels = svi_b.select(*[F.sum(F.when(F.col(c) == "-999", 1).otherwise(0)).alias(c) for c in SVI_FRIENDLY]).collect()[0].asDict()
print("-999 sentinels replaced:", {k: v for k, v in sentinels.items() if v})

svi = svi_b.select(
    fips5(F.col("fips")).alias("fips"),
    F.col("st_abbr").alias("state_abbr"),
    F.col("state").alias("state_name"),
    F.col("county").alias("county_name"),
    *[num(src).alias(dst) for src, dst in SVI_FRIENDLY.items()],
).withColumn("population_per_sq_mi", F.round(F.expr("try_divide(population, area_sq_mi)"), 1))
save(svi, "svi_county", "CDC/ATSDR SVI 2022, one row per county. pct_* are ACS 2018-2022 estimates; svi_*_pctile are national percentile ranks 0-1 (higher = more vulnerable).")

# COMMAND ----------

# MAGIC %md ## County-name lookup (for sources with no FIPS, e.g. CMS hospitals)

# COMMAND ----------

base = spark.table(S("svi_county")).select("fips", "state_abbr", "state_name", "county_name")
keys = base.select(state_key(F.col("state_abbr")).alias("state_key"), county_key(F.col("county_name")).alias("county_key"), "fips").unionByName(
    base.select(state_key(F.col("state_name")).alias("state_key"), county_key(F.col("county_name")).alias("county_key"), "fips")
)
# drop ambiguous keys (same normalized name -> 2 counties) so we never guess wrong
lookup = keys.distinct().groupBy("state_key", "county_key").agg(F.count("*").alias("n"), F.first("fips").alias("fips")).where("n = 1").drop("n")
save(lookup, "county_lookup", "Normalized (state, county name) -> FIPS. Use hc.geo.attach_fips_by_name.")

# COMMAND ----------

# MAGIC %md ## ZIP (ZCTA) → county crosswalk

# COMMAND ----------

xw = (
    spark.table(B("zcta_county_xwalk_2020"))
    .where("geoid_zcta5_20 IS NOT NULL AND trim(geoid_zcta5_20) <> ''")
    .select(
        zip5(F.col("geoid_zcta5_20")).alias("zcta5"),
        fips5(F.col("geoid_county_20")).alias("county_fips"),
        F.col("namelsad_county_20").alias("county_name"),
        F.expr("try_cast(arealand_part AS DOUBLE)").alias("land_area_part"),
    )
)
w = Window.partitionBy("zcta5")
xw = (
    xw.withColumn("land_share", F.round(F.expr("try_divide(land_area_part, sum(land_area_part) OVER (PARTITION BY zcta5))"), 4))
    .withColumn("rank", F.row_number().over(w.orderBy(F.desc("land_area_part"))))
    .withColumn("is_primary", F.col("rank") == 1)
    .drop("rank")
)
save(xw, "zip_county_xwalk", "Census 2020 ZCTA-county overlaps. land_share = share of the ZCTA land area in that county; is_primary marks the largest.")

# COMMAND ----------

# MAGIC %md ## Rural-Urban Continuum Codes

# COMMAND ----------

rucc = (
    spark.table(B("usda_rucc_2023"))
    .groupBy(fips5(F.col("fips")).alias("fips"))
    .pivot("attribute", ["RUCC_2023", "Population_2020", "Description"])
    .agg(F.first("value"))
    .select(
        "fips",
        F.expr("try_cast(RUCC_2023 AS INT)").alias("rucc_2023"),
        F.expr("try_cast(Population_2020 AS BIGINT)").alias("population_2020"),
        F.col("Description").alias("rucc_description"),
    )
    .withColumn("is_rural", F.col("rucc_2023") >= 4)  # 1-3 metro, 4-9 nonmetro
)
save(rucc, "rucc_county", "USDA ERS RUCC 2023: 1-3 metro, 4-9 nonmetro (is_rural). One row per county.")

# COMMAND ----------

# MAGIC %md ## CDC PLACES (40 health measures)

# COMMAND ----------

places_long = spark.table(B("places_county")).select(
    fips5(F.col("location_id")).alias("fips"),
    F.expr("try_cast(year AS INT)").alias("year"),
    F.col("measure_id"),
    F.col("measure"),
    F.col("short_question_text"),
    F.col("category"),
    F.col("data_value_type_id").alias("value_type"),  # CrdPrv = crude, AgeAdjPrv = age-adjusted
    F.expr("try_cast(data_value AS DOUBLE)").alias("value_pct"),
    F.expr("try_cast(low_confidence_limit AS DOUBLE)").alias("ci_low"),
    F.expr("try_cast(high_confidence_limit AS DOUBLE)").alias("ci_high"),
)
save(places_long, "places_county_long", "CDC PLACES county estimates, long. value_type: CrdPrv (crude, for burden) or AgeAdjPrv (age-adjusted, for comparing counties).")

latest = (
    places_long.where("value_type = 'AgeAdjPrv' AND value_pct IS NOT NULL")
    .withColumn("rk", F.row_number().over(Window.partitionBy("fips", "measure_id").orderBy(F.desc("year"))))
    .where("rk = 1")
    .withColumn("col_name", F.concat(F.lit("places_"), F.lower("measure_id")))
)
measures = sorted(r.col_name for r in latest.select("col_name").distinct().collect())
places_wide = latest.groupBy("fips").pivot("col_name", measures).agg(F.first("value_pct"))
save(places_wide, "places_county_wide", "CDC PLACES age-adjusted prevalence (%), latest year per measure, one row per county. See places_measure_dictionary.")

dictionary = latest.groupBy("col_name", "measure_id").agg(
    F.first("measure").alias("measure"), F.first("short_question_text").alias("short_name"),
    F.first("category").alias("category"), F.max("year").alias("latest_year"),
)
save(dictionary, "places_measure_dictionary", "Maps places_* columns to the CDC measure text.")

# COMMAND ----------

# MAGIC %md ## Drug overdose deaths (VSRR, provisional)

# COMMAND ----------

od_b = spark.table(B("overdose_county_vsrr"))
od = od_b.select(
    fips5(F.col("fips")).alias("fips"),
    F.expr("try_cast(year AS INT)").alias("year"),
    F.expr("try_cast(month AS INT)").alias("month"),
    F.expr("try_cast(code2013 AS INT)").alias("nchs_urban_rural_2013"),  # 1 large central metro ... 6 noncore
    F.expr("try_cast(provisional_drug_overdose_deaths AS DOUBLE)").alias("deaths_12mo"),
    (F.coalesce(F.trim("provisional_drug_overdose_deaths"), F.lit("")) == "").alias("is_suppressed"),
    F.col("footnote").alias("suppression_note"),
    F.expr("try_cast(percentage_of_records_pending_investigation AS DOUBLE)").alias("pct_pending_investigation"),
    F.expr("to_date(try_to_timestamp(month_ending_date, 'MM/dd/yyyy'))").alias("period_end"),
    F.expr("to_date(try_to_timestamp(data_as_of, 'MM/dd/yyyy'))").alias("data_as_of"),
)
save(od, "overdose_county_monthly", "CDC VSRR provisional drug overdose deaths. deaths_12mo = 12-month-ending count for the period ending period_end. NULL + is_suppressed when 1-9 deaths (NCHS rule).")

annual = (
    od.where("month = 12")
    .select("fips", "year", F.col("deaths_12mo").alias("overdose_deaths"), "is_suppressed", "nchs_urban_rural_2013")
)
save(annual, "overdose_county_annual", "Calendar-year overdose deaths per county (12-month-ending December rows). is_suppressed = 1-9 deaths.")
display(annual.groupBy("year").agg(F.count("*").alias("counties"), F.round(F.avg(F.col("is_suppressed").cast("int")) * 100, 1).alias("pct_suppressed"), F.sum("overdose_deaths").alias("deaths_unsuppressed")).orderBy("year"))

# COMMAND ----------

# MAGIC %md ## HRSA shortage areas (primary care + mental health)

# COMMAND ----------


def hpsa_county(table, p):
    h = spark.table(B(table)).where("hpsa_status IN ('Designated', 'Proposed For Withdrawal')").select(
        fips5(F.col("state_and_county_federal_information_processing_standard_code")).alias("fips"),
        "hpsa_id", "designation_type",
        F.col("hpsa_component_type_code").alias("component_type"),
        F.expr("try_cast(hpsa_score AS INT)").alias("score"),
        F.expr("try_cast(hpsa_shortage AS DOUBLE)").alias("fte_short"),
        F.expr("try_cast(hpsa_designation_population AS DOUBLE)").alias("designation_pop"),
    )
    geo_types = ["Geographic HPSA", "High Needs Geographic HPSA"]
    per = h.groupBy("fips", "hpsa_id").agg(  # one row per designation (components repeat its numbers)
        F.max("score").alias("score"), F.max("fte_short").alias("fte_short"),
        F.max(F.col("designation_type").isin(geo_types).cast("int")).alias("is_geo"),
        F.max((F.col("designation_type").isin(geo_types) & (F.col("component_type") == "SCTY")).cast("int")).alias("is_whole_county"),
        F.max(F.col("designation_type").isin("HPSA Population").cast("int")).alias("is_pop"),
        F.max((~F.col("designation_type").isin(geo_types + ["HPSA Population"])).cast("int")).alias("is_facility"),
    )
    return per.groupBy("fips").agg(
        F.countDistinct("hpsa_id").alias(f"hpsa_{p}_n_designations"),
        F.max("score").alias(f"hpsa_{p}_max_score"),
        F.round(F.sum("fte_short"), 2).alias(f"hpsa_{p}_fte_short"),
        (F.max("is_geo") == 1).alias(f"hpsa_{p}_has_geographic"),
        (F.max("is_whole_county") == 1).alias(f"hpsa_{p}_whole_county"),
        (F.max("is_pop") == 1).alias(f"hpsa_{p}_has_population"),
        (F.max("is_facility") == 1).alias(f"hpsa_{p}_has_facility"),
    )


hpsa = hpsa_county("hpsa_primary_care", "pc").join(hpsa_county("hpsa_mental_health", "mh"), "fips", "full").where("fips IS NOT NULL")
save(hpsa, "hpsa_county", "HRSA HPSAs (designated or proposed-for-withdrawal) per county. score 0-25/26 (higher = worse shortage); fte_short = clinicians needed to remove the shortage.")

# COMMAND ----------

# MAGIC %md ## CMS hospitals (no FIPS: match on state + county name, fall back to ZIP)

# COMMAND ----------

hosp_b = spark.table(B("cms_hospital_general_info"))
as_int = lambda c: F.expr(f"try_cast(trim(`{c}`) AS INT)")  # 'Not Available' -> NULL  # noqa: E731
hosp = hosp_b.select(
    F.col("facility_id").alias("ccn"), "facility_name", "city_town", F.col("state").alias("state_abbr"),
    zip5(F.col("zip_code")).alias("zip5"), F.col("county_parish").alias("county_name_raw"),
    "hospital_type", "hospital_ownership",
    (F.col("emergency_services") == "Yes").alias("has_emergency_services"),
    (F.col("meets_criteria_for_birthing_friendly_designation") == "Y").alias("is_birthing_friendly"),
    as_int("hospital_overall_rating").alias("overall_star_rating"),
    *[as_int(c).alias(c.replace("count_of_", "n_").replace("_measures", "")) for c in (
        "count_of_mort_measures_worse", "count_of_mort_measures_better",
        "count_of_readm_measures_worse", "count_of_readm_measures_better",
        "count_of_safety_measures_worse",
    )],
)
lookup = spark.table(S("county_lookup"))
by_name = attach_fips_by_name(hosp, lookup, "state_abbr", "county_name_raw", out_col="fips_by_name")
by_zip = attach_fips_by_zip(by_name, spark.table(S("zip_county_xwalk")), "zip5", out_col="fips_by_zip")
hosp_final = by_zip.select(
    "*",
    F.coalesce("fips_by_name", "fips_by_zip").alias("fips"),
    F.when(F.col("fips_by_name").isNotNull(), "county_name").when(F.col("fips_by_zip").isNotNull(), "zip").otherwise("unmatched").alias("fips_match_method"),
    (F.col("fips_by_name").isNotNull() & F.col("fips_by_zip").isNotNull() & (F.col("fips_by_name") != F.col("fips_by_zip"))).alias("fips_name_zip_disagree"),
).drop("fips_by_name", "fips_by_zip")
save(hosp_final, "hospitals", "CMS Hospital General Information, one row per hospital (ccn). fips matched by state+county name, else ZIP primary county (fips_match_method).")
display(hosp_final.groupBy("fips_match_method").count())
display(hosp_final.where("fips_match_method = 'unmatched'").select("state_abbr", "county_name_raw", "zip5", "facility_name").limit(50))
