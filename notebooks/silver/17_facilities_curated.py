# Databricks notebook source
# MAGIC %md
# MAGIC # Silver 17 · `facilities_silver_curated`: one connected, cleaned row per facility
# MAGIC
# MAGIC The source of truth for "what do we know about each facility", combining every source we have:
# MAGIC
# MAGIC | Source | How it joins | What it adds |
# MAGIC |---|---|---|
# MAGIC | Virtue Foundation (`facility_master`) | the base: every VF record | claims text, specialties, beds, doctors, quality flags |
# MAGIC | National Health Portal directory (`ext_hospital_directory`) | same PIN + name match (gold/27); unmatched directory hospitals become their own rows | independent confirmation, phone / beds / ownership gaps filled, specialty and service mentions, ~28k hospitals we didn't have |
# MAGIC | Census 2011 boundaries (`facility_district`) | point in polygon (gold/26), or the directory's own district code | `district_code_2011` |
# MAGIC | IHDS-II survey (`ext_ihds_facilities`) | **not per facility** (the survey has no names or locations): by facility type × ownership | what share of similar facilities offer each service: an expectation, never evidence |
# MAGIC
# MAGIC Every filled-in field says where it came from (`*_source`). Directory-only rows have `in_vf = false` and
# MAGIC no service evidence; they show coverage, not capability.
# MAGIC
# MAGIC **Services, three ways**
# MAGIC * `services_vf`: Care Finder services with direct evidence in the facility's own VF text (gold/21)
# MAGIC * `services_directory`: Care Finder services named in the directory's specialties / facilities lists
# MAGIC * `services_corroborated`: in both (two independent sources agree)
# MAGIC * `ihds_services_mentioned`: IHDS service categories (immunisation, TB/DOTS, antenatal, childbirth…) found in any text
# MAGIC * `ihds_expected_services` / `ihds_expected_care_finder`: % of surveyed facilities of the same type and ownership offering each
# MAGIC * `ihds_likely_unlisted`: services that ≥ 70% of surveyed peers offer but this facility's text never mentions
# MAGIC
# MAGIC All text is normalised (`hc.text.clean_text`): no literal `\n`, line breaks, invisible characters or HTML entities.

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

import pandas as pd

from hc import care, ext, ihds
from hc.io import write_table
from hc.naming import snake
from hc.text import clean_text

S, G = cfg.silver, cfg.gold
SPEC_MAP = F.create_map(*[x for kv in ext.SPECIALTY_SYNONYMS.items() for x in (F.lit(kv[0]), F.lit(kv[1]))])


def norm_spec(x):
    """Spark twin of ext.normalize_specialty."""
    s = F.regexp_replace(x, "([a-z])([A-Z])", "$1 $2")
    s = F.regexp_replace(F.lower(s), "&", " and ")
    s = F.trim(F.regexp_replace(F.regexp_replace(s, "[^a-z0-9 ]", " "), r"\s+", " "))
    s = F.trim(F.regexp_replace(s, ext.SPECIALTY_SUFFIXES, ""))
    s = F.coalesce(SPEC_MAP[s], s)
    return F.when(F.length(s) > 1, s)


def norm_specs(arr_col):
    return F.array_sort(F.array_distinct(F.filter(F.transform(F.coalesce(arr_col, F.array().cast("array<string>")), norm_spec), lambda x: x.isNotNull())))


def text_hits(text_col, patterns: dict) -> "F.Column":
    """Array of keys whose regex matches the (lower-cased) text."""
    t = F.lower(F.coalesce(text_col, F.lit("")))
    return F.filter(F.array(*[F.when(t.rlike(rx), F.lit(k)) for k, rx in patterns.items()]), lambda x: x.isNotNull())


CF_PATTERNS = {s.key: s.pattern for s in care.SERVICES}
IHDS_PATTERNS = {snake(ihds.SERVICES[code]): rx for code, rx in ihds.SERVICE_TEXT_PATTERNS.items()}

# COMMAND ----------

# MAGIC %md ## Inputs

# COMMAND ----------

fm = spark.table(S("facility_master"))
nhp = spark.table(S("ext_hospital_directory"))
matches = spark.table(G("facility_external_matches")).select(
    "facility_id", "nhp_id", F.col("overlap").alias("match_overlap"), F.col("method").alias("match_method"))
fdist = spark.table(G("facility_district")).select("facility_id", F.col("district_code").alias("vf_district_code"), F.col("district_2011").alias("vf_district_2011"))
unmatched_loc = spark.table(G("ext_directory_unmatched")).select("nhp_id", F.col("lat").alias("u_lat"), F.col("lon").alias("u_lon"), F.col("location_source").alias("u_location_source"))
bnd = spark.table(S("district_boundaries_2011")).select(F.col("district_code").alias("dc"), F.col("district").alias("dname_2011"))

ev = spark.table(G("facility_service_evidence"))
services_vf = ev.where("evidence_tier = 'direct'").groupBy("facility_id").agg(F.array_sort(F.collect_set("service_key")).alias("services_vf"))
conf = (spark.table(G("care_finder_index")).groupBy("facility_id")
        .agg(F.map_from_entries(F.collect_list(F.struct("service_key", "confidence"))).alias("service_confidence")))

d = nhp.select(
    "nhp_id", F.col("name").alias("d_name"), F.col("ownership").alias("d_ownership"), F.col("care_type").alias("d_care_type"),
    F.col("address").alias("d_address"), F.col("district").alias("d_district"), F.col("state").alias("d_state"),
    F.col("pin").alias("d_pin"), F.col("phone").alias("d_phone"), F.col("website").alias("d_website"),
    F.col("beds").alias("d_beds"), F.col("doctors").alias("d_doctors"), F.col("year_established").alias("d_year"),
    F.col("specialties").alias("d_specialties"), F.col("facilities").alias("d_facilities"),
    F.col("emergency_services").alias("d_emergency_services"), F.col("district_code").alias("d_district_code"),
    F.col("lat").alias("d_lat"), F.col("lon").alias("d_lon"), F.col("system_of_medicine").alias("d_system"),
)
d_text = F.concat_ws(" | ", F.array_join(F.coalesce("d_specialties", F.array()), " | "), F.array_join(F.coalesce("d_facilities", F.array()), " | "),
                     F.coalesce("d_care_type", F.lit("")), F.coalesce("d_emergency_services", F.lit("")))

# directory care type -> our facility_type
d_type = (F.when(F.lower("d_care_type").rlike("dispensary|clinic|primary health|\\bphc\\b|sub ?cent"), "clinic")
           .when(F.lower("d_care_type").rlike("hospital|community health|\\bchc\\b|medical college|nursing home"), "hospital"))

# COMMAND ----------

# MAGIC %md ## Part 1: every Virtue Foundation facility, enriched where the directory matches

# COMMAND ----------

vf_text = F.concat_ws(" | ", F.coalesce("description", F.lit("")), F.array_join("capability", " | "),
                      F.array_join("procedure", " | "), F.array_join("equipment", " | "))
vf_owner = F.when(F.lower("operator_type").isin("public", "government"), "public").when(F.lower("operator_type") == "private", "private")

vf = (
    fm.join(matches, "facility_id", "left").join(d, "nhp_id", "left").join(fdist, "facility_id", "left")
    .join(services_vf, "facility_id", "left").join(conf, "facility_id", "left")
    .select(
        F.col("facility_id").alias("curated_id"), "facility_id", "nhp_id",
        F.lit(True).alias("in_vf"), F.col("nhp_id").isNotNull().alias("in_directory"), "match_method", "match_overlap",
        "name", F.when(F.col("d_name").isNotNull() & (F.lower("d_name") != F.lower("name")), F.col("d_name")).alias("name_in_directory"),
        F.coalesce("facility_type", d_type).alias("facility_type"),
        F.when(F.col("facility_type").isNotNull(), "vf").when(d_type.isNotNull(), "directory").alias("facility_type_source"),
        F.coalesce(vf_owner, F.col("d_ownership")).alias("ownership"),
        F.when(vf_owner.isNotNull(), "vf").when(F.col("d_ownership").isNotNull(), "directory").alias("ownership_source"),
        "address", "city", "district", "state", "pin",
        F.coalesce("vf_district_code", "d_district_code").alias("district_code_2011"),
        "lat", "lon", "location_source",
        F.coalesce("phone", "d_phone").alias("phone"),
        F.when(F.col("phone").isNotNull(), "vf").when(F.col("d_phone").isNotNull(), "directory").alias("phone_source"),
        "email", F.coalesce("website", "d_website").alias("website"),
        F.coalesce("capacity", "d_beds").alias("beds"),
        F.when(F.col("capacity").isNotNull(), "vf").when(F.col("d_beds").isNotNull(), "directory").alias("beds_source"),
        F.coalesce("number_doctors", "d_doctors").alias("doctors"),
        F.when(F.col("number_doctors").isNotNull(), "vf").when(F.col("d_doctors").isNotNull(), "directory").alias("doctors_source"),
        F.coalesce("year_established", "d_year").alias("year_established"),
        F.when(F.col("year_established").isNotNull(), "vf").when(F.col("d_year").isNotNull(), "directory").alias("year_source"),
        norm_specs(F.col("specialties")).alias("specialties_vf"),
        norm_specs(F.col("d_specialties")).alias("specialties_directory"),
        F.coalesce("services_vf", F.array().cast("array<string>")).alias("services_vf"),
        text_hits(F.when(F.col("nhp_id").isNotNull(), d_text), CF_PATTERNS).alias("services_directory"),
        text_hits(F.concat_ws(" | ", vf_text, F.when(F.col("nhp_id").isNotNull(), d_text)), IHDS_PATTERNS).alias("ihds_services_mentioned"),
        "service_confidence",
        F.col("n_sources").alias("n_web_sources"), F.slice("source_urls", 1, 10).alias("source_urls"),
        "description", "is_malformed", "coords_valid", "state_conflict", "dup_reason",
    )
)

# COMMAND ----------

# MAGIC %md ## Part 2: directory hospitals that aren't in the VF data

# COMMAND ----------

matched_ids = matches.select("nhp_id").distinct()
donly = (
    d.join(matched_ids, "nhp_id", "left_anti").join(unmatched_loc, "nhp_id", "left")
    .join(F.broadcast(bnd), F.col("d_district_code") == F.col("dc"), "left")
    .select(
        F.concat(F.lit("nhp-"), F.col("nhp_id")).alias("curated_id"), F.lit(None).cast("string").alias("facility_id"), "nhp_id",
        F.lit(False).alias("in_vf"), F.lit(True).alias("in_directory"), F.lit(None).cast("string").alias("match_method"),
        F.lit(None).cast("double").alias("match_overlap"),
        F.col("d_name").alias("name"), F.lit(None).cast("string").alias("name_in_directory"),
        F.coalesce(d_type, F.lit("hospital")).alias("facility_type"),
        F.when(d_type.isNotNull(), "directory").otherwise("assumed (hospital directory)").alias("facility_type_source"),
        F.col("d_ownership").alias("ownership"), F.when(F.col("d_ownership").isNotNull(), "directory").alias("ownership_source"),
        F.col("d_address").alias("address"), F.lit(None).cast("string").alias("city"),
        F.coalesce("d_district", "dname_2011").alias("district"), F.col("d_state").alias("state"), F.col("d_pin").alias("pin"),
        F.col("d_district_code").alias("district_code_2011"),
        F.col("u_lat").alias("lat"), F.col("u_lon").alias("lon"), F.col("u_location_source").alias("location_source"),
        F.col("d_phone").alias("phone"), F.when(F.col("d_phone").isNotNull(), "directory").alias("phone_source"),
        F.lit(None).cast("string").alias("email"), F.col("d_website").alias("website"),
        F.col("d_beds").alias("beds"), F.when(F.col("d_beds").isNotNull(), "directory").alias("beds_source"),
        F.col("d_doctors").alias("doctors"), F.when(F.col("d_doctors").isNotNull(), "directory").alias("doctors_source"),
        F.col("d_year").alias("year_established"), F.when(F.col("d_year").isNotNull(), "directory").alias("year_source"),
        F.array().cast("array<string>").alias("specialties_vf"), norm_specs(F.col("d_specialties")).alias("specialties_directory"),
        F.array().cast("array<string>").alias("services_vf"), text_hits(d_text, CF_PATTERNS).alias("services_directory"),
        text_hits(d_text, IHDS_PATTERNS).alias("ihds_services_mentioned"),
        F.lit(None).cast("map<string,string>").alias("service_confidence"),
        F.lit(0).alias("n_web_sources"), F.array().cast("array<string>").alias("source_urls"),
        F.lit(None).cast("string").alias("description"), F.lit(False).alias("is_malformed"),
        F.coalesce(F.col("u_location_source") == "listed coordinates", F.lit(False)).alias("coords_valid"),
        F.lit(False).alias("state_conflict"), F.lit(None).cast("string").alias("dup_reason"),
    )
)

cur = vf.unionByName(donly)

# COMMAND ----------

# MAGIC %md ## IHDS survey expectations by facility type × ownership (filled in, labelled as expectations)

# COMMAND ----------

ih = spark.table(S("ext_ihds_facilities")).toPandas()
ih = ih[ih["our_type"].notna()]
svc_cols = [c for c in ih.columns if c.startswith("svc_")]
cf_cols = [c for c in ih.columns if c.startswith("offers_")]
ih[svc_cols + cf_cols] = ih[svc_cols + cf_cols].astype("float")


def peer_rows(g: pd.DataFrame, t: str, own: str) -> dict:
    return {
        "peer_type": t, "peer_ownership": own, "ihds_peer_n": int(len(g)),
        "ihds_expected_services": {c[4:]: round(100 * g[c].mean(), 1) for c in svc_cols if g[c].notna().any()},
        "ihds_expected_care_finder": {c[7:]: round(100 * g[c].mean(), 1) for c in cf_cols if g[c].notna().any()},
    }


peers = [peer_rows(g, t, o) for (t, o), g in ih.groupby(["our_type", "ownership"])]
peers += [peer_rows(g, t, "*") for t, g in ih.groupby("our_type")]  # when ownership is unknown
peer_df = spark.createDataFrame(
    pd.DataFrame(peers),
    "peer_type string, peer_ownership string, ihds_peer_n int, ihds_expected_services map<string,double>, ihds_expected_care_finder map<string,double>",
)
exact = peer_df.where("peer_ownership <> '*'")
pooled = peer_df.where("peer_ownership = '*'").select(
    "peer_type", F.col("ihds_peer_n").alias("p_n"), F.col("ihds_expected_services").alias("p_svc"), F.col("ihds_expected_care_finder").alias("p_cf"))

cur = (
    cur.join(F.broadcast(exact), (cur.facility_type == exact.peer_type) & (cur.ownership == exact.peer_ownership), "left")
    .drop("peer_type", "peer_ownership")
    .join(F.broadcast(pooled), cur.facility_type == pooled.peer_type, "left")
    .withColumn("ihds_peer_group", F.when(F.col("ihds_peer_n").isNotNull(), F.concat_ws(" ", "ownership", "facility_type"))
                .when(F.col("p_n").isNotNull(), F.concat(F.col("facility_type"), F.lit(" (any ownership)"))))
    .withColumn("ihds_peer_n", F.coalesce("ihds_peer_n", "p_n"))
    .withColumn("ihds_expected_services", F.coalesce("ihds_expected_services", "p_svc"))
    .withColumn("ihds_expected_care_finder", F.coalesce("ihds_expected_care_finder", "p_cf"))
    .drop("peer_type", "p_n", "p_svc", "p_cf")
    .withColumn("ihds_likely_unlisted", F.array_sort(F.filter(
        F.map_keys(F.map_filter(F.coalesce("ihds_expected_services", F.create_map().cast("map<string,double>")),
                                lambda k, v: v >= ihds.LIKELY_THRESHOLD_PCT)),
        lambda k: ~F.array_contains("ihds_services_mentioned", k))))
)

# COMMAND ----------

# MAGIC %md ## Derived columns and final cleaning

# COMMAND ----------

cur = (
    cur.withColumn("specialties", F.array_sort(F.array_union("specialties_vf", "specialties_directory")))
    .withColumn("specialties_agree", F.size(F.array_intersect("specialties_vf", "specialties_directory")))
    .withColumn("services_corroborated", F.array_sort(F.array_intersect("services_vf", "services_directory")))
    .withColumn("services_any", F.array_sort(F.array_union("services_vf", "services_directory")))
    .withColumn("n_independent_sources", F.col("n_web_sources") + F.col("in_directory").cast("int"))
    .withColumn("completeness", F.round((
        F.col("phone").isNotNull().cast("int") + F.col("beds").isNotNull().cast("int") + F.col("doctors").isNotNull().cast("int")
        + F.col("year_established").isNotNull().cast("int") + F.col("website").isNotNull().cast("int") + F.col("lat").isNotNull().cast("int")
        + F.col("pin").isNotNull().cast("int") + (F.size("specialties") > 0).cast("int") + (F.size("services_any") > 0).cast("int")) / 9, 2))
)
# belt and braces: every string column normalised once more (dashboards choke on stray line breaks)
str_cols = [f.name for f in cur.schema.fields if f.dataType.simpleString() == "string"]
cur = cur.select(*[F.when(F.length(clean_text(F.col(c))) > 0, clean_text(F.col(c))).alias(c) if c in str_cols else F.col(c) for c in cur.columns])

ORDER = [
    "curated_id", "facility_id", "nhp_id", "in_vf", "in_directory", "match_method", "match_overlap",
    "name", "name_in_directory", "facility_type", "facility_type_source", "ownership", "ownership_source",
    "address", "city", "district", "state", "pin", "district_code_2011", "lat", "lon", "location_source", "coords_valid",
    "phone", "phone_source", "email", "website", "beds", "beds_source", "doctors", "doctors_source", "year_established", "year_source",
    "specialties", "specialties_vf", "specialties_directory", "specialties_agree",
    "services_any", "services_vf", "services_directory", "services_corroborated", "service_confidence",
    "ihds_services_mentioned", "ihds_peer_group", "ihds_peer_n", "ihds_expected_services", "ihds_expected_care_finder", "ihds_likely_unlisted",
    "n_web_sources", "n_independent_sources", "completeness", "is_malformed", "state_conflict", "dup_reason", "source_urls", "description",
]
cur = cur.select(*ORDER)
write_table(cur, S("facilities_silver_curated"))
spark.sql(
    f"COMMENT ON TABLE {S('facilities_silver_curated')} IS 'Source of truth: one cleaned row per facility. Virtue Foundation records "
    "enriched with the National Health Portal directory (matched on PIN + name), plus directory-only hospitals (in_vf = false). "
    "*_source columns say where each filled field came from. ihds_* columns are IHDS-II survey expectations for facilities of the "
    "same type and ownership, not evidence about this facility.'"
)

# COMMAND ----------

# MAGIC %md ## Checks

# COMMAND ----------

T = S("facilities_silver_curated")
assert spark.table(T).count() == spark.table(T).select("curated_id").distinct().count(), "curated_id must be unique"
assert spark.table(T).where("in_vf").count() == fm.count(), "every VF facility must be present once"
bad = spark.sql(f"SELECT count(*) n FROM {T} WHERE " + " OR ".join(
    f"{c} RLIKE '[\\\\n\\\\r\\\\t]' OR {c} LIKE '%\\\\\\\\n%'" for c in ["name", "address", "description", "phone", "website", "district"])).first().n
assert bad == 0, f"{bad} rows still carry line breaks or literal \\n"
display(spark.sql(f"""
  SELECT count(*) AS facilities, count_if(in_vf) AS from_vf, count_if(in_vf AND in_directory) AS vf_also_in_directory,
         count_if(NOT in_vf) AS directory_only, count_if(phone_source = 'directory') AS phone_filled_from_directory,
         count_if(beds_source = 'directory') AS beds_filled_from_directory, count_if(ownership_source = 'directory') AS ownership_filled,
         count_if(size(services_corroborated) > 0) AS with_corroborated_service, count_if(specialties_agree > 0) AS specialties_agree,
         count_if(size(ihds_likely_unlisted) > 0) AS with_likely_unlisted, round(avg(completeness), 2) AS avg_completeness
  FROM {T}
"""))
