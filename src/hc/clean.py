"""Generic messy-data cleaner for tables we have never seen before (the kickoff dataset).

clean_dataframe(df, overrides) does, in order, and logs every step:
  1. apply overrides: rename / drop columns
  2. trim strings; null tokens ('', 'NA', 'N/A', 'NULL', '#N/A', '.', ...) -> NULL
  3. small-cell suppression tokens ('*', 'Suppressed', '<10', ...) -> NULL
     plus a <col>_is_suppressed flag (suppression is NOT missing-at-random)
  4. infer types on a sample: bigint / double / boolean / date / timestamp / string
     - identifier-like columns (id, code, fips, zip, npi, icd, ...) and values with
       leading zeros stay strings
     - '$1,234.50' and '45%' are parsed as numbers
  5. standardize FIPS / ZIP columns
  6. drop all-null columns
  7. de-duplicate (exact rows, or latest-per-primary-key)

Every cast uses try_cast / try_to_timestamp, so a bad value becomes NULL instead of failing
the job (serverless runs with ANSI mode on). The audit log counts those coerced values.

overrides (JSON in the notebook widget), all keys optional:
  {"rename": {"old": "new"}, "drop": ["col"], "types": {"col": "double"},
   "keep_string": ["col"], "primary_key": ["col"], "null_tokens": ["unk"],
   "drop_empty_columns": true}
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F

from hc import geo
from hc.io import META_COLS

NULL_TOKENS = [
    "", "na", "n/a", "n.a.", "nan", "null", "none", "nil", ".", "-", "--", "?",
    "#n/a", "#na", "#value!", "#div/0!", "#ref!", "not available", "not applicable",
    "missing", "blank", "(blank)", "-999", "-9999", "-888", "9999-12-31",
]
SUPPRESSION_TOKENS = [
    "*", "**", "***", "suppressed", "data suppressed", "<5", "< 5", "<10", "< 10",
    "<11", "< 11", "<20", "1-9", "1 - 9", "†", "‡",
]
_ID_RE = re.compile(
    r"(^|_)(id|ids|key|uuid|guid|code|codes|cd|fips|geoid|zip|zipcode|zcta|zcta5|postal|postcode|pin|pincode|npi|ccn|"
    r"tin|ein|phone|fax|tel|ssn|mrn|icd|icd9|icd10|cpt|hcpcs|ndc|drg|msdrg|loinc|snomed|rxcui|"
    r"provider_number|facility_id|account|acct|claim)(\d*)($|_)"
)
# backslash-free regexes so they are safe inside SQL string literals
_NUM_STRIP = "[,$% ]"
_INT_RE = "^[+-]?[0-9]+$"
_DEC_RE = "^[+-]?([0-9]+[.]?[0-9]*|[.][0-9]+)([eE][+-]?[0-9]+)?$"
_BOOL_TRUE = ["true", "yes", "y", "t"]
_BOOL_FALSE = ["false", "no", "n", "f"]
DATE_FORMATS = [
    "yyyy-MM-dd", "yyyy/M/d", "M/d/yyyy", "M-d-yyyy", "d-MMM-yyyy", "d MMM yyyy", "MMM d, yyyy",
    "MMMM d, yyyy", "yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd HH:mm:ss.SSS",
    "yyyy-MM-dd'T'HH:mm:ss.SSS", "M/d/yyyy H:mm", "M/d/yyyy H:mm:ss", "M/d/yyyy h:mm a",
    "M/d/yyyy h:mm:ss a", "M/d/yy",
]
VALID_TYPES = {"string", "bigint", "int", "double", "boolean", "date", "timestamp"}


def _b(c: str) -> str:
    return f"`{c}`"


def _sql_list(values) -> str:
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values)


def _ts_sql(c: str) -> str:
    parts = [f'try_to_timestamp({_b(c)}, "{fmt}")' for fmt in DATE_FORMATS]
    return f"coalesce({', '.join(parts)})"


def _num_sql(c: str) -> str:
    return f"regexp_replace({_b(c)}, '{_NUM_STRIP}', '')"


def cast_sql(c: str, t: str) -> str:
    """SQL expression that casts string column c to type t without ever throwing."""
    if t in ("bigint", "int"):
        return f"try_cast({_num_sql(c)} AS {t.upper()})"
    if t == "double":
        return f"try_cast({_num_sql(c)} AS DOUBLE)"
    if t == "boolean":
        return (
            f"CASE WHEN lower({_b(c)}) IN ({_sql_list(_BOOL_TRUE)}) THEN true "
            f"WHEN lower({_b(c)}) IN ({_sql_list(_BOOL_FALSE)}) THEN false END"
        )
    if t == "date":
        return f"to_date({_ts_sql(c)})"
    if t == "timestamp":
        return _ts_sql(c)
    return _b(c)


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def is_identifier_like(col_name: str) -> bool:
    return bool(_ID_RE.search(col_name.lower()))


def infer_types(df: DataFrame, string_cols: list[str], n_rows: int, sample_rows: int = 100_000,
                threshold: float = 0.98, keep_string=()) -> dict[str, dict]:
    """Profile string columns on a sample and pick a target type for each."""
    sample = df.select(*string_cols)
    if n_rows > sample_rows:
        sample = sample.sample(fraction=min(1.0, 1.5 * sample_rows / n_rows), seed=42).limit(sample_rows)
    stats: dict[str, dict] = {}
    for chunk in _chunks(string_cols, 25):
        exprs = []
        for c in chunk:
            exprs += [
                f"count({_b(c)}) AS `{c}__nn`",
                f"sum(CASE WHEN {_num_sql(c)} RLIKE '{_INT_RE}' THEN 1 ELSE 0 END) AS `{c}__int`",
                f"sum(CASE WHEN {_num_sql(c)} RLIKE '{_DEC_RE}' THEN 1 ELSE 0 END) AS `{c}__dec`",
                f"sum(CASE WHEN lower({_b(c)}) IN ({_sql_list(_BOOL_TRUE + _BOOL_FALSE)}) THEN 1 ELSE 0 END) AS `{c}__bool`",
                f"sum(CASE WHEN {_ts_sql(c)} IS NOT NULL THEN 1 ELSE 0 END) AS `{c}__ts`",
                f"sum(CASE WHEN date_format({_ts_sql(c)}, 'HH:mm:ss') <> '00:00:00' THEN 1 ELSE 0 END) AS `{c}__time`",
                f"sum(CASE WHEN {_b(c)} RLIKE '^0[0-9]+$' THEN 1 ELSE 0 END) AS `{c}__lead0`",
                f"sum(CASE WHEN instr({_b(c)}, '%') > 0 OR instr({_b(c)}, '$') > 0 OR instr({_b(c)}, ',') > 0 THEN 1 ELSE 0 END) AS `{c}__fmt`",
                f"max(length({_b(c)})) AS `{c}__maxlen`",
            ]
        row = sample.selectExpr(*exprs).collect()[0].asDict()
        for c in chunk:
            stats[c] = {k: (row[f"{c}__{k}"] or 0) for k in ("nn", "int", "dec", "bool", "ts", "time", "lead0", "fmt", "maxlen")}

    keep = {k.lower() for k in keep_string}
    for c, s in stats.items():
        nn = s["nn"]
        if c.lower() in keep:
            t, why = "string", "keep_string override"
        elif nn == 0:
            t, why = "string", "no non-null values in sample"
        elif is_identifier_like(c):
            t, why = "string", "identifier-like name"
        elif s["lead0"] > 0:
            t, why = "string", f"{s['lead0']} values have leading zeros"
        elif s["int"] / nn >= threshold:
            t, why = "bigint", f"{s['int'] / nn:.1%} parse as integer"
        elif s["dec"] / nn >= threshold:
            t, why = "double", f"{s['dec'] / nn:.1%} parse as number"
        elif s["bool"] / nn >= threshold:
            t, why = "boolean", f"{s['bool'] / nn:.1%} are yes/no/true/false"
        elif s["ts"] / nn >= threshold:
            t = "timestamp" if s["time"] > 0 else "date"
            why = f"{s['ts'] / nn:.1%} parse as date/time"
        else:
            t, why = "string", "mixed / free text"
        if t in ("bigint", "double") and s["fmt"] > 0:
            why += f" ({s['fmt']} had $ , or % stripped)"
        s.update(type=t, reason=why)
    return stats


def clean_dataframe(df: DataFrame, overrides: dict | None = None, sample_rows: int = 100_000):
    """Returns (clean_df, log_rows). log_rows: list of dicts for gold.dq_cleaning_log."""
    o = overrides or {}
    log: list[dict] = []

    def note(column, action, detail, n=None):
        log.append({"column_name": column, "action": action, "detail": detail, "n_affected": None if n is None else int(n)})

    try:  # make legacy-vs-new datetime parser differences return NULL rather than raise
        df.sparkSession.conf.set("spark.sql.legacy.timeParserPolicy", "CORRECTED")
    except Exception:
        pass

    n_in = df.count()
    note(None, "rows_in", f"{n_in:,} rows, {len(df.columns)} columns", n_in)

    # 1. rename / drop
    for old, new in (o.get("rename") or {}).items():
        if old in df.columns:
            df = df.withColumnRenamed(old, new)
            note(new, "renamed", f"{old} -> {new}")
    drops = [c for c in (o.get("drop") or []) if c in df.columns]
    if drops:
        df = df.drop(*drops)
        for c in drops:
            note(c, "dropped", "drop override")

    string_cols = [c for c, t in df.dtypes if t == "string" and c not in META_COLS]
    null_tokens = sorted(set(NULL_TOKENS + [t.lower() for t in (o.get("null_tokens") or [])]))

    # 2-3. count + replace null and suppression tokens
    counts = {}
    for chunk in _chunks(string_cols, 50):
        exprs = []
        for c in chunk:
            lv = f"lower(trim({_b(c)}))"
            exprs += [
                f"sum(CASE WHEN {lv} IN ({_sql_list(null_tokens)}) THEN 1 ELSE 0 END) AS `{c}__null`",
                f"sum(CASE WHEN {lv} IN ({_sql_list(SUPPRESSION_TOKENS)}) THEN 1 ELSE 0 END) AS `{c}__supp`",
                f"sum(CASE WHEN {_b(c)} <> trim({_b(c)}) THEN 1 ELSE 0 END) AS `{c}__ws`",
            ]
        if exprs:
            counts.update(df.selectExpr(*exprs).collect()[0].asDict())

    select_exprs, supp_cols = [], []
    for c in df.columns:
        if c not in string_cols:
            select_exprs.append(_b(c))
            continue
        lv = f"lower(trim({_b(c)}))"
        select_exprs.append(
            f"CASE WHEN {lv} IN ({_sql_list(null_tokens)}) OR {lv} IN ({_sql_list(SUPPRESSION_TOKENS)}) "
            f"THEN NULL ELSE trim({_b(c)}) END AS {_b(c)}"
        )
        n_null, n_supp, n_ws = counts.get(f"{c}__null") or 0, counts.get(f"{c}__supp") or 0, counts.get(f"{c}__ws") or 0
        if n_ws:
            note(c, "trimmed_whitespace", "leading/trailing spaces removed", n_ws)
        if n_null:
            note(c, "null_tokens_to_null", "placeholder strings ('NA', '', '#N/A', ...) -> NULL", n_null)
        if n_supp:
            supp_cols.append(c)
            select_exprs.append(f"coalesce({lv} IN ({_sql_list(SUPPRESSION_TOKENS)}), false) AS `{c}_is_suppressed`")
            note(c, "suppressed_to_null", f"small-cell suppression markers -> NULL; flag in {c}_is_suppressed", n_supp)
    df = df.selectExpr(*select_exprs)

    # 4. type inference + casting
    stats = infer_types(df, string_cols, n_in, sample_rows=sample_rows, keep_string=o.get("keep_string") or [])
    forced = {k: v.lower() for k, v in (o.get("types") or {}).items()}
    for c, t in forced.items():
        if t not in VALID_TYPES:
            raise ValueError(f"override type for {c} must be one of {sorted(VALID_TYPES)}, got {t}")
        if c in stats:
            stats[c].update(type=t, reason="types override")

    cast_cols = {c: s["type"] for c, s in stats.items() if s["type"] != "string"}
    if cast_cols:
        before_nn = df.selectExpr(*[f"count({_b(c)}) AS `{c}`" for c in cast_cols]).collect()[0].asDict()
        df = df.selectExpr(*[f"{cast_sql(c, cast_cols[c])} AS {_b(c)}" if c in cast_cols else _b(c) for c in df.columns])
        after_nn = df.selectExpr(*[f"count({_b(c)}) AS `{c}`" for c in cast_cols]).collect()[0].asDict()
        for c, t in cast_cols.items():
            lost = (before_nn[c] or 0) - (after_nn[c] or 0)
            note(c, f"cast_to_{t}", stats[c]["reason"], None)
            if lost:
                note(c, "unparseable_to_null", f"{lost:,} values could not be read as {t}", lost)
    for c, s in stats.items():
        if s["type"] == "string" and s["reason"] not in ("mixed / free text", "no non-null values in sample"):
            note(c, "kept_as_string", s["reason"])

    # 5. geography standardization on identifier columns we kept as strings
    for c in df.columns:
        lc = c.lower()
        if c in cast_cols or c in META_COLS:
            continue
        if "fips" in lc or lc in ("geoid", "county_geoid"):
            is_state = "state" in lc and "county" not in lc
            fn = geo.state_fips2 if is_state or (stats.get(c, {}).get("maxlen", 5) or 5) <= 2 else geo.fips5
            df = df.withColumn(c, fn(F.col(c)))
            note(c, "standardized_fips", "zero-padded to 2 (state) or 5 (county) digits")
        elif re.search(r"(^|_)(zip|zipcode|zip_code|postal_code|postcode|zcta|zcta5|pin|pincode|pin_code)($|_)", lc):
            # Decide by the values, not the name: a 'postcode' can be a US ZIP or a 6-digit Indian PIN.
            v = F.regexp_replace(F.trim(F.col(c).cast("string")), r"\.0+$", "")
            shares = df.select(
                F.avg(F.when(v.isNotNull(), v.rlike(r"^\d{3,5}(-?\d{4})?$").cast("int"))).alias("us"),
                F.avg(F.when(v.isNotNull(), F.regexp_replace(v, r"\s", "").rlike(r"^[1-9]\d{5}$").cast("int"))).alias("pin"),
            ).first()
            if (shares["pin"] or 0) >= 0.8:
                df = df.withColumn(c, geo.pin6(F.col(c)))
                note(c, "standardized_pin", f"{shares['pin']:.1%} look like 6-digit Indian PIN codes; spaces removed, invalid -> NULL")
            elif (shares["us"] or 0) >= 0.8:
                df = df.withColumn(c, geo.zip5(F.col(c)))
                note(c, "standardized_zip", "trimmed to 5-digit ZIP, leading zeros restored")
            else:
                note(c, "kept_postcode_as_is", f"mixed formats (US-like {shares['us'] or 0:.0%}, PIN-like {shares['pin'] or 0:.0%})")

    # 6. drop all-null columns
    if o.get("drop_empty_columns", True):
        data_cols = [c for c in df.columns if c not in META_COLS]
        nn = df.selectExpr(*[f"count({_b(c)}) AS `{c}`" for c in data_cols]).collect()[0].asDict()
        empty = [c for c in data_cols if not nn[c]]
        if empty:
            df = df.drop(*empty)
            for c in empty:
                note(c, "dropped_empty_column", "100% null after cleaning")

    # 7. de-duplicate
    pk = [c for c in (o.get("primary_key") or []) if c in df.columns]
    if pk:
        order = F.col("_ingested_at").desc() if "_ingested_at" in df.columns else F.lit(1)
        w = Window.partitionBy(*pk).orderBy(order)
        df = df.withColumn("__rn", F.row_number().over(w)).where("__rn = 1").drop("__rn")
        how = f"kept latest row per primary key {pk}"
    else:
        df = df.dropDuplicates([c for c in df.columns if c not in META_COLS])
        how = "removed exact duplicate rows"
    n_out = df.count()
    if n_in - n_out:
        note(None, "deduplicated", how, n_in - n_out)
    note(None, "rows_out", f"{n_out:,} rows, {len(df.columns)} columns", n_out)
    return df, log


def write_cleaning_log(spark, cfg, table_name: str, log: list[dict]) -> None:
    target = cfg.gold("dq_cleaning_log")
    spark.sql(
        f"CREATE TABLE IF NOT EXISTS {target} (table_name STRING, step INT, column_name STRING, action STRING, "
        "detail STRING, n_affected BIGINT, run_at TIMESTAMP) "
        "COMMENT 'Every automated cleaning decision, per table and column (audit trail)'"
    )
    spark.sql(f"DELETE FROM {target} WHERE table_name = '{table_name}'")
    run_at = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = [(table_name, i, r["column_name"], r["action"], r["detail"], r["n_affected"], run_at) for i, r in enumerate(log)]
    schema = "table_name string, step int, column_name string, action string, detail string, n_affected bigint, run_at timestamp"
    spark.createDataFrame(rows, schema).write.mode("append").saveAsTable(target)
