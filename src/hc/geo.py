"""Geography standardization: the glue that lets any healthcare table join to county context.

Three ways in, one key out (5-digit county FIPS):
    fips5(col)                       '1001', '1001.0', '01001' -> '01001'
    attach_fips_by_zip(df, ...)      ZIP / ZIP+4 -> ZCTA -> primary county
    attach_fips_by_name(df, ...)     ('UT' or 'Utah', 'Salt Lake County') -> '49035'
"""

from __future__ import annotations

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F

_COUNTY_SUFFIX = (
    r"\b(CITY AND BOROUGH|CENSUS AREA|PLANNING REGION|MUNICIPALITY|MUNICIPIO|COUNTY|PARISH|BOROUGH)\b"
)


def fips5(col: Column) -> Column:
    """County FIPS as a zero-padded 5-char string; null when it can't be one."""
    c = F.regexp_replace(F.trim(col.cast("string")), r"\.0+$", "")
    c = F.regexp_replace(c, r"[^0-9]", "")
    return F.when(F.length(c).isin(4, 5), F.lpad(c, 5, "0"))


def state_fips2(col: Column) -> Column:
    c = F.regexp_replace(F.regexp_replace(F.trim(col.cast("string")), r"\.0+$", ""), r"[^0-9]", "")
    return F.when(F.length(c).isin(1, 2), F.lpad(c, 2, "0"))


def zip5(col: Column) -> Column:
    """'84101', '84101-1234', '841011234', '2134' (lost leading zero) -> 5-char ZIP."""
    raw = F.regexp_replace(F.trim(col.cast("string")), r"\.0+$", "")
    first = F.regexp_extract(raw, r"^(\d{3,5})(?:-?\d{4})?$", 1)
    return F.when(first != "", F.lpad(first, 5, "0"))


def haversine_km(lat1: Column, lon1: Column, lat2: Column, lon2: Column) -> Column:
    """Great-circle distance in km. SQL twin is in gold/43 (recommend_facilities)."""
    a = F.pow(F.sin(F.radians(lat2 - lat1) / 2), 2) + F.cos(F.radians(lat1)) * F.cos(F.radians(lat2)) * F.pow(
        F.sin(F.radians(lon2 - lon1) / 2), 2
    )
    return F.lit(2 * 6371.0) * F.asin(F.sqrt(a))


def pin6(col: Column) -> Column:
    """Indian PIN code: '110 002', '110002.0' -> '110002'; anything not 6 digits starting 1-9 -> NULL."""
    c = F.regexp_replace(F.regexp_replace(F.trim(col.cast("string")), r"\.0+$", ""), r"\s", "")
    return F.when(c.rlike(r"^[1-9][0-9]{5}$"), c)


def county_key(col: Column) -> Column:
    """Normalized county name for fuzzy-ish joins: 'St. Mary's Parish' -> 'STMARYS'.
    Keeps the word CITY so 'Baltimore city' and 'Baltimore County' stay distinct."""
    c = F.upper(F.trim(col))
    c = F.translate(c, "ÁÀÂÄÃÉÈÊËÍÌÎÏÓÒÔÖÕÚÙÛÜÑÇ", "AAAAAEEEEIIIIOOOOOUUUUNC")
    c = F.regexp_replace(c, r"[\.'’`]", "")
    c = F.regexp_replace(c, r"^THE DISTRICT$", "DISTRICT OF COLUMBIA")  # CMS spelling for DC
    for short, full in (("E", "EAST"), ("W", "WEST"), ("N", "NORTH"), ("S", "SOUTH")):  # 'E. Baton Rouge'
        c = F.regexp_replace(c, rf"^{short}\s", f"{full} ")
    c = F.regexp_replace(c, _COUNTY_SUFFIX, "")
    c = F.regexp_replace(c, r"\bSAINTE\b", "STE")
    c = F.regexp_replace(c, r"\bSAINT\b", "ST")
    return F.regexp_replace(c, r"[^A-Z0-9]", "")


def state_key(col: Column) -> Column:
    return F.regexp_replace(F.upper(F.trim(col)), r"[^A-Z]", "")


def attach_fips_by_name(
    df: DataFrame, county_lookup: DataFrame, state_col: str, county_col: str, out_col: str = "county_fips"
) -> DataFrame:
    """Left-join FIPS using silver.county_lookup (state_key, county_key, fips).
    state_col may hold 'UT' or 'Utah'."""
    lk = county_lookup.select(
        F.col("state_key").alias("__sk"), F.col("county_key").alias("__ck"), F.col("fips").alias(out_col)
    )
    keyed = df.withColumn("__sk", state_key(F.col(state_col))).withColumn("__ck", county_key(F.col(county_col)))
    return keyed.join(F.broadcast(lk), ["__sk", "__ck"], "left").drop("__sk", "__ck")


def attach_fips_by_zip(
    df: DataFrame, zip_xwalk: DataFrame, zip_col: str, out_col: str = "county_fips", share_col: str | None = None
) -> DataFrame:
    """Left-join the primary county for each ZIP via silver.zip_county_xwalk."""
    xw = zip_xwalk.where("is_primary").select(
        F.col("zcta5").alias("__z"), F.col("county_fips").alias(out_col), F.col("land_share").alias("__share")
    )
    out = df.withColumn("__z", zip5(F.col(zip_col))).join(F.broadcast(xw), "__z", "left").drop("__z")
    return out.withColumnRenamed("__share", share_col) if share_col else out.drop("__share")
