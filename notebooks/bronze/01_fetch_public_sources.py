# Databricks notebook source
# MAGIC %md
# MAGIC # Bronze 01 · Fetch public sources into the landing volume
# MAGIC
# MAGIC Downloads every source in `src/hc/sources.py` to `/Volumes/<catalog>/hc_bronze/landing/public/<key>/`.
# MAGIC Files that already exist are skipped unless `force = true`.
# MAGIC
# MAGIC **If downloads are blocked** (Free Edition can restrict outbound internet), run this on a laptop instead:
# MAGIC ```
# MAGIC python scripts/fetch_public_sources.py --upload --profile <your-profile>
# MAGIC ```
# MAGIC Then re-run this notebook. It will find the uploaded files and pass.

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

from hc.io import download
from hc.sources import select_sources

selection = widget(dbutils, "sources", "all", "sources (comma list or all)")
force = widget(dbutils, "force", "false", "re-download (true/false)").lower() == "true"

results, missing = [], []
for src in select_sources(selection):
    dest = f"{cfg.public_landing}/{src.key}/{src.filename}"
    if os.path.exists(dest) and not force:
        results.append((src.key, "already present", round(os.path.getsize(dest) / 1e6, 1), dest))
        continue
    try:
        size = download(src.url, dest)
        results.append((src.key, "downloaded", round(size / 1e6, 1), dest))
    except Exception as exc:
        status = "FAILED (kept existing file)" if os.path.exists(dest) else "FAILED"
        results.append((src.key, f"{status}: {str(exc)[:150]}", None, dest))
        if not os.path.exists(dest):
            missing.append(src.key)

display(spark.createDataFrame(results, "source string, status string, size_mb double, path string"))

# COMMAND ----------

if missing:
    raise RuntimeError(
        f"No file for {missing}. Outbound internet is probably blocked here. On a laptop run:\n"
        f"  python scripts/fetch_public_sources.py --only {','.join(missing)} --upload --profile <profile>\n"
        "then re-run this notebook."
    )
print("All public source files are in the landing volume.")
