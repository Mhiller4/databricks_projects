"""Data-quality profiling -> gold.dq_profile (per column) and gold.dq_table_summary (per table).

This is the "how messy was it?" evidence for the Exploration score and the video:
profile bronze, profile silver, and show the before/after.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pyspark.sql import DataFrame

from hc.io import META_COLS

PROFILE_SCHEMA = (
    "layer string, table_name string, ordinal int, column_name string, data_type string, n_rows bigint, "
    "n_null bigint, null_pct double, n_distinct_approx bigint, min_value string, max_value string, "
    "mean double, stddev double, p50 double, top_values string, profiled_at timestamp"
)
SUMMARY_SCHEMA = (
    "layer string, table_name string, n_rows bigint, n_columns int, pct_cells_null double, "
    "n_columns_mostly_null int, n_duplicate_rows bigint, profiled_at timestamp"
)
_NUMERIC = ("tinyint", "smallint", "int", "bigint", "float", "double", "decimal")


def _b(c):
    return f"`{c}`"


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def profile_df(df: DataFrame, layer: str, table_name: str, top_k: int = 5, top_max_distinct: int = 50,
               top_max_cols: int = 40, dup_check_max_rows: int = 5_000_000):
    """Return (column_rows, summary_row) as python tuples matching the schemas above."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cols = [(c, t) for c, t in df.dtypes if c not in META_COLS]
    n = df.count()
    stats: dict[str, dict] = {}
    for chunk in _chunks(cols, 30):
        exprs = []
        for c, t in chunk:
            exprs += [f"count({_b(c)}) AS `{c}__nn`", f"approx_count_distinct({_b(c)}) AS `{c}__nd`"]
            if not t.startswith(("struct", "array", "map", "binary")):
                exprs += [f"CAST(min({_b(c)}) AS STRING) AS `{c}__min`", f"CAST(max({_b(c)}) AS STRING) AS `{c}__max`"]
            if t.startswith(_NUMERIC):
                exprs += [
                    f"avg({_b(c)}) AS `{c}__mean`",
                    f"stddev({_b(c)}) AS `{c}__sd`",
                    f"percentile_approx({_b(c)}, 0.5) AS `{c}__p50`",
                ]
        row = df.selectExpr(*exprs).collect()[0].asDict() if exprs else {}
        for c, _ in chunk:
            stats[c] = {k: row.get(f"{c}__{k}") for k in ("nn", "nd", "min", "max", "mean", "sd", "p50")}

    top_done = 0
    rows = []
    for i, (c, t) in enumerate(cols):
        s = stats[c]
        nn = s["nn"] or 0
        top = None
        if t == "string" and top_done < top_max_cols and 0 < (s["nd"] or 0) <= top_max_distinct:
            vals = df.groupBy(c).count().where(f"{_b(c)} IS NOT NULL").orderBy("count", ascending=False).limit(top_k).collect()
            top = "; ".join(f"{r[c]} ({r['count']:,})" for r in vals)
            top_done += 1
        mean, sd, p50 = (float(s[k]) if s[k] is not None else None for k in ("mean", "sd", "p50"))
        rows.append((
            layer, table_name, i, c, t, n, n - nn, (n - nn) / n if n else None, s["nd"],
            (s["min"] or "")[:200] or None, (s["max"] or "")[:200] or None, mean, sd, p50, top, now,
        ))

    n_dups = None
    if 0 < n <= dup_check_max_rows and cols:
        n_dups = n - df.select(*[c for c, _ in cols]).distinct().count()
    total_cells = n * len(cols)
    null_cells = sum(r[6] for r in rows)
    summary = (
        layer, table_name, n, len(cols), null_cells / total_cells if total_cells else None,
        sum(1 for r in rows if (r[7] or 0) >= 0.5), n_dups, now,
    )
    return rows, summary


def write_profile(spark, cfg, layer: str, table_name: str, rows, summary) -> None:
    prof, summ = cfg.gold("dq_profile"), cfg.gold("dq_table_summary")
    spark.sql(f"CREATE TABLE IF NOT EXISTS {prof} ({PROFILE_SCHEMA}) COMMENT 'Column-level data-quality profile per table and layer'")
    spark.sql(f"CREATE TABLE IF NOT EXISTS {summ} ({SUMMARY_SCHEMA}) COMMENT 'Table-level data-quality summary per layer'")
    for t in (prof, summ):
        spark.sql(f"DELETE FROM {t} WHERE layer = '{layer}' AND table_name = '{table_name}'")
    if rows:
        spark.createDataFrame(rows, PROFILE_SCHEMA).write.mode("append").saveAsTable(prof)
    spark.createDataFrame([summary], SUMMARY_SCHEMA).write.mode("append").saveAsTable(summ)
