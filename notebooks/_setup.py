# Databricks notebook source
# MAGIC %md
# MAGIC # Shared setup (`%run ../_setup`)
# MAGIC
# MAGIC Puts `src/` on the path, (re)loads the `hc` helpers, and builds `cfg` from widgets / job parameters.
# MAGIC Works both from a bundle deploy and from a Git folder, because it walks up to find `databricks.yml`.

# COMMAND ----------

import importlib
import os
import sys


def _repo_root(start=None):
    p = os.path.abspath(start or os.getcwd())
    while p != os.path.dirname(p):
        if os.path.exists(os.path.join(p, "databricks.yml")):
            return p
        p = os.path.dirname(p)
    raise RuntimeError(f"Could not find databricks.yml above {os.getcwd()}")


REPO_ROOT = _repo_root()
_SRC = os.path.join(REPO_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import hc  # noqa: E402
import hc.config, hc.naming, hc.sources, hc.io, hc.geo, hc.clean, hc.profile  # noqa: E401,E402

for _m in (hc.config, hc.naming, hc.sources, hc.io, hc.geo, hc.clean, hc.profile):
    importlib.reload(_m)  # pick up edits to src/ without restarting Python

from pyspark.sql import functions as F  # noqa: E402

from hc.config import get_config, q, widget  # noqa: E402

cfg = get_config(dbutils)  # noqa: F821  (dbutils is provided by Databricks)
cfg.show()
