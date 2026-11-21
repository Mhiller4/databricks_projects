"""Load the gold Parquet exports (notebooks/gold/25_export_serving) into an in-memory DuckDB.

Download them first:
    databricks fs cp -r --overwrite dbfs:/Volumes/workspace/hc_gold/serving backend/data --profile <p>
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import duckdb

DATA_DIR = Path(os.environ.get("CARE_FINDER_DATA", Path(__file__).resolve().parents[1] / "data"))
TABLES = ("care_finder_index", "location_lookup", "service_catalog", "facilities")


class Store:
    """One read-only DuckDB connection; each request uses its own cursor (thread-safe)."""

    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = Path(data_dir)
        missing = [t for t in TABLES if not list((self.data_dir / t).glob("*.parquet"))]
        if missing:
            raise FileNotFoundError(
                f"Missing Parquet exports in {self.data_dir}: {missing}. Run the export_serving task, then "
                "`databricks fs cp -r --overwrite dbfs:/Volumes/workspace/hc_gold/serving backend/data --profile <p>`."
            )
        self.con = duckdb.connect(":memory:")
        for t in TABLES:
            path = (self.data_dir / t / "*.parquet").as_posix()
            self.con.execute(f"CREATE TABLE {t} AS SELECT * FROM read_parquet('{path}')")
        self.funnel_base = json.loads((self.data_dir / "funnel_base.json").read_text())
        self._lock = threading.Lock()

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        with self._lock:
            cur = self.con.cursor()
        try:
            cur.execute(sql, params or [])
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            cur.close()


_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store
