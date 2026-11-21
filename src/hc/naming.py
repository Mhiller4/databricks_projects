"""Column/table name sanitizing. Stdlib only so it can be unit-tested locally."""

from __future__ import annotations

import re

_CAMEL = re.compile(r"([a-z0-9])([A-Z])")
_NON_ALNUM = re.compile(r"[^0-9a-zA-Z]+")


def snake(name: str) -> str:
    """'% of Population Below 100% Poverty' -> 'pct_of_population_below_100_pct_poverty'
    'DataValueTypeID' -> 'data_value_type_id', '\\ufeffST' -> 'st', '_c65' -> 'c65'."""
    s = (name or "").replace("﻿", "").strip()
    s = s.replace("%", " pct ").replace("#", " num ").replace("&", " and ")
    s = _CAMEL.sub(r"\1_\2", s)
    s = _NON_ALNUM.sub("_", s).strip("_").lower()
    if not s:
        s = "col"
    if s[0].isdigit():
        s = "c_" + s
    return s


def unique_snake(names: list[str]) -> list[str]:
    """snake() every name and de-duplicate collisions with _2, _3, ..."""
    seen: dict[str, int] = {}
    out = []
    for n in names:
        base = snake(n)
        cand, i = base, 1
        while cand in seen:
            i += 1
            cand = f"{base}_{i}"
        seen[cand] = 1
        out.append(cand)
    return out


def table_name_from_file(filename: str, prefix: str = "") -> str:
    """'Patient Encounters (2023).csv' -> 'patient_encounters_2023'."""
    stem = filename.rsplit("/", 1)[-1]
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    return snake(prefix + stem)
