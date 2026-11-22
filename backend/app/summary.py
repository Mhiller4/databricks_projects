"""What the voice agent says, written from engine output by fixed templates (never by the LLM).

Three layers, so a caller gets a short answer first and the detail only when they ask:

    answer  where to go, one alternative, and how sure we are          (said straight away)
    why     the evidence, sources, cautions, how we narrowed it down   ("why?", "how do you know?")
    more    the other options and the closer places we left out        ("anything else?", "other options?")

Style: plain spoken English, short sentences, no dashes or lists, numbers said the way people say
them. Every fact comes from the response; nothing is added.
"""

from __future__ import annotations

import re

FIELD_WORDS = {"procedure": "procedures", "equipment": "equipment list", "capability": "list of services", "description": "description"}

# Gold-table cautions in the words a helpline nurse would use (first match wins)
PLAIN_CAUTIONS = (
    ("coordinates", "their map pin doesn't quite match their PIN code, so check the address before you set off"),
    ("is not in the india post", "their PIN code isn't in the postal directory, so check the address"),
    ("single web source", "everything I know about them comes from one website"),
    ("indirect evidence", "they list a related department but never mention this service by name"),
    ("another hospital", "the mention reads like it's about a different hospital"),
    ("merged", "their listing may be mixed up with another place"),
    ("beds but only", "their bed and doctor numbers don't add up"),
    ("almost no supporting detail", "there's very little detail in their listing"),
    ("disagrees with the pin", "their address and PIN code point to different states"),
    ("looks like the same facility", "they might be listed twice"),
)

SKIP_REASONS = (
    ("no direct evidence", "it only lists a related department"),
    ("another hospital", "the mention seems to be about a different hospital"),
    ("record trust", "its record has too many problems to rely on"),
    ("type fit", "it isn't the kind of place that usually does this"),
    ("scores lower", "the evidence for it was weaker"),
)


def say_service(label: str) -> str:
    """'NICU (newborn intensive care)' -> 'NICU'; acronyms stay upper-case so TTS spells them."""
    base = re.sub(r"\s*\(.*?\)", "", label).split(" / ")[0].strip()
    return " ".join(w if w.isupper() else w.lower() for w in base.split())


def say_phone(p: str | None) -> str | None:
    """'+916272233684' -> '+91 62722 33684', read in digit groups."""
    if not p:
        return None
    d = re.sub(r"\D", "", p)
    return f"+91 {d[2:7]} {d[7:]}" if len(d) == 12 and d.startswith("91") else p


def say_km(x: float) -> str:
    if x < 1:
        return "less than a kilometre away"
    if x < 10:
        return f"about {x:.1f} kilometres away"
    return f"about {x:.0f} kilometres away"


def say_name(r: dict) -> str:
    """'Lilavati Hospital and Research Centre, Mumbai, India' -> 'Lilavati Hospital and Research Centre'."""
    name = re.sub(r",\s*India\s*$", "", r["name"] or "").strip()
    for place in (r.get("city"), r.get("district"), r.get("state")):
        if place:
            name = re.sub(rf",\s*{re.escape(place)}\s*$", "", name, flags=re.I).strip()
    return name


def _same_place(a: str, b: str) -> bool:
    a, b = re.sub(r"[^a-z0-9]", "", a.lower()), re.sub(r"[^a-z0-9]", "", b.lower())
    return bool(a) and bool(b) and (a.startswith(b) or b.startswith(a))


def _skipped(resp: dict, recs: list[dict], excluded_only: bool = False) -> list[dict]:
    """Skipped facilities, minus any that are another record of a place we recommend."""
    names = [r["name"] for r in recs]
    return [s for s in resp.get("skipped_nearby") or []
            if (s.get("excluded") or not excluded_only) and not any(_same_place(s["name"], n) for n in names)]


def _town(r: dict) -> str | None:
    return r.get("city") or r.get("district") or r.get("state")


def _place(resp: dict) -> str:
    loc = resp["query"]["location"]
    return "your location" if loc.get("kind") == "coordinates" else loc["display_name"].split(" (")[0]


def _plain_caution(r: dict) -> str | None:
    for c in (r.get("call_ahead") or []) + (r.get("cautions") or []):
        for marker, plain in PLAIN_CAUTIONS:
            if marker in c.lower():
                return plain
    return None


def _skip_reason(s: dict) -> str:
    r = (s.get("reasons") or [""])[0].lower()
    return next((plain for marker, plain in SKIP_REASONS if marker in r), r)


def _fields(r: dict) -> list[str]:
    return [FIELD_WORDS.get(f, f) for f in r["score_breakdown"]["raw"].get("evidence_fields") or []]


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _sure(r: dict, svc: str) -> str:
    """How sure we are, said the way a person would say it."""
    n = len(_fields(r))
    return {
        "High": f"My sources mention {svc} there in {'several places' if n >= 3 else 'more than one place'}, so I'm fairly confident about this one.",
        "Medium": f"My sources say they do {svc}, but I'd give them a quick call to check first.",
        "Low": f"I've only seen {svc} mentioned once for them, so please call and confirm before you go.",
    }[r["confidence"]]


def _recs(resp: dict) -> tuple[list[dict], bool]:
    nearby = resp.get("recommendations") or []
    return (nearby, False) if nearby else (resp.get("nearest_beyond_radius") or [], True)


def _alternative(recs: list[dict]) -> dict | None:
    return next((r for r in recs[1:] if r.get("tier") == "nearest_verified"), recs[1] if len(recs) > 1 else None)


# ---------------------------------------------------------------------------------------------
# Layer 1: the answer
# ---------------------------------------------------------------------------------------------


def spoken_answer(resp: dict, audience: str | None = None) -> str:
    svc = say_service(resp["query"]["service"]["label"])
    place = _place(resp)
    recs, beyond = _recs(resp)
    parts: list[str] = []
    if audience == "patient" and resp["query"].get("urgency") == "emergency":
        parts.append("If it's life-threatening, please call 108 for an ambulance first.")

    if not recs:
        parts.append(f"I'm sorry, I couldn't find anywhere near {place} that I can confirm does {svc}.")
        parts.append("My list has few government hospitals, so it's worth asking at the nearest district hospital.")
        return " ".join(parts)

    top = recs[0]
    town = _town(top)
    where = f" in {town}" if town else ""
    if beyond:
        parts.append(f"I'm sorry, I could not find anywhere close to {place} that I can confirm does {svc}.")
        parts.append(f"The nearest one I can vouch for is {say_name(top)}{where}, {say_km(top['distance_km'])}.")
    else:
        parts.append(f"For {svc} near {place}, I'd go to {say_name(top)}{where}. It's {say_km(top['distance_km'])}.")
    parts.append(_sure(top, svc))

    alt = _alternative(recs)
    if alt:
        how_far = say_km(alt["distance_km"])
        if alt["distance_km"] < top["distance_km"]:
            parts.append(f"If you can't get there, {say_name(alt)} is closer, {how_far}.")
        else:
            parts.append(f"If you can't get there, {say_name(alt)} is another good option, {how_far}.")
    if beyond:
        parts.append("My list has few government hospitals, so the district hospital is worth asking too.")

    loc = resp["query"]["location"]
    if loc.get("ask_for_more_detail"):
        city = loc["display_name"].split(" (")[0].split(",")[0]
        parts.append(f"I measured from the middle of {city}. If you tell me the area or PIN code, I can narrow it down.")
    return " ".join(parts)


# ---------------------------------------------------------------------------------------------
# Layer 2: why (everything about the top pick and how it was chosen)
# ---------------------------------------------------------------------------------------------

FACT_REWRITES = (
    ("Built from", "Their record pulls together"),
    ("independent web sources", "separate websites"),
    ("Also listed in", "They're also listed in"),
    (" (an independent source)", ", which is a separate source"),
    ("doctor(s)", "doctors"),
    ("Lists 1 doctors", "Lists 1 doctor"),
    ("Lists ", "They list "),
    ("Established ", "They opened in "),
    ("Coordinates match the PIN code area.", "Their map location matches their PIN code."),
    ("Phone number listed.", ""),
)


def _fact(f: str) -> str:
    for a, b in FACT_REWRITES:
        f = f.replace(a, b)
    return f.strip()


def spoken_why(resp: dict, audience: str | None = None) -> str:
    recs, beyond = _recs(resp)
    if not recs:
        return ("I didn't find a facility nearby whose own listing mentions this service and whose record I trust. "
                "There may still be one. My list mostly covers private hospitals with a website.")
    svc = say_service(resp["query"]["service"]["label"])
    top = recs[0]
    parts = [f"Here's why I picked {say_name(top)}."]

    fields = _fields(top)
    if fields:
        parts.append(f"Their own listing mentions {svc} in their {_join(fields)}.")
    quote = next((c["text"] for c in top.get("citations") or [] if c.get("field") != "specialties"), None)
    if quote:
        parts.append(f"One line says: \"{quote.rstrip('.')}\".")

    for f in (top.get("why") or [])[2:6]:  # supporting facts: sources, directory listing, beds, doctors, year
        f = _fact(f)
        if f:
            parts.append(f)

    caution = _plain_caution(top)
    if caution:
        parts.append(f"One thing to know: {caution}.")

    funnel = resp.get("funnel") or []
    if len(funnel) >= 7 and not beyond:
        parts.append(f"I looked at {funnel[4]['count']} places near you that mention {svc}. "
                     f"{funnel[5]['count']} of them describe actually doing it, and {funnel[6]['count']} of those also have a record I trust.")
        parts.append("From those, I picked the best balance of distance, strength of evidence, how reliable the record is, and the size of the place.")
    elif len(funnel) >= 7:
        near = funnel[4]["count"]
        parts.append(f"Near you I found {near} place{'s' if near != 1 else ''} that mention {svc}, but none describe actually doing it with a record I trust. "
                     "So I searched further out and picked the nearest one that does.")

    skipped = _skipped(resp, recs, excluded_only=True)
    if skipped:
        s0 = skipped[0]
        parts.append(f"I passed over {say_name(s0)}, which is closer, because {_skip_reason(s0)}.")
    phone = say_phone(top.get("phone"))
    parts.append(f"Their number is {phone}." if phone else "I don't have a phone number for them.")
    return " ".join(parts)


# ---------------------------------------------------------------------------------------------
# Layer 3: more options
# ---------------------------------------------------------------------------------------------


def spoken_more(resp: dict, audience: str | None = None) -> str:
    recs, _ = _recs(resp)
    svc = say_service(resp["query"]["service"]["label"])
    alt = _alternative(recs)
    extra = [r for r in recs[1:] if r is not alt]
    parts: list[str] = []
    for r in extra:
        line = f"{say_name(r)} is {say_km(r['distance_km'])}."
        if r.get("tier") == "highest_confidence":
            line = f"{say_name(r)} is further, {say_km(r['distance_km'])}, but it has the strongest evidence for {svc} of anywhere I checked."
        parts.append(line)
    skipped = _skipped(resp, recs)[:2]
    if skipped:
        parts.append("There are a couple of closer places I left out." if len(skipped) > 1 else "There's one closer place I left out.")
        for s in skipped:
            parts.append(f"{say_name(s)}, {say_km(s['distance_km'])}, because {_skip_reason(s)}.")
    if not parts:
        return f"Those are the only places near you I can confirm for {svc}."
    return " ".join(parts)


# ---------------------------------------------------------------------------------------------
# Used by the engine
# ---------------------------------------------------------------------------------------------


def spoken(resp: dict, audience: str | None = None) -> dict:
    return {"answer": spoken_answer(resp, audience), "why": spoken_why(resp, audience), "more": spoken_more(resp, audience)}


def spoken_summary(resp: dict, audience: str | None = None) -> str:
    """The short answer (kept under this name for the UI and older callers)."""
    return spoken_answer(resp, audience)
