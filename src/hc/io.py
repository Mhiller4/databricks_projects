"""Download, read-any-file, and write-to-bronze helpers.

Bronze rule: land data as close to the original as possible. We only:
  * sanitize column names (Delta needs it) and record the original -> new mapping,
  * read delimited text as ALL STRINGS (type inference happens in silver, where we log it),
  * add lineage columns _source_file and _ingested_at.
"""

from __future__ import annotations

import os
import shutil
import ssl
import subprocess
import time
import urllib.request
import zipfile

from hc.naming import unique_snake

META_COLS = ("_source_file", "_ingested_at")
TEXT_EXT = {"csv", "txt", "tsv", "tab", "psv", "dat"}
JSON_EXT = {"json", "jsonl", "ndjson"}
EXCEL_EXT = {"xlsx", "xlsm", "xls"}
SAS_EXT = {"xpt", "sas7bdat"}  # NHANES ships .XPT
STATA_EXT = {"dta"}
PARQUET_EXT = {"parquet"}
SUPPORTED_EXT = TEXT_EXT | JSON_EXT | EXCEL_EXT | SAS_EXT | STATA_EXT | PARQUET_EXT


def ext_of(path: str) -> str:
    return path.rsplit(".", 1)[-1].lower() if "." in path.rsplit("/", 1)[-1] else ""


# --------------------------------------------------------------------------------------
# Downloads
# --------------------------------------------------------------------------------------
def _ssl_context():
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _fetch_urllib(url: str, tmp: str, timeout: int) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "hc-datathon-fetch/1.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp, open(tmp, "wb") as fh:
        shutil.copyfileobj(resp, fh, length=1 << 20)


def _fetch_curl(url: str, tmp: str, timeout: int) -> None:
    # Fallback for python.org macOS builds that ship without CA certs (curl uses the system store).
    subprocess.run(
        ["curl", "-fsSL", "--retry", "2", "--max-time", str(timeout), "-A", "hc-datathon-fetch/1.0", "-o", tmp, url],
        check=True,
    )


def download(url: str, dest_path: str, timeout: int = 600, retries: int = 3) -> int:
    """Stream url -> dest_path (works for /Volumes paths). Returns bytes written."""
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    tmp = dest_path + ".part"
    last: Exception | None = None
    use_curl = False
    for attempt in range(1, retries + 1):
        try:
            (_fetch_curl if use_curl else _fetch_urllib)(url, tmp, timeout)
            shutil.move(tmp, dest_path)
            return os.path.getsize(dest_path)
        except Exception as exc:  # network, HTTP, TLS, or egress-blocked
            last = exc
            if os.path.exists(tmp):
                os.remove(tmp)
            if "CERTIFICATE_VERIFY_FAILED" in str(exc) and shutil.which("curl"):
                use_curl = True
                continue
            time.sleep(2 * attempt)
    raise RuntimeError(f"Download failed after {retries} tries: {url} -> {last}")


def unzip_all(folder: str) -> list[str]:
    """Extract every .zip under folder into a sibling folder named after the zip."""
    extracted = []
    for root, _, files in os.walk(folder):
        for f in files:
            if f.lower().endswith(".zip"):
                zpath = os.path.join(root, f)
                out = os.path.join(root, f[:-4])
                if not os.path.exists(out):
                    with zipfile.ZipFile(zpath) as z:
                        z.extractall(out)
                    extracted.append(out)
    return extracted


def list_data_files(folder: str) -> list[str]:
    """Every supported data file under folder (recursive), skipping hidden/partial files."""
    found = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith((".", "_"))]
        for f in sorted(files):
            if f.startswith((".", "_")) or f.endswith(".part"):
                continue
            if ext_of(f) in SUPPORTED_EXT:
                found.append(os.path.join(root, f))
    return sorted(found)


def sniff_delimiter(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        head = fh.readline()
    counts = {d: head.count(d) for d in [",", "|", "\t", ";"]}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


# --------------------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------------------
def _pandas_to_spark(spark, pdf):
    """All-string Spark DataFrame from pandas (keeps NaN as null)."""
    from pyspark.sql import types as T

    pdf = pdf.astype(object).where(pdf.notna(), None)
    rows = [[None if v is None else str(v) for v in r] for r in pdf.itertuples(index=False, name=None)]
    schema = T.StructType([T.StructField(str(c), T.StringType(), True) for c in pdf.columns])
    return spark.createDataFrame(rows, schema)


def read_any(spark, path: str, delimiter: str | None = None, sheet: str | int | None = None):
    """Read one file (or a folder of same-format part files) as a Spark DataFrame.

    Returns (df, uses_file_metadata). Text formats come back all-string.
    """
    ext = ext_of(path)
    if ext in TEXT_EXT:
        delim = delimiter or ("\t" if ext in {"tsv", "tab"} else sniff_delimiter(path))
        df = (
            spark.read.option("header", True)
            .option("sep", delim)
            .option("inferSchema", False)
            .option("multiLine", True)
            .option("quote", '"')
            .option("escape", '"')
            .option("encoding", "UTF-8")
            .option("mode", "PERMISSIVE")
            .csv(path)
        )
        return df, True
    if ext in JSON_EXT:
        multiline = False
        if ext == "json":
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                multiline = fh.read(1024).lstrip().startswith("[")
        return spark.read.option("multiLine", multiline).json(path), True
    if ext in PARQUET_EXT:
        return spark.read.parquet(path), True

    import pandas as pd

    if ext in EXCEL_EXT:
        try:
            pdf = pd.read_excel(path, sheet_name=sheet if sheet is not None else 0, dtype=str)
        except ImportError as exc:
            raise ImportError("Excel needs openpyxl: run `%pip install openpyxl` first") from exc
        return _pandas_to_spark(spark, pdf), False
    if ext in SAS_EXT:
        pdf = pd.read_sas(path, format="xport" if ext == "xpt" else "sas7bdat", encoding="latin-1")
        return _pandas_to_spark(spark, pdf), False
    if ext in STATA_EXT:
        return _pandas_to_spark(spark, pd.read_stata(path, convert_categoricals=False)), False
    raise ValueError(f"Unsupported file type '.{ext}' for {path}")


def excel_sheets(path: str) -> list[str]:
    import pandas as pd

    return list(pd.ExcelFile(path).sheet_names)


# --------------------------------------------------------------------------------------
# Writing bronze
# --------------------------------------------------------------------------------------
def to_bronze_df(df, source_path: str, uses_file_metadata: bool):
    """Sanitize column names + add lineage. Returns (df, [(original, sanitized), ...])."""
    from pyspark.sql import functions as F

    original = df.columns
    new = unique_snake(original)
    df = df.toDF(*new)
    src = F.col("_metadata.file_path") if uses_file_metadata else F.lit(source_path)
    df = df.withColumn("_source_file", src).withColumn("_ingested_at", F.current_timestamp())
    return df, list(zip(original, new))


def write_table(df, fqn: str, mode: str = "overwrite") -> None:
    writer = df.write.mode(mode)
    writer = writer.option("overwriteSchema", "true") if mode == "overwrite" else writer.option("mergeSchema", "true")
    writer.saveAsTable(fqn)


def record_column_map(spark, cfg, table: str, mapping: list[tuple[str, str]], source_path: str) -> None:
    """Keep original column names next to sanitized ones (bronze._column_map)."""
    from pyspark.sql import functions as F

    target = cfg.bronze("_column_map")
    spark.sql(
        f"CREATE TABLE IF NOT EXISTS {target} (table_name STRING, ordinal INT, original_name STRING, "
        "column_name STRING, source_file STRING, recorded_at TIMESTAMP) "
        "COMMENT 'Original source column names for every bronze table'"
    )
    spark.sql(f"DELETE FROM {target} WHERE table_name = '{table}'")
    rows = [(table, i, o, n, source_path) for i, (o, n) in enumerate(mapping)]
    (
        spark.createDataFrame(rows, "table_name string, ordinal int, original_name string, column_name string, source_file string")
        .withColumn("recorded_at", F.current_timestamp())
        .write.mode("append")
        .saveAsTable(target)
    )


def ingest_file_to_bronze(spark, cfg, path: str, table: str, comment: str = "", delimiter=None, sheet=None) -> int:
    """Read path -> bronze.<table>. Returns row count."""
    df, uses_meta = read_any(spark, path, delimiter=delimiter, sheet=sheet)
    df, mapping = to_bronze_df(df, path, uses_meta)
    fqn = cfg.bronze(table)
    write_table(df, fqn)
    if comment:
        safe = comment.replace("'", "\\'")
        spark.sql(f"COMMENT ON TABLE {fqn} IS '{safe}'")
    record_column_map(spark, cfg, table, mapping, path)
    return spark.table(fqn).count()
