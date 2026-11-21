"""Spoken summary for the phone agent: a fixed template filled with engine output, never LLM-written.

Target: 30-45 seconds read aloud (about 80-110 words). Numbers are spoken plainly.
"""

from __future__ import annotations

import re


def _km(x: float) -> str:
    return f"{x:.0f} kilometres" if x >= 10 else f"{x:.1f} kilometres"


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


def _first_caution(rec: dict) -> str | None:
    c = (rec.get("call_ahead") or rec.get("cautions") or [None])[0]
    return c.rstrip(".") if c else None


def spoken_summary(resp: dict) -> str:
    q = resp["query"]
    svc = _say_label(q["service"]["label"])
    place = "your location" if q["location"].get("kind") == "coordinates" else q["location"]["display_name"]
    recs = resp["recommendations"]
    desert = resp["medical_desert_alert"]
    parts: list[str] = []

    if not recs:
        far = resp.get("nearest_beyond_radius") or []
        parts.append(f"I could not find a facility with verified {svc} near {place} in our data.")
        if far:
            r = far[0]
            parts.append(f"The nearest verified option is {r['name']} in {r['city'] or r['district'] or r['state']}, {_km(r['distance_km'])} away.")
            if r.get("phone"):
                parts.append(f"Their listed phone number is {_say_phone(r['phone'])}. Please call before travelling.")
        parts.append("Our data has few government hospitals, so please also check with the district hospital.")
        return " ".join(parts)

    top = recs[0]
    parts.append(f"For {svc} near {place}, my best recommendation is {top['name']}, {_km(top['distance_km'])} away.")
    parts.append(top["why"][0])
    parts.append(f"Confidence is {top['confidence'].lower()}.")
    caution = _first_caution(top)
    if caution:
        parts.append(f"One caution: {caution}.")
    if top.get("phone"):
        parts.append(f"Call ahead on {_say_phone(top['phone'])}.")
    others = [r for r in recs[1:] if r.get("tier_label")]
    if others:
        parts.append("Other options: " + "; ".join(f"{r['tier_label'].lower()}, {r['name']}, {_km(r['distance_km'])}" for r in others) + ".")
    if desert["triggered"]:
        parts.append(f"Note that nothing verified is within {desert['safe_km']:.0f} kilometres.")
    checked = resp["funnel"][3]["count"]
    parts.append(f"I checked {checked} facilities that mention {svc}, and kept only those with direct evidence and a trustworthy record.")
    return " ".join(parts)
