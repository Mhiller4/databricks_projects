"""Spoken summary for the phone agent: a fixed template filled with engine output, never LLM-written.

Written to be heard, not read: short sentences, no field names, distances and phone numbers in a form
TTS says naturally. Every fact comes from the engine response. Target 30-45 seconds (80-110 words).
"""

from __future__ import annotations

import re

# Gold-table cautions -> how a helpline nurse would say them (first match wins)
PLAIN_CAUTIONS = (
    ("coordinates", "their map location doesn't quite match their PIN code, so double-check the address"),
    ("is not in the india post", "their PIN code isn't in the postal directory, so double-check the address"),
    ("single web source", "their details come from only one website"),
    ("indirect evidence", "they list a related department, but never mention this service directly"),
    ("another hospital", "the mention reads like it's about another hospital"),
    ("merged", "their listing may be mixed up with another facility"),
    ("beds but only", "their bed and doctor numbers don't add up"),
    ("almost no supporting detail", "their listing has very little detail"),
    ("disagrees with the pin", "their address and PIN code point to different states"),
    ("looks like the same facility", "they may be listed twice"),
)


def _say_label(label: str) -> str:
    """'NICU (newborn intensive care)' -> 'NICU'; keeps acronyms upper-case so TTS spells them."""
    base = re.sub(r"\s*\(.*?\)", "", label).split(" / ")[0].strip()
    return " ".join(w if w.isupper() else w.lower() for w in base.split())


def _say_phone(p: str | None) -> str | None:
    """'+916272233684' -> '+91 62722 33684' so it is read in digit groups."""
    if not p:
        return None
    d = re.sub(r"\D", "", p)
    if len(d) == 12 and d.startswith("91"):
        return f"+91 {d[2:7]} {d[7:]}"
    return p


def _km(x: float) -> str:
    if x < 1:
        return "less than a kilometre"
    if x < 10:
        return f"about {x:.1f} kilometres"
    return f"about {x:.0f} kilometres"


def _plain_caution(rec: dict) -> str | None:
    for c in (rec.get("call_ahead") or []) + (rec.get("cautions") or []):
        lc = c.lower()
        for marker, plain in PLAIN_CAUTIONS:
            if marker in lc:
                return plain
    return None


def _evidence_sentence(rec: dict, svc: str) -> str:
    n_fields = len(rec["score_breakdown"]["raw"].get("evidence_fields") or [])
    where = "in several places" if n_fields >= 3 else "in two places" if n_fields == 2 else "in only one part of their listing"
    sure = {
        "High": "so I'm fairly confident they offer it",
        "Medium": "so they probably offer it, but please confirm by phone",
        "Low": "but the evidence is thin, so please confirm by phone",
    }[rec["confidence"]]
    if n_fields <= 1:
        return f"Only one part of their listing mentions {svc}, {sure}."
    return f"Their own listing mentions {svc} {where}, {sure}."


def _general(resp: dict) -> str:
    q = resp["query"]
    svc = _say_label(q["service"]["label"])
    place = "your location" if q["location"].get("kind") == "coordinates" else q["location"]["display_name"]
    recs = resp["recommendations"]
    desert = resp["medical_desert_alert"]
    funnel = resp["funnel"]
    parts: list[str] = []

    if not recs:
        far = resp.get("nearest_beyond_radius") or []
        parts.append(f"I'm sorry, I could not find a facility near {place} that clearly offers {svc}, at least not in the data I have.")
        if far:
            r = far[0]
            town = r["city"] or r["district"] or r["state"]
            parts.append(f"The nearest one I can vouch for is {r['name']} in {town}, {_km(r['distance_km'])} away.")
            if r.get("phone"):
                parts.append(f"Please call them before travelling, on {_say_phone(r['phone'])}.")
        parts.append("My data has few government hospitals, so it's worth checking with the district hospital too.")
        return " ".join(parts)

    top = recs[0]
    parts.append(f"For {svc} near {place}, the best option I found is {top['name']}, {_km(top['distance_km'])} away.")
    parts.append(_evidence_sentence(top, svc))
    caution = _plain_caution(top)
    if caution:
        parts.append(f"One thing to know: {caution}.")
    if top.get("phone"):
        parts.append(f"You can call them on {_say_phone(top['phone'])} before you go.")

    alts = []
    for r in recs[1:]:
        if r.get("tier") == "nearest_verified":
            alts.append(f"{r['name']} is {'closer' if r['distance_km'] < top['distance_km'] else 'also nearby'}, {_km(r['distance_km'])} away")
        elif r.get("tier") == "highest_confidence":
            alts.append(f"{r['name']}, {_km(r['distance_km'])} away, has the strongest evidence overall")
    if alts:
        parts.append("If that doesn't work out, " + ", and ".join(alts) + ".")
    if desert["triggered"]:
        parts.append(f"Just so you know, none of these is within {desert['safe_km']:.0f} kilometres.")

    n_near, n_passed = funnel[4]["count"], funnel[6]["count"]
    parts.append(f"Of the {n_near} places nearby that mention {svc}, {n_passed} passed all my checks.")
    return " ".join(parts)


# ---------------------------------------------------------------------------------------------
# Audience-specific versions (the voice agent's provider / patient personas)
# ---------------------------------------------------------------------------------------------

SKIP_REASONS = (
    ("no direct evidence", "it only lists a related specialty"),
    ("another hospital", "the mention is about another hospital"),
    ("record trust", "its record has data problems"),
    ("type fit", "it is the wrong type of facility for this"),
    ("scores lower", "its evidence was weaker"),
)
FIELD_WORDS = {"procedure": "procedures", "equipment": "equipment", "capability": "capabilities", "description": "description"}


def _fields(rec: dict) -> str:
    f = [FIELD_WORDS.get(x, x) for x in rec["score_breakdown"]["raw"].get("evidence_fields") or []]
    return f[0] if len(f) == 1 else ", ".join(f[:-1]) + " and " + f[-1] if f else "its listing"


def _skip_reason(s: dict) -> str:
    r = (s.get("reasons") or [""])[0].lower()
    return next((plain for marker, plain in SKIP_REASONS if marker in r), r)


def _town(r: dict) -> str:
    return r.get("city") or r.get("district") or r.get("state") or ""


def _precision_note(resp: dict) -> str | None:
    loc = resp["query"]["location"]
    if not loc.get("ask_for_more_detail"):
        return None
    return (f"These distances are from the {loc.get('precision', 'centre')} of {loc['display_name'].split(' (')[0]}. "
            "Tell me the area or PIN code and I can find closer options.")


def _provider(resp: dict) -> str:
    q = resp["query"]
    svc = _say_label(q["service"]["label"])
    place = "your location" if q["location"].get("kind") == "coordinates" else q["location"]["display_name"]
    recs, skipped, funnel = resp["recommendations"], resp["skipped_nearby"], resp["funnel"]
    parts: list[str] = []
    if not recs:
        far = resp.get("nearest_beyond_radius") or []
        safe = resp["medical_desert_alert"]["safe_km"]
        parts.append(f"No facility with verified {svc} evidence within {safe:.0f} kilometres of {place} in this dataset.")
        if far:
            r = far[0]
            parts.append(f"Nearest verified: {r['name']} in {_town(r)}, {_km(r['distance_km'])}, {r['confidence'].lower()} confidence"
                         + (f", phone {_say_phone(r['phone'])}." if r.get("phone") else "."))
        if skipped:
            s0 = skipped[0]
            parts.append(f"Closer facilities didn't qualify: for example {s0['name']}, {_km(s0['distance_km'])}, because {_skip_reason(s0)}.")
        parts.append("The dataset under-covers government facilities, so check with the district hospital as well.")
    else:
        ordinal = ["First", "Second", "Third"]
        parts.append(f"{svc[0].upper() + svc[1:]} near {place}: {len(recs)} verified option{'s' if len(recs) > 1 else ''}.")
        for i, r in enumerate(recs):
            line = (f"{ordinal[i]}, {r['tier_label'].lower()}: {r['name']}, {_km(r['distance_km'])}, "
                    f"{r['confidence'].lower()} confidence, evidence in its {_fields(r)}.")
            c = _plain_caution(r)
            if i == 0 and c:
                line += f" Caution: {c}."
            if i == 0 and r.get("phone"):
                line += f" Phone {_say_phone(r['phone'])}."
            parts.append(line)
        if skipped:
            s0 = skipped[0]
            parts.append(f"I skipped {s0['name']}, {_km(s0['distance_km'])}, because {_skip_reason(s0)}.")
        parts.append(f"Of {funnel[4]['count']} facilities nearby that mention {svc}, {funnel[6]['count']} passed every check.")
    note = _precision_note(resp)
    if note:
        parts.append(note)
    return " ".join(parts)


PATIENT_SURE = {
    "High": "I'm fairly sure they offer this",
    "Medium": "They probably offer this, but please check when you call",
    "Low": "I'm not sure they offer this, so please check when you call",
}


def _patient(resp: dict) -> str:
    q = resp["query"]
    svc = _say_label(q["service"]["label"])
    place = "you" if q["location"].get("kind") == "coordinates" else q["location"]["display_name"]
    recs = resp["recommendations"]
    parts: list[str] = []
    if q.get("urgency") == "emergency":
        parts.append("If this is life-threatening, call 108 for an ambulance right away.")
    if not recs:
        far = resp.get("nearest_beyond_radius") or []
        parts.append(f"I'm sorry, I couldn't find a place close to {place} that I can confirm offers {svc}.")
        if far:
            r = far[0]
            parts.append(f"The nearest one I can confirm is {r['name']} in {_town(r)}, {_km(r['distance_km'])} away.")
            if r.get("phone"):
                parts.append(f"Please call them first, on {_say_phone(r['phone'])}.")
        parts.append("It's also worth asking at your nearest government district hospital.")
    else:
        top = recs[0]
        parts.append(f"The best place I found for {svc} is {top['name']}, {_km(top['distance_km'])} away.")
        parts.append(PATIENT_SURE[top["confidence"]] + ".")
        c = _plain_caution(top)
        if c:
            parts.append(f"One thing to know: {c}.")
        if top.get("phone"):
            parts.append(f"Call them first on {_say_phone(top['phone'])}, to check they can see you.")
        backup = next((r for r in recs[1:] if r.get("tier") == "nearest_verified"), recs[1] if len(recs) > 1 else None)
        if backup:
            parts.append(f"If you can't reach them, try {backup['name']}, {_km(backup['distance_km'])} away.")
    note = _precision_note(resp)
    if note:
        parts.append(note)
    return " ".join(parts)


def spoken_summary(resp: dict, audience: str | None = None) -> str:
    if audience == "provider":
        return _provider(resp)
    if audience == "patient":
        return _patient(resp)
    text = _general(resp)
    note = _precision_note(resp)
    return f"{text} {note}" if note else text
