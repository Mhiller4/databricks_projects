"""IHDS-II (2011-12) medical facilities survey: code -> label maps.

Source: India Human Development Survey, ICPSR 36151 dataset 6 ("Medical Facilities") codebook,
uploaded as /Volumes/workspace/hc_bronze/landing/36151-0006-Codebook.pdf. 4,447 facilities sampled
near IHDS villages and urban blocks; half government, half private. Not a census, and 2011-12, so we
use it for *base rates* (what share of each facility type offers a service), not for individual facilities.

Coding (from the codebook): services MF13* and equipment MF16* are 0 = No, 1 = Yes, blank = missing.
MQGOVT 0 = Private, 1 = Govt. MF1 = facility type (below). STATEID = Census 2001 state code.
No Spark imports.
"""

from __future__ import annotations

# MF1: "What type of facility is this?" -> (label, ownership, our facility_type bucket)
FACILITY_TYPES = {
    1: ("Public hospital", "public", "hospital"),
    2: ("Community Health Centre (CHC)", "public", "hospital"),
    3: ("Primary Health Centre (PHC)", "public", "clinic"),
    4: ("Sub-centre", "public", "clinic"),
    5: ("Public family planning centre", "public", "clinic"),
    6: ("Private hospital", "private", "hospital"),
    7: ("Private clinic or polyclinic", "private", "clinic"),
    8: ("Private doctor", "private", "doctor"),
    9: ("Other", None, None),
}

# MF13*: "Does this clinic provide ...?" (0/1)
SERVICES = {
    "MF13A": "Child immunizations", "MF13B": "Contraception: oral pills", "MF13C": "Contraception: IUD insertion",
    "MF13D": "Male vasectomy", "MF13E": "Female sterilisation", "MF13F": "Contraception: injection",
    "MF13G": "Incision of abscess, boils", "MF13H": "Saline IV", "MF13I": "Setting broken bones",
    "MF13J": "Gynaecological conditions", "MF13K": "STDs/STIs", "MF13L": "DOTS for tuberculosis",
    "MF13M": "Prenatal care", "MF13N": "Eye exam", "MF13O": "Diarrhoea", "MF13P": "Wound dressing",
    "MF13Q": "Stitching wounds", "MF13R": "Malaria", "MF13S": "Minor illnesses like fever", "MF13T": "Rabies",
    "MF13U": "Childbirth", "MF13V": "Abortion / D&C", "MF13W": "Blood transfusion", "MF13X": "Cataract surgery",
    "MF13Y": "Abdominal surgery", "MF13Z": "Heart surgery",
}

# MF16*: "Does the facility have ... in good working condition?" (0/1)
EQUIPMENT = {
    "MF16A": "Stethoscope", "MF16B": "Sterilisation / autoclave", "MF16C": "Adult weighing scale",
    "MF16D": "Infant weighing scale", "MF16E": "Thermometer", "MF16F": "Vaginal speculum",
    "MF16G": "Ultrasound", "MF16H": "X-ray machine", "MF16I": "Blood pressure gauge", "MF16J": "Oxygen",
    "MF16K": "Otoscope", "MF16L": "Ophthalmoscope", "MF16M": "Delivery kit", "MF16N": "Forceps",
    "MF16O": "Partograph", "MF16P": "IV stand", "MF16Q": "Laryngoscope", "MF16R": "Urethral catheter",
    "MF16S": "Microscope", "MF16T": "Centrifuge", "MF16U": "Refrigerator", "MF16V": "Cold chest",
    "MF16W": "ECG monitor", "MF16X": "Ambulance", "MF16Y": "Wheelchair", "MF16Z": "Trolley stretcher",
    "MF16AA": "Computer", "MF16BB": "Internet", "MF16CC": "Landline telephone", "MF16DD": "Mobile phone for patients",
}

# Our Care Finder services -> the IHDS evidence that best stands for them.
# all(...) = every listed variable must be Yes. These are proxies, and the notebook labels them as such.
SERVICE_PROXIES = {
    "maternity_delivery": {"all": ["MF13U"], "note": "Childbirth offered"},
    "emergency_c_section": {"all": ["MF13U", "MF13Y"], "note": "Childbirth + abdominal surgery (C-section capability proxy)"},
    "blood_bank": {"all": ["MF13W"], "note": "Blood transfusion offered"},
    "cataract_surgery": {"all": ["MF13X"], "note": "Cataract surgery offered"},
    "cardiac_surgery": {"all": ["MF13Z"], "note": "Heart surgery offered"},
    "trauma_care": {"all": ["MF13I", "MF13Q"], "note": "Setting broken bones + stitching wounds"},
    "icu": {"all": ["MF16J", "MF16W"], "note": "Oxygen + ECG monitor (critical-care equipment proxy)"},
}

# Other columns used
BEDS = "MF6A"            # beds for overnight in-patient care (count)
OWNERSHIP = "MQGOVT"     # 0 private, 1 government
FACILITY_TYPE = "MF1"
YEAR_OPENED = "MF4"
KM_TO_DISTRICT_HOSPITAL = "MF5A"
KM_TO_CHC = "MF5B"

# STATEID (Census 2001 codes)
STATES = {
    1: "Jammu & Kashmir", 2: "Himachal Pradesh", 3: "Punjab", 4: "Chandigarh", 5: "Uttarakhand", 6: "Haryana",
    7: "Delhi", 8: "Rajasthan", 9: "Uttar Pradesh", 10: "Bihar", 11: "Sikkim", 12: "Arunachal Pradesh",
    13: "Nagaland", 14: "Manipur", 15: "Mizoram", 16: "Tripura", 17: "Meghalaya", 18: "Assam",
    19: "West Bengal", 20: "Jharkhand", 21: "Odisha", 22: "Chhattisgarh", 23: "Madhya Pradesh", 24: "Gujarat",
    25: "Daman & Diu", 27: "Maharashtra", 28: "Andhra Pradesh", 29: "Karnataka", 30: "Goa", 31: "Lakshadweep",
    32: "Kerala", 33: "Tamil Nadu", 34: "Puducherry",
}
