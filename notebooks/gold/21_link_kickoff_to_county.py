# Databricks notebook source
# MAGIC %md
# MAGIC # Gold 21 · Link the kickoff data to `county_context` (template, fill in Saturday)
# MAGIC
# MAGIC Pick the geography the organizer data has, attach `county_fips`, check the match rate, and join.
# MAGIC
# MAGIC | Organizer data has... | Use |
# MAGIC |---|---|
# MAGIC | county FIPS | `fips5(col)`, already standardized by silver/11 if the name contains "fips" |
# MAGIC | ZIP / ZCTA | `attach_fips_by_zip(df, xwalk, "zip_col")` (primary county by land area) |
# MAGIC | state + county name | `attach_fips_by_name(df, lookup, "state_col", "county_col")` |
# MAGIC | hospital CCN | join `hc_silver.hospitals` on `ccn`, which carries `fips` |
# MAGIC | only state | aggregate `county_context` to state (population-weighted) |
# MAGIC | patient-level, no geography | skip the join; use county context only for framing |

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

from hc.geo import attach_fips_by_name, attach_fips_by_zip, fips5
from hc.io import write_table

source_table = widget(dbutils, "source_table", "", "silver table to link, e.g. kickoff_encounters")
geo_mode = widget(dbutils, "geo_mode", "zip", "fips | zip | name | ccn")
col_a = widget(dbutils, "geo_col", "", "fips/zip/ccn column, or STATE column for name mode")
col_b = widget(dbutils, "county_col", "", "county-name column (name mode only)")
target = widget(dbutils, "target_table", "", "gold output table (blank = <source>_with_county)")

if not source_table:
    dbutils.notebook.exit("Set source_table (and geo_mode / geo_col) to run this notebook.")

df = spark.table(cfg.silver(source_table))
if geo_mode == "fips":
    linked = df.withColumn("county_fips", fips5(F.col(col_a)))
elif geo_mode == "zip":
    linked = attach_fips_by_zip(df, spark.table(cfg.silver("zip_county_xwalk")), col_a, share_col="zip_county_land_share")
elif geo_mode == "name":
    linked = attach_fips_by_name(df, spark.table(cfg.silver("county_lookup")), col_a, col_b)
elif geo_mode == "ccn":
    linked = df.join(spark.table(cfg.silver("hospitals")).select("ccn", F.col("fips").alias("county_fips")), F.col(col_a) == F.col("ccn"), "left").drop("ccn")
else:
    raise ValueError("geo_mode must be fips | zip | name | ccn")

# COMMAND ----------

# MAGIC %md ### Match rate (put this number in the write-up)

# COMMAND ----------

display(linked.groupBy(F.col("county_fips").isNotNull().alias("matched")).count())
display(linked.where("county_fips IS NULL").groupBy(col_a).count().orderBy(F.desc("count")).limit(50))

# COMMAND ----------

ctx = spark.table(cfg.gold("county_context")).withColumnRenamed("fips", "county_fips")
dup_cols = (set(ctx.columns) & set(linked.columns)) - {"county_fips"}
enriched = linked.join(ctx.drop(*dup_cols), "county_fips", "left")
out = target or f"{source_table}_with_county"
write_table(enriched, cfg.gold(out))
print(f"{cfg.gold(out)}: {spark.table(cfg.gold(out)).count():,} rows x {len(enriched.columns)} columns")
