# Databricks notebook source
# MAGIC %md
# MAGIC # Bronze 03 · Kickoff (organizer) data → bronze tables
# MAGIC
# MAGIC **Saturday morning:** put whatever the organizers give us in
# MAGIC `/Volumes/<catalog>/hc_bronze/landing/kickoff/`
# MAGIC (Catalog Explorer → volume → *Upload to this volume*, or `databricks fs cp -r ./data dbfs:/Volumes/...`).
# MAGIC
# MAGIC This notebook then:
# MAGIC * unzips any `.zip`
# MAGIC * reads every CSV / TSV / pipe / JSON / Parquet / Excel (every sheet) / SAS `.xpt` `.sas7bdat` / Stata `.dta`
# MAGIC * writes one bronze table per file (or per sheet): `hc_bronze.kickoff_<file_name>`
# MAGIC
# MAGIC **If the data arrives as a table** (Delta Sharing, Marketplace, or a pre-loaded catalog), set
# MAGIC `source_tables` to a comma list of full table names and they are copied into bronze instead.

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

from hc.io import EXCEL_EXT, excel_sheets, ext_of, ingest_file_to_bronze, list_data_files, to_bronze_df, unzip_all, write_table
from hc.naming import snake, table_name_from_file

subfolder = widget(dbutils, "subfolder", "kickoff", "landing subfolder")
prefix = widget(dbutils, "table_prefix", "kickoff_", "bronze table prefix")
source_tables = widget(dbutils, "source_tables", "", "OR: existing tables to copy (comma list)")
folder = f"{cfg.landing}/{subfolder}"
results = []

# COMMAND ----------

# Path A: files in the landing volume
if not source_tables:
    os.makedirs(folder, exist_ok=True)
    for out in unzip_all(folder):
        print("unzipped ->", out)
    files = list_data_files(folder)
    if not files:
        raise RuntimeError(f"No data files found in {folder}. Upload the kickoff data there first.")
    for path in files:
        rel = os.path.relpath(path, folder)
        base_table = table_name_from_file(rel.replace("/", "_"), prefix)
        if ext_of(path) in EXCEL_EXT:
            try:
                sheets = excel_sheets(path)
            except ImportError:
                raise ImportError("Excel files need openpyxl: add a cell `%pip install openpyxl` at the top and re-run")
            for sheet in sheets:
                table = base_table if len(sheets) == 1 else f"{base_table}__{snake(sheet)}"
                n = ingest_file_to_bronze(spark, cfg, path, table, comment=f"Kickoff file {rel}, sheet {sheet}", sheet=sheet)
                results.append((rel, sheet, table, n))
        else:
            n = ingest_file_to_bronze(spark, cfg, path, base_table, comment=f"Kickoff file {rel}")
            results.append((rel, None, base_table, n))
        print(f"{rel:<60} -> {results[-1][2]} ({results[-1][3]:,} rows)")

# COMMAND ----------

# Path B: data already lives in a table somewhere
if source_tables:
    for full in [t.strip() for t in source_tables.split(",") if t.strip()]:
        table = snake(prefix + full.split(".")[-1].strip("`"))
        df, mapping = to_bronze_df(spark.table(full), full, uses_file_metadata=False)
        write_table(df, cfg.bronze(table))
        hc.io.record_column_map(spark, cfg, table, mapping, full)
        results.append((full, None, table, spark.table(cfg.bronze(table)).count()))

# COMMAND ----------

display(spark.createDataFrame(results, "source string, sheet string, bronze_table string, rows bigint"))
print("Next: silver/10_profile_tables (layer=bronze) to see how messy it is, then silver/11_clean_kickoff_tables.")
