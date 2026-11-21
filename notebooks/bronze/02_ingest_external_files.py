# Databricks notebook source
# MAGIC %md
# MAGIC # Bronze 02 · External sources in the landing volume → `hc_bronze.ext_*`
# MAGIC
# MAGIC Every supported file at the **top level** of `/Volumes/workspace/hc_bronze/landing/` (the challenge data
# MAGIC itself comes from the Delta Share, see bronze/01). Known files get a clear table name and a description;
# MAGIC anything else lands as `ext_<file name>`. PDFs (codebooks) are not data and are skipped; their contents are
# MAGIC encoded in `src/hc/ihds.py`.
# MAGIC
# MAGIC | File | Table | What it is |
# MAGIC |---|---|---|
# MAGIC | `hospital_directory.csv` | `ext_nhp_hospital_directory` | National Health Portal hospital directory (~30k hospitals) |
# MAGIC | `Medical_Facilities_Michigan_Study.tsv` | `ext_ihds_medical_facilities` | IHDS-II (2011-12) medical facility survey, ICPSR 36151 DS6 |
# MAGIC | `count_procedure_per_state.csv` | `ext_pmjay_procedures_by_state` | PM-JAY top procedures per state, 2025 |
# MAGIC | `count_specialty_per_state.csv` | `ext_pmjay_specialties_by_state` | PM-JAY top specialties per state, 2025 |
# MAGIC | `india_districts_2011.geojson` | `ext_district_boundaries_2011` | District polygons, Census 2011 codes |
# MAGIC | `india_districts_2001.geojson` | `ext_district_boundaries_2001` | District polygons, Census 2001 codes |

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

import os

from hc.io import SUPPORTED_EXT, ext_of, ingest_file_to_bronze
from hc.naming import table_name_from_file

KNOWN = {
    "hospital_directory.csv": ("ext_nhp_hospital_directory", "National Health Portal (Govt of India) hospital directory. '0' means missing."),
    "medical_facilities_michigan_study.tsv": ("ext_ihds_medical_facilities", "IHDS-II 2011-12 medical facilities survey (ICPSR 36151 DS6). Codes decoded in src/hc/ihds.py."),
    "count_procedure_per_state.csv": ("ext_pmjay_procedures_by_state", "PM-JAY (Ayushman Bharat) top procedures per state, calendar year 2025. Top-N only."),
    "count_specialty_per_state.csv": ("ext_pmjay_specialties_by_state", "PM-JAY (Ayushman Bharat) top specialties per state, calendar year 2025. Top-N only."),
    "india_districts_2011.geojson": ("ext_district_boundaries_2011", "India district boundaries with Census 2011 codes; geometry is GeoJSON text."),
    "india_districts_2001.geojson": ("ext_district_boundaries_2001", "India district boundaries with Census 2001 codes; geometry is GeoJSON text."),
}

folder = cfg.landing
files = sorted(f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f)) and not f.startswith((".", "_")))
results = []
for f in files:
    if ext_of(f) not in SUPPORTED_EXT:
        print(f"skip (not data): {f}")
        continue
    table, comment = KNOWN.get(f.lower(), (table_name_from_file(f, "ext_"), f"External file {f}"))
    n = ingest_file_to_bronze(spark, cfg, os.path.join(folder, f), table, comment=f"{comment} Source file: {f}.")
    results.append((f, table, n))
    print(f"{f:<45} -> {table} ({n:,} rows)")

display(spark.createDataFrame(results, "source_file string, bronze_table string, rows bigint"))
