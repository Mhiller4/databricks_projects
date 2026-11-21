"""One config object for every notebook.

Values come from notebook widgets, which jobs fill from job parameters (see resources/*.yml).
Run interactively and the defaults below apply, which match the Free Edition layout:
    workspace.hc_bronze / hc_silver / hc_gold, volume workspace.hc_bronze.landing
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULTS = {
    "catalog": "workspace",
    "bronze_schema": "hc_bronze",
    "silver_schema": "hc_silver",
    "gold_schema": "hc_gold",
    "landing_volume": "landing",
}


def q(*parts: str) -> str:
    """Backtick-quote a dotted identifier: q('a','b-c') -> `a`.`b-c`."""
    return ".".join(f"`{p.replace('`', '``')}`" for p in parts)


@dataclass(frozen=True)
class Config:
    catalog: str
    bronze_schema: str
    silver_schema: str
    gold_schema: str
    landing_volume: str

    @property
    def landing(self) -> str:
        return f"/Volumes/{self.catalog}/{self.bronze_schema}/{self.landing_volume}"

    @property
    def kickoff_landing(self) -> str:
        return f"{self.landing}/kickoff"

    def bronze(self, table: str) -> str:
        return q(self.catalog, self.bronze_schema, table)

    def silver(self, table: str) -> str:
        return q(self.catalog, self.silver_schema, table)

    def gold(self, table: str) -> str:
        return q(self.catalog, self.gold_schema, table)

    def schema(self, layer: str) -> str:
        return q(self.catalog, getattr(self, f"{layer}_schema"))

    def show(self) -> None:
        print(
            f"catalog={self.catalog}  bronze={self.bronze_schema}  silver={self.silver_schema}  "
            f"gold={self.gold_schema}\nlanding volume={self.landing}"
        )


def get_config(dbutils) -> Config:
    """Create the standard widgets (no-op if they exist) and read them."""
    for name, default in DEFAULTS.items():
        try:
            dbutils.widgets.text(name, default)
        except Exception:
            pass
    values = {}
    for name, default in DEFAULTS.items():
        try:
            values[name] = (dbutils.widgets.get(name) or default).strip()
        except Exception:
            values[name] = default
    return Config(**values)


def widget(dbutils, name: str, default: str = "", label: str | None = None) -> str:
    """Notebook-specific extra widget."""
    try:
        dbutils.widgets.text(name, default, label or name)
    except Exception:
        pass
    try:
        return (dbutils.widgets.get(name) or "").strip()
    except Exception:
        return default
