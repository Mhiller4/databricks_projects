"""Local tests for the pyspark-free helpers.  Run:  python3 -m pytest tests/  (or python3 tests/test_local.py)"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from hc.naming import snake, table_name_from_file, unique_snake  # noqa: E402


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


def test_identifier_regex():
    # imported lazily: clean.py needs pyspark; replicate just the regex check if pyspark is missing
    try:
        from hc.clean import is_identifier_like
    except ImportError:
        return
    for c in ["facility_id", "pin_code", "postcode", "pincode", "provider_number"]:
        assert is_identifier_like(c), c
    for c in ["age", "los_days", "hpsa_score", "paid_amount", "valid_flag"]:
        assert not is_identifier_like(c), c


def test_care_service_patterns():
    import re

    from hc.care import QUANTITY_PATTERN, SERVICES_BY_KEY, THIRD_PARTY_PATTERN

    cases = {
        "dialysis": (["20-bed Dialysis Unit with 10 machines", "Haemodialysis available 24x7", "CAPD program"],
                     ["Nephrology OPD on Mondays", "dialyzer reuse policy"]),
        "emergency_c_section": (["Emergency caesarean sections performed round the clock", "LSCS and normal deliveries",
                                 "Handles high-risk pregnancies", "C-section"], ["Section of general surgery"]),
        "nicu": (["Level III NICU with 12 incubators", "Neonatal intensive care unit", "SNCU"], ["Neonatal jaundice clinic"]),
        "icu": (["10-bed ICU", "Critical care with ventilators"], ["Picnic area for families"]),
        "trauma_care": (["Level 1 trauma centre", "Accident & Emergency services", "Casualty"], ["Trauma counselling" ]),
        "emergency_department": (["24x7 emergency", "24 hours emergency services", "Emergency department"], ["Emergency contact number"]),
        "burn_care": (["Burns unit with 8 beds", "burn injuries treated"], ["Fat burning program"]),
        "cardiac_surgery": (["CABG and valve replacement", "Open-heart surgery", "Cardiothoracic surgery"], ["Cardiology OPD"]),
        "cardiac_cath": (["Cath lab with primary angioplasty", "PTCA"], ["Cathedral road"]),
        "mri": (["1.5 Tesla MRI", "Magnetic resonance imaging"], ["Primary care", "Mrinal Sen ward"]),
        "ct_scan": (["128 slice CT", "CT scan available", "HRCT chest"], ["Act on patient rights", "OCT imaging"]),
        "blood_bank": (["Licensed blood bank", "Blood transfusion services"], ["Blood pressure monitoring"]),
        "chemotherapy": (["Chemotherapy day care", "Medical oncology"], ["Oncology awareness camp"]),
        "radiotherapy": (["Elekta linear accelerator", "Brachytherapy suite"], ["Radiology department"]),
        "cataract_surgery": (["Phacoemulsification cataract surgery"], ["Retina clinic"]),
    }
    for k, (pos, neg) in cases.items():
        rx = re.compile(SERVICES_BY_KEY[k].pattern)
        for t in pos:
            assert rx.search(t.lower()), (k, "should match", t)
        for t in neg:
            assert not rx.search(t.lower()), (k, "should NOT match", t)
    assert re.search(THIRD_PARTY_PATTERN, "madras medical mission is listed as a referral hospital outside the state.")
    assert not re.search(THIRD_PARTY_PATTERN, "20-bed dialysis unit with 10 machines")
    assert re.search(QUANTITY_PATTERN, "20-bed dialysis unit with 10 machines")
    assert re.search(QUANTITY_PATTERN, "level iii nicu with 12 incubators")


def test_care_scoring_helpers():
    from hc.care import confidence, key, match_service, noisy_or

    assert abs(noisy_or([0.6, 0.5]) - 0.8) < 1e-9
    assert confidence(0.8, 0.9, 1.0) == "High"
    assert confidence(0.8, 0.6, 1.0) == "Medium"
    assert confidence(0.15, 1.0, 1.0) == "Low"
    assert confidence(0.97, 0.6, 0.4) == "Low"  # eye hospital claiming dialysis
    assert key("Tamil Nadu") == key("TAMILNADU") == "TAMILNADU"
    assert match_service("Dialysis").service.key == "dialysis"
    assert match_service("kidney machine").service.key == "dialysis"
    assert match_service("c section").service.key == "emergency_c_section"
    assert match_service("NICU").service.key == "nicu"
    assert match_service("quantum healing") is None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
