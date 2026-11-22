"""What the caller describes -> which of Care Finder's 16 services to look for (a routing map, not a diagnosis).

Used by the voice agent (via POST /api/symptoms/match) when a caller doesn't know what kind of care they need,
and written to hc_gold.symptom_service_map by gold/35 so it is visible in Databricks.

Rules this map follows:
- It suggests the KIND OF PLACE to look for, never what is wrong. Every spoken line says a doctor must check.
- Warning signs marked red_flag come first: the agent tells the caller to call 108 before anything else.
- Signs are taken from public warning-sign lists (sources in BASIS). Wording is plain and spoken.
- No first aid, medicines or home treatment: that is outside what Care Finder may say.
- Many problems (fever, cough, diarrhoea) are not one of the 16 services. Those return "general": the nearest
  district hospital or a doctor, or the 24x7 emergency department when the sign is serious.

No Spark imports (shared by the backend and the notebooks).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

BASIS = {
    "heart": "Heart attack warning signs (WHO; American Heart Association; NHS)",
    "stroke": "Stroke warning signs, BE-FAST (WHO; American Stroke Association)",
    "pregnancy": "Danger signs in pregnancy (WHO; India MCP card / JSSK)",
    "newborn": "Newborn danger signs (WHO / India IMNCI)",
    "burns": "Burns needing hospital care (WHO burns fact sheet)",
    "trauma": "Serious injury (WHO trauma care guidance)",
    "critical": "Signs of critical illness (WHO emergency triage, ETAT)",
    "kidney": "Kidney failure (National Kidney Foundation; doctor referral)",
    "eyes": "Cataract symptoms (US National Eye Institute); sudden vision loss is an emergency",
    "blood": "Transfusion need (doctor referral; WHO blood safety)",
    "cancer": "Cancer care (doctor referral; suspected signs need a doctor first)",
    "scan": "Imaging ordered by a doctor; CT for head injury and stroke",
    "general": "Not one of the 16 services: general care",
}

WHO = ("any", "adult", "child", "newborn", "pregnant")


@dataclass(frozen=True)
class Sign:
    id: str
    group: str                    # key of BASIS
    says: str                     # plain words, for "it sounds like ..." ("chest pain that spreads to the arm")
    phrases: tuple[str, ...]      # what callers say (lower-case, English); matched as whole words
    services: tuple[str, ...]     # Care Finder service keys, best first; () = general care
    urgency: str                  # emergency | urgent | routine
    who: str = "any"              # any | adult | child | newborn | pregnant
    red_flag: bool = False        # True -> call 108 first

    @property
    def basis(self) -> str:
        return BASIS[self.group]


S = Sign
SIGNS: tuple[Sign, ...] = (
    # ---- heart
    S("chest_pain", "heart", "chest pain, pressure or tightness",
      ("chest pain", "pain in chest", "chest pressure", "tight chest", "chest tightness", "heaviness in chest", "heart pain"),
      ("cardiac_cath", "emergency_department", "icu"), "emergency", red_flag=True),
    S("pain_spreads_arm_jaw", "heart", "pain spreading to the arm, jaw, neck or back",
      ("pain in left arm", "arm pain", "jaw pain", "pain spreading", "pain going to arm"),
      ("cardiac_cath", "emergency_department"), "emergency", red_flag=True),
    S("heart_attack_said", "heart", "a possible heart attack",
      ("heart attack", "cardiac arrest"), ("cardiac_cath", "emergency_department", "icu"), "emergency", red_flag=True),
    S("cold_sweat_breathless", "heart", "cold sweat with breathlessness or feeling faint",
      ("cold sweat", "sweating and breathless", "sweating with chest"), ("cardiac_cath", "emergency_department"), "emergency", red_flag=True),
    S("told_angiography", "heart", "a doctor asking for an angiography or a stent",
      ("angiography", "angiogram", "angioplasty", "stent", "blocked artery", "blockage in heart"), ("cardiac_cath",), "urgent"),
    S("told_heart_surgery", "heart", "a doctor saying they need heart surgery",
      ("bypass", "heart surgery", "heart operation", "valve replacement", "valve problem", "hole in the heart", "open heart"),
      ("cardiac_surgery", "cardiac_cath"), "routine"),
    S("child_heart_problem", "heart", "a child born with a heart problem, with blue lips or breathlessness while feeding",
      ("blue lips", "turns blue", "heart defect", "born with heart problem"), ("cardiac_surgery", "nicu"), "urgent", who="child"),
    # ---- stroke
    S("face_drooping", "stroke", "one side of the face drooping",
      ("face drooping", "face drooped", "mouth crooked", "face fallen", "face twisted"), ("emergency_department", "ct_scan"), "emergency", red_flag=True),
    S("weak_one_side", "stroke", "sudden weakness or numbness on one side of the body",
      ("weakness on one side", "one side weak", "cannot move arm", "cannot move leg", "numb on one side", "paralysis", "paralysed"),
      ("emergency_department", "ct_scan"), "emergency", red_flag=True),
    S("speech_trouble", "stroke", "sudden trouble speaking or understanding",
      ("slurred speech", "cannot speak", "speech problem", "words not coming", "talking strangely"), ("emergency_department", "ct_scan"), "emergency", red_flag=True),
    S("stroke_said", "stroke", "a possible stroke", ("stroke", "brain attack", "lakwa", "paralytic attack"),
      ("emergency_department", "ct_scan", "icu"), "emergency", red_flag=True),
    # ---- pregnancy
    S("preg_bleeding", "pregnancy", "bleeding during pregnancy", ("bleeding", "spotting", "blood coming"),
      ("emergency_c_section", "maternity_delivery", "blood_bank"), "emergency", who="pregnant", red_flag=True),
    S("preg_fits_headache", "pregnancy", "fits, a severe headache or blurred vision in pregnancy",
      ("fits", "seizure", "convulsion", "severe headache", "blurred vision", "swelling of face"),
      ("emergency_c_section", "maternity_delivery", "icu"), "emergency", who="pregnant", red_flag=True),
    S("preg_pain", "pregnancy", "severe pain in the belly during pregnancy",
      ("severe pain", "stomach pain", "abdominal pain", "belly pain"), ("emergency_c_section", "maternity_delivery"), "emergency", who="pregnant", red_flag=True),
    S("labour_long", "pregnancy", "labour going on for many hours, or the baby not coming",
      ("labour for long", "long labour", "baby not coming", "stuck", "pains since yesterday", "labour pains for hours"),
      ("emergency_c_section", "maternity_delivery"), "emergency", who="pregnant", red_flag=True),
    S("baby_not_moving", "pregnancy", "the baby moving less or not at all",
      ("baby not moving", "baby moving less", "no movement"), ("emergency_c_section", "maternity_delivery"), "emergency", who="pregnant", red_flag=True),
    S("water_broke", "pregnancy", "the waters breaking", ("water broke", "waters broke", "water breaking", "leaking water", "fluid leaking"),
      ("maternity_delivery", "emergency_c_section"), "urgent", who="pregnant"),
    S("labour_started", "pregnancy", "labour pains or a planned delivery",
      ("labour", "labor", "contractions", "delivery", "due date", "going to deliver", "labour pains"),
      ("maternity_delivery", "emergency_c_section"), "urgent", who="pregnant"),
    S("told_csection", "pregnancy", "a doctor saying a C-section may be needed, or a high-risk pregnancy",
      ("c section", "caesarean", "cesarean", "operation for delivery", "high risk pregnancy", "twins", "breech", "previous caesarean"),
      ("emergency_c_section", "maternity_delivery", "blood_bank"), "urgent", who="pregnant"),
    # ---- newborn
    S("nb_not_feeding", "newborn", "a newborn not feeding well", ("not feeding", "not drinking milk", "not sucking", "refusing feed"),
      ("nicu",), "emergency", who="newborn", red_flag=True),
    S("nb_breathing", "newborn", "a newborn breathing fast or with difficulty",
      ("fast breathing", "breathing fast", "difficulty breathing", "grunting", "chest pulling in"), ("nicu",), "emergency", who="newborn", red_flag=True),
    S("nb_fits_floppy", "newborn", "a newborn with fits, or very floppy or hard to wake",
      ("fits", "seizure", "convulsion", "floppy", "not waking", "very sleepy", "not moving"), ("nicu",), "emergency", who="newborn", red_flag=True),
    S("nb_temperature", "newborn", "a newborn who is hot with fever or cold to touch",
      ("fever", "very hot", "cold to touch", "body cold"), ("nicu",), "emergency", who="newborn", red_flag=True),
    S("nb_yellow", "newborn", "a newborn turning yellow, especially the palms and soles",
      ("yellow", "jaundice", "yellow eyes", "yellow skin"), ("nicu",), "urgent", who="newborn"),
    S("nb_premature", "newborn", "a baby born early or very small",
      ("premature", "born early", "small baby", "low birth weight", "seven months", "eight months", "weighs less"),
      ("nicu",), "urgent", who="newborn"),
    # ---- burns
    S("burn_large", "burns", "a large burn, or a burn on the face, hands, feet or private parts",
      ("burn", "burns", "burnt", "burned", "fire", "scald", "hot water", "hot oil"), ("burn_care", "emergency_department"), "urgent"),
    S("burn_severe", "burns", "a burn from electricity or chemicals, or after breathing smoke",
      ("electric shock", "electrical burn", "acid", "chemical burn", "breathed smoke", "smoke inhalation"),
      ("burn_care", "emergency_department", "icu"), "emergency", red_flag=True),
    # ---- trauma
    S("road_accident", "trauma", "a road accident or a fall from a height",
      ("accident", "road accident", "bike accident", "car accident", "hit by", "fell from", "fall from height", "fell down"),
      ("trauma_care", "emergency_department", "ct_scan"), "emergency", red_flag=True),
    S("head_injury", "trauma", "a head injury, especially with vomiting, drowsiness or confusion",
      ("head injury", "hit head", "head hit", "head wound", "fell on head"), ("trauma_care", "ct_scan", "emergency_department"), "emergency", red_flag=True),
    S("heavy_bleeding", "trauma", "heavy bleeding that won't stop", ("heavy bleeding", "bleeding a lot", "bleeding badly", "won't stop bleeding", "deep cut"),
      ("trauma_care", "emergency_department", "blood_bank"), "emergency", red_flag=True),
    S("broken_bone", "trauma", "a possible broken bone", ("broken bone", "fracture", "bone broken", "cannot walk after fall", "swollen after fall"),
      ("trauma_care",), "urgent"),
    # ---- critical illness
    S("breathing_severe", "critical", "severe difficulty breathing", ("cannot breathe", "can't breathe", "breathless", "gasping", "breathing difficulty", "short of breath"),
      ("emergency_department", "icu"), "emergency", red_flag=True),
    S("unconscious", "critical", "someone unconscious, very hard to wake, or suddenly confused",
      ("unconscious", "fainted", "not responding", "not waking", "collapsed", "confused", "passed out"),
      ("emergency_department", "icu"), "emergency", red_flag=True),
    S("seizure", "critical", "a fit that won't stop, or a first fit", ("fit", "fits", "seizure", "convulsion", "epilepsy attack"),
      ("emergency_department", "icu"), "emergency", red_flag=True),
    S("poison_bite", "critical", "poisoning, a snake bite or a severe allergic reaction",
      ("poison", "poisoning", "swallowed", "snake", "snakebite", "bitten", "dog bite", "pesticide", "allergic reaction", "throat swelling"),
      ("emergency_department", "icu"), "emergency", red_flag=True),
    S("told_icu", "critical", "a doctor saying the patient needs intensive care or a ventilator",
      ("icu", "intensive care", "ventilator", "critical care", "on oxygen"), ("icu", "emergency_department"), "emergency"),
    # ---- kidney
    S("told_dialysis", "kidney", "a doctor saying the kidneys have failed or dialysis is needed",
      ("dialysis", "kidney failure", "kidney failed", "kidney not working", "kidney problem", "creatinine", "ckd", "kidney disease"),
      ("dialysis",), "urgent"),
    S("kidney_overload", "kidney", "very little urine with swelling and breathlessness, in someone with kidney disease",
      ("no urine", "little urine", "not passing urine", "swelling all over"), ("dialysis", "emergency_department"), "emergency", red_flag=True),
    # ---- eyes
    S("cloudy_vision", "eyes", "slowly worsening cloudy or blurry vision, glare or faded colours",
      ("cloudy", "blurry", "hazy", "blurred vision", "cannot see clearly", "can't see clearly", "glare", "white in eye", "cataract", "motiyabind"),
      ("cataract_surgery",), "routine"),
    S("sudden_vision_loss", "eyes", "sudden loss of vision, an eye injury or a very painful red eye",
      ("sudden blindness", "suddenly cannot see", "eye injury", "something in eye", "painful red eye"),
      ("emergency_department",), "emergency", red_flag=True),
    # ---- blood
    S("told_transfusion", "blood", "a doctor saying the patient needs blood",
      ("need blood", "blood transfusion", "transfusion", "low hemoglobin", "low haemoglobin", "thalassemia", "thalassaemia", "sickle cell"),
      ("blood_bank",), "urgent"),
    # ---- cancer
    S("told_chemo", "cancer", "cancer that a doctor wants treated with chemotherapy", ("chemo", "chemotherapy", "cancer treatment", "oncologist"),
      ("chemotherapy",), "routine"),
    S("told_radiation", "cancer", "cancer that a doctor wants treated with radiation", ("radiation", "radiotherapy", "radiation therapy", "sikai"),
      ("radiotherapy", "chemotherapy"), "routine"),
    S("cancer_diagnosed", "cancer", "a cancer diagnosis", ("cancer", "tumour", "tumor", "malignant"), ("chemotherapy", "radiotherapy"), "routine"),
    S("cancer_warning", "cancer", "a lump, or weight loss or bleeding without a reason, that a doctor should check",
      ("lump", "unexplained weight loss", "losing weight", "growth"), (), "routine"),
    # ---- scans
    S("told_mri", "scan", "a doctor asking for an MRI scan", ("mri", "mri scan"), ("mri",), "routine"),
    S("told_ct", "scan", "a doctor asking for a CT scan", ("ct scan", "ct", "cat scan"), ("ct_scan",), "routine"),
    # ---- not one of the 16
    S("fever_general", "general", "fever, cough, diarrhoea or other everyday illness",
      ("fever", "cough", "cold", "diarrhoea", "diarrhea", "vomiting", "loose motion", "body pain", "headache"), (), "routine"),
    S("severe_belly_pain", "general", "severe pain in the belly", ("severe stomach pain", "severe abdominal pain", "severe belly pain"),
      ("emergency_department",), "emergency", red_flag=True),
)

# When nothing matches: offer these areas, one short question
MENU = ("an injury or accident", "a burn", "a pregnancy or delivery", "a newborn baby", "the heart or chest",
        "breathing or someone very unwell", "the kidneys", "the eyes", "cancer care", "needing blood", "a scan a doctor asked for")

ADVICE = {
    "emergency": "This could be serious. Please call 108 for an ambulance now. If you can't get one, go to the nearest "
                 "emergency department straight away. Don't wait to see if it gets better.",
    "urgent": "This should be seen by a doctor today.",
    "routine": "A doctor should check this. You can plan the visit, but call the place first.",
}
TELL_THEM = {
    "heart": "When you call, tell them when the pain started.",
    "stroke": "Tell them the time the symptoms started. That time matters for treatment.",
    "pregnancy": "Tell them how many months pregnant she is and what is happening.",
    "newborn": "Tell them the baby's age in days and, if you know it, the birth weight.",
    "burns": "Tell them what caused the burn and roughly how big it is.",
    "trauma": "Tell them what happened and when.",
    "critical": "Tell them what happened and when it started.",
    "kidney": "Tell them about the kidney problem and bring the latest reports.",
    "eyes": "Tell them which eye and how long it has been like this.",
    "blood": "Tell them the blood group if you know it, and why the doctor said blood is needed.",
    "cancer": "Bring the reports and the doctor's note.",
    "scan": "Bring the doctor's note asking for the scan.",
    "general": "Tell them the main problem and how long it has been going on.",
}
NOT_A_DIAGNOSIS = "I can't tell you what's wrong. This only helps find the right kind of place, and a doctor there will check."

_WORD = re.compile(r"[a-z0-9']+")
WHO_WORDS = {
    "pregnant": ("pregnant", "pregnancy", "expecting", "months pregnant", "labour", "labor", "delivery", "garbhvati"),
    "newborn": ("newborn", "new born", "born yesterday", "born today", "days old", "week old", "just born", "baby born"),
    "child": ("child", "son", "daughter", "kid", "boy", "girl", "baby"),
}


def _norm(text: str) -> str:
    return " ".join(_WORD.findall((text or "").lower().replace("-", " ")))


def _stem(w: str) -> str:
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def _has(text: str, phrase: str) -> bool:
    """True when every word of the phrase appears in the text (any order, plurals ignored):
    "kidney not working" matches "his kidneys are not working"; "chest pain" matches "pain in my chest"."""
    words = {_stem(w) for w in text.split()}
    return all(_stem(w) in words for w in phrase.split())


def guess_who(text: str) -> str:
    t = _norm(text)
    for who in ("newborn", "pregnant", "child"):  # most specific first
        if any(_has(t, w) for w in WHO_WORDS[who]):
            return who
    return "any"


def match(text: str, who: str = "", limit: int = 3) -> dict:
    """Signs found in what the caller said, and the services they point to, best first.

    who: any | adult | child | newborn | pregnant ('' = guess from the text). Signs for a different group
    are ignored (newborn danger signs don't apply to an adult)."""
    t = _norm(text)
    who = who if who in WHO else guess_who(text)
    ok_who = {"any", who} | ({"newborn"} if who == "child" else set()) | ({"child"} if who == "newborn" else set())
    found = [s for s in SIGNS if s.who in ok_who and any(_has(t, p) for p in s.phrases)]
    # pregnancy / newborn signs are more specific than everyday-illness ones that matched the same words
    if any(s.who in ("pregnant", "newborn") for s in found):
        found = [s for s in found if s.group != "general"]

    scores: dict[str, float] = {}
    why: dict[str, list[str]] = {}
    for s in found:
        for rank, svc in enumerate(s.services):
            scores[svc] = scores.get(svc, 0) + (2.0 if s.red_flag else 1.0) / (1 + rank)
            why.setdefault(svc, []).append(s.says)
    services = [{"service_key": k, "because": why[k][:2]} for k, _ in sorted(scores.items(), key=lambda kv: -kv[1])[:limit]]

    order = {"emergency": 0, "urgent": 1, "routine": 2}
    urgency = min((s.urgency for s in found), key=order.get, default=None)
    red = [s for s in found if s.red_flag]
    groups = list(dict.fromkeys(s.group for s in found))
    general_only = bool(found) and not services
    return {
        "who": who,
        "signs": [{"id": s.id, "says": s.says, "red_flag": s.red_flag, "urgency": s.urgency, "basis": s.basis} for s in found],
        "red_flag": bool(red),
        "urgency": urgency,
        "services": services,
        "general_care": general_only,
        "advice": ADVICE.get(urgency or "", ""),
        "tell_them": [TELL_THEM[g] for g in groups][:2],
        "not_a_diagnosis": NOT_A_DIAGNOSIS,
        "menu": [] if found else list(MENU),
    }


def rows() -> list[dict]:
    """One row per sign x service, for hc_gold.symptom_service_map."""
    out = []
    for s in SIGNS:
        for rank, svc in enumerate(s.services or ("general_care",), start=1):
            out.append({"sign_id": s.id, "group": s.group, "who": s.who, "says": s.says, "phrases": list(s.phrases),
                        "service_key": svc, "service_rank": rank, "urgency": s.urgency, "red_flag": s.red_flag,
                        "advice": ADVICE[s.urgency], "tell_them": TELL_THEM[s.group], "basis": s.basis})
    return out
