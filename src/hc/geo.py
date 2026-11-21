"""Geography helpers for the India facility data."""

from __future__ import annotations

from pyspark.sql import Column
from pyspark.sql import functions as F


def pin6(col: Column) -> Column:
    """Indian PIN code: '110 002', '110002.0' -> '110002'; anything not 6 digits starting 1-9 -> NULL."""
    c = F.regexp_replace(F.regexp_replace(F.trim(col.cast("string")), r"\.0+$", ""), r"\s", "")
    return F.when(c.rlike(r"^[1-9][0-9]{5}$"), c)


def haversine_km(lat1: Column, lon1: Column, lat2: Column, lon2: Column) -> Column:
    """Great-circle distance in km. SQL twin is in gold/23 (recommend_facilities)."""
    a = F.pow(F.sin(F.radians(lat2 - lat1) / 2), 2) + F.cos(F.radians(lat1)) * F.cos(F.radians(lat2)) * F.pow(
        F.sin(F.radians(lon2 - lon1) / 2), 2
    )
    return F.lit(2 * 6371.0) * F.asin(F.sqrt(a))
