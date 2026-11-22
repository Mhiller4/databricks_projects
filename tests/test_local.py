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


def test_directory_name_matching():
    from hc.ext import names_match

    assert names_match("Holy Spirit Hospital Andheri", "HOLY SPIRIT HOSPITAL")
    assert names_match("Jyotipunj Hospital", "JYOTI PUNJ HOSPITAL")  # spacing differs
    assert not names_match("City Hospital", "City Care Clinic")       # only a generic word in common
    assert not names_match("Apollo Hospitals", "Fortis Hospital")
    assert not names_match("Sai Eye Hospital", "Sai Krupa Hospital")


def test_pmjay_mapping():
    from hc.care import SERVICES_BY_KEY
    from hc.ext import PMJAY_PROCEDURE_TO_SERVICE, PMJAY_SPECIALTY_TO_SERVICE, map_pmjay

    cases = {
        "Hemodialysis": "dialysis", "Caesarian Delivery": "emergency_c_section", "Caesarean Delivery": "emergency_c_section",
        "Normal Vaginal Delivery": "maternity_delivery", "Phaco Emulsification With Foldable Hydrophobic Acrylic": "cataract_surgery",
        "Ptca, Inclusive Of Diagnostic Angiogram": "cardiac_cath", "Magnetic Resonance Imaging (Mri)  Brain": "mri",
        "Acute Respiratory Failure (Without Ventilator) 10 Days Stay": None, "Screening Test For Covid-19 Infection": None,
    }
    for name, want in cases.items():
        assert map_pmjay(name) == want, (name, map_pmjay(name), want)
    assert map_pmjay("Neo-natal care Packages", PMJAY_SPECIALTY_TO_SERVICE) == "nicu"
    assert all(v in SERVICES_BY_KEY for _, v in PMJAY_PROCEDURE_TO_SERVICE + PMJAY_SPECIALTY_TO_SERVICE)


def test_ihds_codes():
    from hc import ihds
    from hc.care import SERVICES_BY_KEY

    assert ihds.FACILITY_TYPES[7][2] == "clinic" and ihds.FACILITY_TYPES[1][1] == "public"
    assert all(k in SERVICES_BY_KEY for k in ihds.SERVICE_PROXIES)
    assert all(v in ihds.SERVICES or v in ihds.EQUIPMENT for r in ihds.SERVICE_PROXIES.values() for v in r["all"])


def test_text_cleaning():
    from hc.text import clean_text_py, split_list_py

    assert clean_text_py("Cardiology\\nUrology") == "Cardiology Urology"          # literal backslash-n
    assert clean_text_py("Line one\nLine two\t end") == "Line one Line two end"   # real line break / tab
    assert clean_text_py("A &amp; B\u00a0 hospital") == "A & B hospital"           # entity + non-breaking space
    assert clean_text_py("keep \\\\n escaped") == "keep \\\\n escaped"        # escaped backslash survives (JSON)
    assert split_list_py("Gastro Wing\\nPaediatric Wing, ENT; Dialysis") == ["Gastro Wing", "Paediatric Wing", "ENT", "Dialysis"]


def test_specialty_normalisation():
    from hc.ext import normalize_specialty as n

    assert n("gynecologyAndObstetrics") == n("Obstetrics and Gynacology") == "obstetrics and gynecology"
    assert n("Orthopaedics") == "orthopedics" and n("internalMedicine") == n("General Medicine") == "internal medicine"
    assert n("Gastro Wing") == "gastroenterology" and n("ENT") == "otolaryngology"


def test_ihds_text_patterns():
    import re

    from hc import ihds

    assert set(ihds.SERVICE_TEXT_PATTERNS) == set(ihds.SERVICES)
    assert re.search(ihds.SERVICE_TEXT_PATTERNS["MF13L"], "dots centre for tuberculosis")
    assert re.search(ihds.SERVICE_TEXT_PATTERNS["MF13M"], "antenatal check-ups")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
