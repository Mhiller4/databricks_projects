"""Load the gold Parquet exports (notebooks/gold/25_export_serving) into an in-memory DuckDB.

Either download them first:
    databricks fs cp -r --overwrite dbfs:/Volumes/workspace/hc_gold/serving backend/data --profile <p>
or set nothing: when the folder has no Parquet, Store pulls the UC volume itself via the
Databricks Files API (the Databricks Apps startup path, design 3.5). Volume path comes from
CARE_FINDER_VOLUME (default /Volumes/workspace/hc_gold/serving); set it to '' to disable.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import duckdb

DATA_DIR = Path(os.environ.get("CARE_FINDER_DATA", Path(__file__).resolve().parents[1] / "data"))
TABLES = ("care_finder_index", "location_lookup", "service_catalog", "facilities")


def _download_volume(volume: str, dest: Path) -> None:
    """Pull the serving exports from the UC volume into dest (Files API, ambient credentials;
    inside a Databricks App these are the app service principal's)."""
    from databricks.sdk import WorkspaceClient  # optional dependency outside the app

    w = WorkspaceClient()

    def walk(path: str, into: Path) -> None:
        for entry in w.files.list_directory_contents(path):
            if not entry.path:
                continue
            if entry.is_directory:
                walk(entry.path, into / (entry.name or entry.path.rstrip("/").rsplit("/", 1)[-1]))
            elif entry.name and (entry.name.endswith(".parquet") or entry.name.endswith(".json")):
                target = into / entry.name
                target.parent.mkdir(parents=True, exist_ok=True)
                w.files.download_to(entry.path, str(target), overwrite=True)

    walk(volume, dest)


class Store:
    """One read-only DuckDB connection; each request uses its own cursor (thread-safe)."""

    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = Path(data_dir)
        missing = [t for t in TABLES if not list((self.data_dir / t).glob("*.parquet"))]
        if missing:  # app startup path: fetch the volume once, then reuse what landed here (design 3.5)
            volume = os.environ.get("CARE_FINDER_VOLUME", "/Volumes/workspace/hc_gold/serving")
            if volume:
                _download_volume(volume, self.data_dir)
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
