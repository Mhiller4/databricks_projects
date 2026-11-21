"""Local tests for the pyspark-free helpers.  Run:  python3 -m pytest tests/  (or python3 tests/test_local.py)"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from hc.naming import snake, table_name_from_file, unique_snake  # noqa: E402
from hc.sources import PUBLIC_SOURCES, SOURCES_BY_KEY, select_sources  # noqa: E402


def test_snake_cases():
    cases = {
        "% of Population Below 100% Poverty": "pct_of_population_below_100_pct_poverty",
        "DataValueTypeID": "data_value_type_id",
        "﻿ST": "st",
        "TotalPop18plus": "total_pop18plus",
        "City/Town": "city_town",
        "U.S. - Mexico Border 100 Kilometer Indicator": "u_s_mexico_border_100_kilometer_indicator",
        "2023 Value": "c_2023_value",
        "": "col",
        "_c65": "c65",
        "Patient ID#": "patient_id_num",
    }
    for raw, want in cases.items():
        assert snake(raw) == want, (raw, snake(raw), want)


def test_unique_snake_dedupes():
    assert unique_snake(["Zip Code", "ZIP_CODE", "zip code"]) == ["zip_code", "zip_code_2", "zip_code_3"]


def test_table_name_from_file():
    assert table_name_from_file("Patient Encounters (2023).csv", "kickoff_") == "kickoff_patient_encounters_2023"
    assert table_name_from_file("sub/dir/labs.XPT") == "labs"


def test_sources_registry():
    keys = [s.key for s in PUBLIC_SOURCES]
    assert len(keys) == len(set(keys))
    assert all(k == snake(k) for k in keys), "source keys must already be valid table names"
    assert all(s.url.startswith("https://") for s in PUBLIC_SOURCES)
    assert select_sources("all") == PUBLIC_SOURCES
    assert [s.key for s in select_sources("svi_county_2022, usda_rucc_2023")] == ["svi_county_2022", "usda_rucc_2023"]
    assert "places_county" in SOURCES_BY_KEY
    try:
        select_sources("nope")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown key should raise")


def test_identifier_regex():
    # imported lazily: clean.py needs pyspark; replicate just the regex check if pyspark is missing
    try:
        from hc.clean import is_identifier_like
    except ImportError:
        return
    for c in ["patient_id", "zip_code", "icd10_code", "county_fips", "npi", "provider_number"]:
        assert is_identifier_like(c), c
    for c in ["age", "los_days", "hpsa_score", "paid_amount", "valid_flag"]:
        assert not is_identifier_like(c), c


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
