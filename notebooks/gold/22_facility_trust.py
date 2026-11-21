# Databricks notebook source
# MAGIC %md
# MAGIC # Gold 22 · `facility_trust`: how much should we believe this record at all?
# MAGIC
# MAGIC Service evidence (gold/21) asks "does the text say they do X?". This asks "is the record itself
# MAGIC coherent?" Each problem multiplies the trust score by a penalty and adds a **plain-language caution**
# MAGIC that the user sees. Penalties are in `care.TRUST_PENALTIES`.
# MAGIC
# MAGIC | Check | Penalty |
# MAGIC |---|---|
# MAGIC | malformed record (shifted columns) | × 0.30 |
# MAGIC | coordinates outside India | × 0.40 |
# MAGIC | no usable location | × 0.50 |
# MAGIC | coordinates > 50 km from the PIN's area (city breaks the tie) | × 0.80 |
# MAGIC | single web source / 2-3 sources | × 0.80 / × 0.90 |
# MAGIC | state disagrees with PIN · lots of beds but ≤ 2 doctors · almost no detail | × 0.85 each |
# MAGIC | PIN not in directory · possible duplicate · location from PIN only | × 0.90 each |
# MAGIC
# MAGIC Strengths (several sources, beds and doctors listed, year established) are listed as **supporting
# MAGIC facts**, and they are cited too, but they don't raise the score above 1.
# MAGIC
# MAGIC **Independent second source**: a facility that also appears in the government's National Health Portal
# MAGIC hospital directory (gold/27) is not penalised for having few web sources, and the match is listed as a
# MAGIC supporting fact. The directory confirms that the facility exists; it says nothing about its services.

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

import re

from hc import care, ext
from hc.io import write_table

S, G = cfg.silver, cfg.gold
fm = spark.table(S("facility_master"))
listed = spark.table(G("facility_external_matches")).select("facility_id", F.lit(True).alias("listed_in_directory"))
fm = fm.join(listed, "facility_id", "left").withColumn("listed_in_directory", F.coalesce("listed_in_directory", F.lit(False)))
P = care.TRUST_PENALTIES

flags = {
    "malformed_record": F.col("is_malformed"),
    "coords_outside_india": F.col("coords_outside_india"),
    "no_location": F.col("lat").isNull(),
    "location_from_pin_only": ~F.col("coords_valid") & ~F.col("coords_outside_india") & F.col("lat").isNotNull(),
    "pin_coords_conflict": F.col("pin_distance_km") > care.PIN_COORD_CONFLICT_KM,
    "state_conflict": F.col("state_conflict"),
    "pin_not_found": F.col("pin").isNotNull() & ~F.col("pin_found"),
    "single_source": (F.col("n_sources") <= 1) & ~F.col("listed_in_directory"),
    "few_sources": F.col("n_sources").between(2, 3) & ~F.col("listed_in_directory"),
    "possible_duplicate": F.col("dup_reason").isNotNull(),
    "beds_doctors_implausible": (F.col("capacity") >= 100) & (F.col("number_doctors") <= 2),
    "sparse_record": F.col("capacity").isNull() & F.col("number_doctors").isNull() & F.col("year_established").isNull() & (F.size("equipment") == 0),
}
assert set(flags) == set(P), set(flags) ^ set(P)

ALIASES = {"state_text": F.coalesce(F.col("state_text"), F.lit("?")), "pin_state": F.col("pin_state")}


def message(template):
    """'{capacity} beds' -> format_string('%s beds', capacity)."""
    names = re.findall(r"\{(\w+)\}", template)
    fmt = re.sub(r"\{\w+\}", "%s", template)
    return F.format_string(fmt, *[ALIASES.get(n, F.col(n)).cast("string") for n in names]) if names else F.lit(template)


df = fm
trust = F.lit(1.0)
cautions = []
for name, cond in flags.items():
    factor, template = P[name]
    c = F.coalesce(cond, F.lit(False))
    df = df.withColumn(f"flag_{name}", c)
    trust = trust * F.when(c, F.lit(factor)).otherwise(F.lit(1.0))
    cautions.append(F.when(c, message(template)))

supporting = [
    F.when(F.col("listed_in_directory"), F.lit(ext.DIRECTORY_SUPPORTING_FACT)),
    F.when(F.col("n_sources") >= 4, F.format_string("Built from %d independent web sources.", "n_sources")),
    F.when(F.col("capacity").isNotNull(), F.format_string("Lists %d beds.", "capacity")),
    F.when(F.col("number_doctors").isNotNull(), F.format_string("Lists %d doctor(s).", "number_doctors")),
    F.when(F.col("year_established").between(1800, 2026), F.format_string("Established %d.", "year_established")),
    F.when(F.col("coords_valid") & (F.coalesce(F.col("pin_distance_km"), F.lit(0.0)) <= 10), F.lit("Coordinates match the PIN code area.")),
    F.when(F.col("phone").isNotNull(), F.lit("Phone number listed.")),
]

out = df.select(
    "facility_id",
    F.round(F.greatest(F.lit(care.TRUST_FLOOR), trust), 3).alias("trust_score"),
    F.filter(F.array(*cautions), lambda x: x.isNotNull()).alias("cautions"),
    F.filter(F.array(*supporting), lambda x: x.isNotNull()).alias("supporting_facts"),
    *[f"flag_{n}" for n in flags],
    F.col("listed_in_directory").alias("flag_listed_in_directory"),
)
write_table(out, G("facility_trust"))
spark.sql(
    f"COMMENT ON TABLE {G('facility_trust')} IS 'Per-facility record trust: trust_score (product of penalties), "
    "cautions (plain-language reasons it was lowered), supporting_facts, and one boolean column per check.'"
)

# COMMAND ----------

display(spark.sql(f"""
  SELECT CASE WHEN trust_score >= 0.75 THEN '1 high (>= 0.75)' WHEN trust_score >= 0.5 THEN '2 medium (0.5-0.75)' ELSE '3 low (< 0.5)' END AS trust_band,
         count(*) AS facilities
  FROM {G('facility_trust')} GROUP BY 1 ORDER BY 1
"""))
display(spark.sql(
    "SELECT " + ", ".join(f"count_if(flag_{n}) AS {n}" for n in flags) + f" FROM {G('facility_trust')}"
))
