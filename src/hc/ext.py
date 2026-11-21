"""External sources: matching rules and mappings (National Health Portal directory, PM-JAY). No Spark imports.

Matching our facilities to the National Health Portal hospital directory:
    same 6-digit PIN  AND  name-token overlap >= MATCH_MIN_OVERLAP
    (+ within MATCH_MAX_KM when both sides have real coordinates; a city-centre point is not "real")
Overlap = |shared tokens| / |tokens of the shorter name|, after dropping generic words (hospital, clinic,
pvt, ltd ...), so "Holy Spirit Hospital, Andheri" matches "HOLY SPIRIT HOSPITAL".
"""

from __future__ import annotations

import re

NAME_STOPWORDS = frozenset(
    """HOSPITAL HOSPITALS HOSP CLINIC CLINICS CENTRE CENTER CENTRES MEDICAL MEDICALS NURSING HOME HOMES
    AND THE OF PVT PRIVATE LTD LIMITED LLP MULTI MULTISPECIALITY MULTISPECIALTY SPECIALITY SPECIALTY SUPER
    SUPERSPECIALITY CARE HEALTH HEALTHCARE DR DRS RESEARCH INSTITUTE INSTITUTES SCIENCES SCIENCE TRUST
    MEMORIAL CHARITABLE POLYCLINIC DISPENSARY SERVICES""".split()
)
# Words too common to identify a facility on their own: a match needs at least one shared token outside this set
WEAK_TOKENS = frozenset(
    """CITY NEW LIFE SHRI SHREE SRI SREE SAI JAI MAA MATA GOOD GENERAL GOVT GOVERNMENT DISTRICT CIVIL STATE
    COMMUNITY PRIMARY RURAL URBAN WOMEN WOMENS CHILDREN CHILD CHILDRENS MOTHER MATERNITY EYE EYES DENTAL KIDNEY
    HEART BONE JOINT SKIN NAGAR ROAD MAIN NATIONAL INDIA INDIAN CENTRAL WEST EAST NORTH SOUTH GROUP UNIT""".split()
)
MATCH_MIN_OVERLAP = 0.6
MATCH_MAX_KM = 5.0
CENTROID_REPEAT = 5          # a coordinate used by more than this many directory rows is a geocoded city centre

DIRECTORY_NAME = "India's National Health Portal hospital directory"
DIRECTORY_SUPPORTING_FACT = f"Also listed in {DIRECTORY_NAME} (an independent source)."


def name_tokens(name: str | None) -> set[str]:
    """Python twin of the Spark token logic in silver/13 and gold/27."""
    toks = re.findall(r"[A-Z0-9]+", (name or "").upper())
    return {t for t in toks if len(t) > 1 and t not in NAME_STOPWORDS}


def compact_name(name: str | None) -> str:
    """Name with generic words and spaces removed: 'Jyoti Punj Hospital' -> 'JYOTIPUNJ'."""
    toks = re.findall(r"[A-Z0-9]+", (name or "").upper())
    return "".join(t for t in toks if t not in NAME_STOPWORDS)


COMPACT_MIN_LEN = 5


def token_overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def names_match(a: str | None, b: str | None) -> bool:
    """Same-PIN candidates only. Needs >= 60% overlap AND a shared distinctive (non-weak) token."""
    ca = compact_name(a)
    if len(ca) >= COMPACT_MIN_LEN and ca == compact_name(b) and set(name_tokens(a)) - WEAK_TOKENS:
        return True
    ta, tb = name_tokens(a), name_tokens(b)
    return bool((ta & tb) - WEAK_TOKENS) and token_overlap(ta, tb) >= MATCH_MIN_OVERLAP


# PM-JAY procedure / specialty names -> our service keys (regex on lower-cased names; first match wins).
# PM-JAY files list only each state's top procedures, so absent != zero.
PMJAY_PROCEDURE_TO_SERVICE = (
    (r"h(a)?emodialysis|peritoneal dialysis|\bdialysis\b", "dialysis"),
    (r"caesar[ie]an|cesarean|\blscs\b|c-section", "emergency_c_section"),
    (r"normal delivery|vaginal delivery|delivery", "maternity_delivery"),
    (r"sick new ?born|neonat|nicu|low birth weight|preterm", "nicu"),
    (r"phaco|cataract|sics\b|small incision", "cataract_surgery"),
    (r"ptca|angioplasty|coronary (angiography|stent)|cath ?lab", "cardiac_cath"),
    (r"cabg|bypass graft|valve (replacement|repair)|open heart|cardiothoracic", "cardiac_surgery"),
    (r"radiotherapy|radiation|brachytherapy|\bimrt\b|\bigrt\b|\bsbrt\b|linac", "radiotherapy"),
    (r"chemotherapy|cisplatin|carboplatin|paclitaxel|docetaxel|gemcitabine|regimen", "chemotherapy"),
    (r"\bburns?\b", "burn_care"),
    (r"blood (and blood component )?transfusion", "blood_bank"),
    (r"poly ?trauma|fracture|head injury|road traffic", "trauma_care"),
    (r"\bicu\b|intensive care|(?<!without )ventilator", "icu"),
    (r"magnetic resonance|\bmri\b", "mri"),
    (r"computed tomogra|\bct scan", "ct_scan"),
)
PMJAY_SPECIALTY_TO_SERVICE = (
    (r"nephrology|kidney disease", "dialysis"),
    (r"obstetric|gynae|gyne", "maternity_delivery"),
    (r"neo-?natal", "nicu"),
    (r"ophthal|opthal", "cataract_surgery"),
    (r"cardiology", "cardiac_cath"),
    (r"cardio[- ]?thoracic|ctvs", "cardiac_surgery"),
    (r"radiation oncology", "radiotherapy"),
    (r"medical oncology", "chemotherapy"),
    (r"burns", "burn_care"),
    (r"emergency room", "emergency_department"),
    (r"polytrauma", "trauma_care"),
)


def map_pmjay(name: str, table=PMJAY_PROCEDURE_TO_SERVICE) -> str | None:
    n = (name or "").lower()
    for rx, svc in table:
        if re.search(rx, n):
            return svc
    return None
