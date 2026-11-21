"""Care Finder rules: the service catalog, evidence weights, trust penalties and location aliases.

Everything a judge would ask about under "HOW did you decide?" lives here, in plain Python, so it can
be read, tested, and written to gold.service_catalog / shown in the app. No Spark imports.

Scoring, end to end (see notebooks/gold/21-23):

    evidence_score  = 1 - PRODUCT(1 - best_weight_per_field)       noisy-OR across independent fields
                      (+ QUANTITY_BONUS when a snippet gives specifics like "10 dialysis machines")
    type_fit        = does the facility type / name fit the service (a dental clinic offering NICU?)
    trust_score     = PRODUCT of record-level penalties (location conflicts, merged records, thin sources)
    distance_score  = exp(-distance_km / service.tau_km)            tau is how far people reasonably travel
    score           = evidence_score * type_fit * trust_score * distance_score

Confidence (independent of distance, so a far facility can still be High confidence):
    High   evidence >= 0.75 (two or more independent fields agree), trust >= 0.75, type_fit >= 0.9
    Medium evidence >= 0.5, trust >= 0.5 and type_fit >= 0.5
    Low    anything else, including specialty-only ("indirect") evidence
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

# --------------------------------------------------------------------------------------------
# Evidence weights per source field
# --------------------------------------------------------------------------------------------

# A claim in `procedure` or `equipment` names a concrete thing the facility does or has, so it is
# the strongest single field. `capability` is broader marketing-style text. `description` is a
# one-paragraph summary. A specialty tag alone ("nephrology") only says a related department exists.
FIELD_WEIGHTS = {
    "procedure": 0.60,
    "equipment": 0.60,
    "capability": 0.50,
    "description": 0.35,
    "specialties": 0.15,
}
DIRECT_FIELDS = ("procedure", "equipment", "capability", "description")

# A snippet that reads like a directory / scheme listing ABOUT another hospital ("X is listed as a
# referral hospital") is weak evidence for THIS facility: it is how merged records happen.
THIRD_PARTY_PATTERN = (
    r"(listed (in|as|under)|referral hospital|referred to|refer(s)? patients|empanel+ed|"
    r"hospital directory|scheme hospital|tie[- ]?up with|outside the state)"
)
THIRD_PARTY_FACTOR = 0.5

# Specifics ("20-bed dialysis unit", "10 machines", "1.5 tesla", "128 slice") are harder to invent.
QUANTITY_PATTERN = r"[0-9]+ ?-? ?(beds?|bedded|machines?|stations?|chairs?|slices?|tesla|incubators?|warmers?|ventilators?|units)\b"
QUANTITY_BONUS = 0.05
EVIDENCE_CAP = 0.97

# --------------------------------------------------------------------------------------------
# Services
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Service:
    key: str
    label: str
    pattern: str  # Java/Spark regex, matched against lower-cased snippet text
    specialties: tuple[str, ...] = ()  # specialty codes that count as indirect evidence
    needs_hospital: bool = False  # inpatient / surgical / critical care
    tau_km: float = 40.0  # distance at which the distance score falls to 37%
    compatible_name_kinds: tuple[str, ...] = ()  # facility-name specialties that fit (e.g. eye -> cataract)
    synonyms: tuple[str, ...] = ()  # what a user might type
    note: str = ""

    def as_row(self) -> dict:
        d = asdict(self)
        for k in ("specialties", "compatible_name_kinds", "synonyms"):
            d[k] = list(d[k])
        return d


SERVICES: tuple[Service, ...] = (
    Service(
        "dialysis", "Dialysis",
        r"\b(dialysis|haemodialysis|hemodialysis|hemodiafiltration|haemodiafiltration|capd|crrt)\b",
        ("nephrology",), False, 30,
        synonyms=("kidney dialysis", "haemodialysis", "hemodialysis", "kidney machine", "renal replacement"),
        note="Recurring care (2-3 sessions a week), so distance matters a lot.",
    ),
    Service(
        "emergency_c_section", "Emergency C-section / high-risk delivery",
        r"\b(c[- ]?sections?|caesarean|cesarean|lscs|emergency obstetric\w*|cemonc|bemonc|emoc|"
        r"high[- ]risk (pregnanc\w*|deliver\w*|obstetric\w*)|obstetric emergenc\w*|obstetric icu)\b",
        ("gynecologyAndObstetrics", "obstetricsAndMaternityCare", "maternalFetalMedicineOrPerinatology"), True, 25,
        synonyms=("c section", "caesarean", "cesarean", "high risk delivery", "high risk pregnancy", "emergency delivery"),
        note="Time-critical: an emergency C-section should start within about 30 minutes of the decision.",
    ),
    Service(
        "maternity_delivery", "Maternity / normal delivery",
        r"\b(labou?r rooms?|normal deliver\w*|childbirth|maternity (ward|wards|unit|units|services?|care|home|hospital)|"
        r"deliveries|antenatal|obstetric care)\b",
        ("gynecologyAndObstetrics", "obstetricsAndMaternityCare"), True, 25,
        compatible_name_kinds=("fertility",),
        synonyms=("delivery", "pregnancy", "labour", "labor", "birth", "maternity"),
    ),
    Service(
        "nicu", "NICU (newborn intensive care)",
        r"\b(nicu|neonatal intensive care|neonatal icu|newborn intensive care|level (ii|iii|2|3) neonatal|sncu|"
        r"special newborn care)\b",
        ("neonatologyPerinatalMedicine",), True, 40,
        synonyms=("neonatal icu", "newborn icu", "premature baby", "sncu", "neonatal intensive care"),
    ),
    Service(
        "icu", "ICU / critical care",
        r"\b(icu|iccu|micu|sicu|intensive care|critical care|ventilators?|ventilator support)\b",
        ("criticalCareMedicine",), True, 40,
        synonyms=("intensive care", "critical care", "ventilator"),
    ),
    Service(
        "trauma_care", "Trauma / accident care",
        r"\b(trauma (centre|center|care|unit|ward|surgery|services?|team|icu)|polytrauma|level [i1]+ trauma|"
        r"accident (and|&) emergency|road traffic accident|casualty)\b",
        ("emergencyMedicine",), True, 40,
        synonyms=("trauma", "accident", "road accident", "injury", "casualty"),
    ),
    Service(
        "emergency_department", "24x7 emergency department",
        r"(24 ?[x×/*] ?7|24 ?hours?|round[- ]the[- ]clock) ?(emergency|casualty)|\bemergency (department|services?|room|care|ward|unit)\b",
        ("emergencyMedicine",), True, 30,
        synonyms=("emergency", "er", "a&e", "24 hour emergency"),
    ),
    Service(
        "burn_care", "Burn care",
        r"\b(burns? (unit|units|ward|care|centre|center|icu|treatment|management|surgery)|burn injur\w*)\b",
        ("plasticSurgery",), True, 100,
        synonyms=("burns", "burn unit", "burn ward"),
    ),
    Service(
        "cardiac_surgery", "Cardiac surgery",
        r"\b(cardiac surger\w*|heart surger\w*|open[- ]heart|cabg|coronary artery bypass|bypass surger\w*|"
        r"valve (replacement|repair)|cardiothoracic|ctvs)\b",
        ("cardiacSurgery", "cardiothoracicSurgery"), True, 150,
        synonyms=("heart surgery", "bypass", "cabg", "open heart", "valve replacement"),
        note="Planned surgery: patients travel further, so distance is weighted less.",
    ),
    Service(
        "cardiac_cath", "Angioplasty / cath lab",
        r"\b(angioplasty|cath(eterisation|eterization)? lab|ptca|coronary stent\w*|stenting|angiography)\b",
        ("cardiology", "interventionalCardiology"), True, 60,
        synonyms=("angioplasty", "cath lab", "heart attack", "stent", "angiography"),
    ),
    Service(
        "mri", "MRI scan",
        r"\b(mri|magnetic resonance)\b",
        ("radiology",), False, 75,
        compatible_name_kinds=("diagnostic_lab",),
        synonyms=("mri scan", "magnetic resonance"),
    ),
    Service(
        "ct_scan", "CT scan",
        r"\b(ct scan\w*|ct scanner|computed tomography|cect|hrct|[0-9]+[- ]?slice ct)\b",
        ("radiology",), False, 50,
        compatible_name_kinds=("diagnostic_lab",),
        synonyms=("ct", "cat scan", "ct scan"),
    ),
    Service(
        "blood_bank", "Blood bank / transfusion",
        r"\b(blood banks?|blood storage|blood transfusion\w*|blood centre|blood center)\b",
        ("hematology",), False, 40,
        synonyms=("blood", "transfusion"),
    ),
    Service(
        "chemotherapy", "Cancer chemotherapy",
        r"\b(chemotherapy|chemo|medical oncology|oncology (department|unit|services?|centre|center|ward))\b",
        ("medicalOncology",), False, 120,
        synonyms=("chemo", "cancer treatment", "oncology", "cancer"),
    ),
    Service(
        "radiotherapy", "Radiotherapy",
        r"\b(radiotherapy|radiation therapy|radiation oncology|linac|linear accelerator|brachytherapy|"
        r"cobalt[- ]60|tomotherapy|cyberknife)\b",
        ("radiationOncology",), True, 150,
        synonyms=("radiation", "radiation therapy", "cancer radiation"),
    ),
    Service(
        "cataract_surgery", "Cataract surgery",
        r"\b(cataracts?|phaco\w*|iol implant\w*|intraocular lens)\b",
        ("cataractAndAnteriorSegmentSurgery", "ophthalmology"), False, 75,
        compatible_name_kinds=("eye",),
        synonyms=("cataract", "eye surgery", "phaco"),
    ),
)
SERVICES_BY_KEY = {s.key: s for s in SERVICES}

# --------------------------------------------------------------------------------------------
# Facility-type fit
# --------------------------------------------------------------------------------------------

# Single-specialty names. If the name says "Eye Hospital" but the record claims dialysis, the
# dialysis text probably came from a different facility merged into this record.
NAME_KINDS = {
    "eye": r"\b(eye|eyes|netra|nethra|netralaya|nethralaya|ophthalm\w*|vision|lasik)\b",
    "dental": r"\b(dental|dentist\w*|dentistry|orthodont\w*|tooth|teeth|smile)\b",
    "skin": r"\b(skin|derma\w*|cosmetolog\w*|hair)\b",
    "fertility": r"\b(ivf|fertility|test tube)\b",
    "ent": r"\b(ent|ear nose|hearing)\b",
    "physio": r"\b(physio\w*|rehab\w*)\b",
    "diagnostic_lab": r"\b(lab|labs|laboratory|pathology|diagnostics?)\b",
}
NAME_KIND_FIT = 0.4  # multiplier when the name kind conflicts with the service

TYPE_FIT = {
    # facility_type -> (fit for hospital-only services, fit for other services)
    "hospital": (1.0, 1.0),
    "clinic": (0.6, 0.9),
    "doctor": (0.3, 0.7),
    "dentist": (0.1, 0.3),
    "pharmacy": (0.1, 0.2),
    None: (0.5, 0.7),
}

# --------------------------------------------------------------------------------------------
# Trust penalties (multiplied together; each one adds a plain-language caution)
# --------------------------------------------------------------------------------------------

TRUST_PENALTIES = {
    "malformed_record": (0.3, "Record looks malformed (fields shifted), so details may belong to the wrong columns."),
    "coords_outside_india": (0.4, "Listed coordinates are outside India; location taken from the PIN code instead."),
    "no_location": (0.5, "No usable coordinates or PIN code, so the distance is unknown."),
    "location_from_pin_only": (0.9, "No coordinates listed; location approximated from the PIN code."),
    "pin_coords_conflict": (0.8, "Listed coordinates are {pin_distance_km} km from the PIN code's area ({location_conflict_resolved_by}); the location we used may still be off."),
    "state_conflict": (0.85, "Address state ({state_text}) disagrees with the PIN code's state ({pin_state})."),
    "pin_not_found": (0.9, "PIN code {pin} is not in the India Post directory."),
    "single_source": (0.8, "Built from a single web source."),
    "few_sources": (0.9, "Built from only {n_sources} web sources."),
    "possible_duplicate": (0.9, "Another record looks like the same facility ({dup_reason}); details may be split or merged."),
    "beds_doctors_implausible": (0.85, "Lists {capacity} beds but only {number_doctors} doctor(s); numbers may be merged from different places."),
    "sparse_record": (0.85, "Almost no supporting detail (no beds, doctors, year established or equipment listed)."),
}
# single_source / few_sources are waived when the facility also appears in the National Health Portal
# hospital directory (an independent source; gold/27, src/hc/ext.py).
PIN_COORD_CONFLICT_KM = 50
TRUST_FLOOR = 0.05

INDIA_BBOX = {"lat_min": 6.0, "lat_max": 37.6, "lon_min": 68.0, "lon_max": 97.6}

# --------------------------------------------------------------------------------------------
# Confidence
# --------------------------------------------------------------------------------------------

CONFIDENCE_RULES = (
    ("High", "evidence >= 0.75 (two or more independent fields agree), trust >= 0.75 and the facility type fits"),
    ("Medium", "evidence >= 0.5, trust >= 0.5 and the facility type plausibly fits (type_fit >= 0.5)"),
    ("Low", "anything else, including specialty-only (indirect) evidence"),
)


def confidence(evidence: float, trust: float, type_fit: float) -> str:
    """Python twin of the SQL CASE in gold/23, used by tests and the app."""
    if evidence >= 0.75 and trust >= 0.75 and type_fit >= 0.9:
        return "High"
    if evidence >= 0.5 and trust >= 0.5 and type_fit >= 0.5:
        return "Medium"
    return "Low"


def noisy_or(weights: list[float]) -> float:
    p = 1.0
    for w in weights:
        p *= 1 - w
    return 1 - p


# --------------------------------------------------------------------------------------------
# State names and location aliases
# --------------------------------------------------------------------------------------------

# Keys are upper-case alphanumerics only ("Tamil Nadu" -> TAMILNADU), so spacing variants match.
STATE_ALIASES = {
    "ORISSA": "ODISHA",
    "UP": "UTTARPRADESH",
    "MP": "MADHYAPRADESH",
    "PONDICHERRY": "PUDUCHERRY",
    "PUNJABREGION": "PUNJAB",
    "NCT": "DELHI",
    "NCTOFDELHI": "DELHI",
    "NEWDELHI": "DELHI",
    "UTTARANCHAL": "UTTARAKHAND",
    "JAMMUKASHMIR": "JAMMUANDKASHMIR",
    "JK": "JAMMUANDKASHMIR",
    "TELENGANA": "TELANGANA",
    "CHATTISGARH": "CHHATTISGARH",
    "WESTBENGAL": "WESTBENGAL",
    "DAMANANDDIU": "THEDADRAANDNAGARHAVELIANDDAMANANDDIU",
    "DADRAANDNAGARHAVELI": "THEDADRAANDNAGARHAVELIANDDAMANANDDIU",
    "ANDAMANANDNICOBAR": "ANDAMANANDNICOBARISLANDS",
}

# Old and new place names a user might type.
PLACE_ALIASES = {
    "BANGALORE": "BENGALURU",
    "BENGALURU": "BANGALORE",
    "GURGAON": "GURUGRAM",
    "GURUGRAM": "GURGAON",
    "BOMBAY": "MUMBAI",
    "CALCUTTA": "KOLKATA",
    "MADRAS": "CHENNAI",
    "TRIVANDRUM": "THIRUVANANTHAPURAM",
    "POONA": "PUNE",
    "BARODA": "VADODARA",
    "BENARES": "VARANASI",
    "BANARAS": "VARANASI",
    "ALLAHABAD": "PRAYAGRAJ",
    "PRAYAGRAJ": "ALLAHABAD",
    "COCHIN": "KOCHI",
    "KOCHI": "ERNAKULAM",
    "MYSORE": "MYSURU",
    "MANGALORE": "MANGALURU",
    "CAWNPORE": "KANPUR",
    "PONDICHERRY": "PUDUCHERRY",
    "NEWDELHI": "DELHI",
}


def key(text: str | None) -> str:
    """Python twin of the SQL key: upper-case, alphanumerics only."""
    return "".join(ch for ch in (text or "").upper() if ch.isalnum())


@dataclass
class ServiceMatch:
    service: Service
    how: str  # 'key', 'label', 'synonym'
    alternatives: list[str] = field(default_factory=list)


def match_service(text: str) -> ServiceMatch | None:
    """Map what a user typed to a service (used by the app; SQL has its own twin)."""
    k = key(text)
    if not k:
        return None
    for s in SERVICES:
        if k == key(s.key) or k == key(s.label):
            return ServiceMatch(s, "label")
    for s in SERVICES:
        if any(k == key(x) for x in s.synonyms):
            return ServiceMatch(s, "synonym")
    hits = [s for s in SERVICES if k in key(s.label) or any(k in key(x) or key(x) in k for x in s.synonyms)]
    if len(hits) == 1:
        return ServiceMatch(hits[0], "partial")
    if hits:
        return ServiceMatch(hits[0], "ambiguous", [h.label for h in hits[1:]])
    return None
