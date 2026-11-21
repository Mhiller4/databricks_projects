"""Care Finder decision engine: service + location -> gated, weighted, explained recommendations.

Everything is deterministic. The voice agent and the UI only display what this returns.

    1. Resolve the service (src/hc/care.py match_service) and the location (gold location_lookup).
    2. GATES: a facility can be recommended only if it has direct evidence for the service, record
       trust >= MIN_TRUST, type fit >= MIN_TYPE_FIT, text that is not only a third-party listing, and
       it is within the search radius. Gates come first so no slider setting can surface an
       unverified facility.
    3. WEIGHTS re-rank the facilities that pass the gates:
           score = sum(w_i * component_i) / sum(w_i)
       components (all 0-1): proximity = exp(-km / tau), evidence = evidence_score * type_fit,
       trust = trust_score, depth = clinical depth (beds, doctors, specific claims).
    4. Three tiers (distinct facilities): Best balanced, Nearest verified, Highest-confidence specialist.
    5. Funnel counts, closer facilities we skipped and why, a care-desert alert, and a spoken summary.
"""

from __future__ import annotations

import math
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

try:
    from hc import care  # noqa: E402  (assembled app: hc/ sits next to app/)
except ImportError:  # repo layout: the shared module lives under src/
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from hc import care  # noqa: E402  (shared with the Databricks notebooks; no Spark imports)

from .data import Store  # noqa: E402
from .summary import spoken_summary  # noqa: E402

# ---------------------------------------------------------------------------------------------
# Rules (all shown to the user in the HOW section)
# ---------------------------------------------------------------------------------------------

MIN_TRUST = 0.5
MIN_TYPE_FIT = 0.5
MAX_SEARCH_KM = 300.0
DESERT_SEARCH_KM = 600.0  # when nothing passes nearby, look this far for the nearest verified option

DEFAULT_WEIGHTS = {
    "routine": {"proximity": 0.35, "evidence": 0.30, "trust": 0.20, "depth": 0.15},
    "emergency": {"proximity": 0.50, "evidence": 0.25, "trust": 0.15, "depth": 0.10},
}
# search radius = tau * factor (tau = how far people reasonably travel for the service)
RADIUS_FACTOR = {"routine": 3.0, "emergency": 2.0}

TIERS = (
    ("best_balanced", "Best balanced", "Highest overall score: evidence, trust, depth and distance together."),
    ("nearest_verified", "Nearest verified", "The closest facility that passes every check, with Medium or High confidence if one exists."),
    ("highest_confidence", "Highest-confidence specialist", "The strongest evidence and record trust within the search radius, regardless of distance."),
)

COORD_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


class CareFinderError(Exception):
    def __init__(self, status: str, message: str, **extra):
        super().__init__(message)
        self.status, self.message, self.extra = status, message, extra


# ---------------------------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------------------------


PRECISION = {  # kind -> (label, is_precise)
    "coordinates": ("exact point", True),
    "pin": ("PIN code area", True),
    "post_office": ("locality", True),
    "city": ("city centre", False),
    "district": ("district centre", False),
    "state": ("state centre", False),
}
BIG_CITY_POINTS = 30       # a city with this many facilities is big enough that its centre is a rough point
QUALIFIER_RADIUS_KM = 80   # "Bandra, Mumbai": keep Bandra candidates within this distance of Mumbai
CLARIFY_SPREAD_KM = 50     # same name in places this far apart -> ask which one
MIN_CITY_POINTS = 3        # city points from fewer facility records rank below India Post localities
DIRECTION_SUFFIXES = {"EAST", "WEST", "NORTH", "SOUTH", "CENTRAL", "EASTERN", "WESTERN"}


def _km_between(a: dict, b: dict) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def _lookup(store: Store, name_key: str, prefix: bool) -> list[dict]:
    cols = "kind, name_key, display_name, district, state, state_key, lat, lon, priority, n_points"
    if not prefix:
        return store.query(f"SELECT {cols} FROM location_lookup WHERE name_key = ? ORDER BY priority, n_points DESC LIMIT 60", [name_key])
    return store.query(
        f"SELECT {cols} FROM location_lookup WHERE starts_with(name_key, ?) AND name_key <> ? AND kind NOT IN ('pin', 'state') "
        "ORDER BY priority, n_points DESC LIMIT 60",
        [name_key, name_key],
    )


def _states(store: Store) -> set[str]:
    if not hasattr(store, "_state_keys"):
        store._state_keys = {r["state_key"] for r in store.query("SELECT DISTINCT state_key FROM location_lookup WHERE kind = 'state'")}
    return store._state_keys


def resolve_location(store: Store, q: str | dict) -> list[dict]:
    """Candidates for what the user typed, best first.

    "800001" (PIN), "Andheri" (locality), "Darbhanga, Bihar" (qualifier = state),
    "Bandra, Mumbai" / "Salt Lake, Kolkata" (qualifier = a nearby place), "25.6, 85.1", or {lat, lon}.
    Localities also match by prefix ("Bandra" finds Bandra West and Bandra East).
    """
    if isinstance(q, dict):
        return [{"kind": "coordinates", "display_name": f"{q['lat']:.4f}, {q['lon']:.4f}", "district": None,
                 "state": None, "lat": float(q["lat"]), "lon": float(q["lon"]), "priority": 0, "n_points": 1}]
    raw = (q or "").strip()
    m = COORD_RE.match(raw)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        return [{"kind": "coordinates", "display_name": f"Coordinates {lat}, {lon}", "district": None,
                 "state": None, "lat": lat, "lon": lon, "priority": 0, "n_points": 1}]
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return []
    name_key = care.key(parts[0])
    if not name_key:
        return []

    # qualifiers: a state narrows by state; anything else narrows to places near that place
    state_key, anchor = None, None
    for qual in parts[1:]:
        qk = care.STATE_ALIASES.get(care.key(qual), care.key(qual))
        if qk in _states(store):
            state_key = qk
        elif anchor is None:
            hits = _lookup(store, qk, prefix=False) or _lookup(store, qk, prefix=True)
            hits = [h for h in hits if not state_key or h["state_key"] == state_key]
            anchor = hits[0] if hits else None

    def keep(rows):
        rows = [r for r in rows if not state_key or r["state_key"] == state_key]
        if anchor:
            rows = [r for r in rows if _km_between(r, anchor) <= QUALIFIER_RADIUS_KM]
        return rows

    exact = keep(_lookup(store, name_key, prefix=False))
    partial = keep(_lookup(store, name_key, prefix=True)) if len(name_key) >= 4 else []
    # "Bandra" -> "Bandra West": a direction suffix is the same place, not a fuzzy guess
    variants = [r for r in partial if r["name_key"][len(name_key):] in DIRECTION_SUFFIXES]
    fuzzy = [r for r in partial if r not in variants]
    for r in fuzzy:
        r["display_name"] += " (partial match)"
        r["priority"] += 10
    rows = exact + variants if (exact or variants) else fuzzy
    for r in rows:  # a "city" built from 1-2 facility records is a shakier point than an India Post locality
        if r["kind"] == "city" and (r["n_points"] or 0) < MIN_CITY_POINTS:
            r["priority"] = 4.5
    rows.sort(key=lambda r: (r["priority"], -(r["n_points"] or 0)))
    return rows[:20]


def pick_location(candidates: list[dict], q) -> tuple[dict, list[dict]]:
    """Best candidate, or raise needs_clarification when the name points to places far apart."""
    if not candidates:
        raise CareFinderError("unresolved_location", f"I couldn't find a place called '{q}'. Try a city, district, locality or 6-digit PIN code.")
    best = candidates[0]
    if best["kind"] in ("coordinates", "pin"):
        return best, []
    # candidates as specific as the best one (same kind), plus partial-match localities
    # only places as prominent as the best one compete: a city vs cities, a locality vs localities
    pool = [c for c in candidates if c["kind"] == best["kind"] and "(partial match)" not in c["display_name"]]
    far = [c for c in pool if _km_between(c, best) > CLARIFY_SPREAD_KM]
    if far:
        seen, options = set(), []
        for c in [best] + far:
            base = c["display_name"].replace(" (partial match)", "").split(" (")[0].split(",")[0]
            district = c.get("district")
            label = district if district and care.key(district) != care.key(base) else c.get("state")
            k = (c["state"], label, care.key(base))
            if k in seen:
                continue
            seen.add(k)
            options.append({"display_name": c["display_name"].replace(" (partial match)", ""), "state": c["state"],
                            "district": c.get("district"), "query": f"{base}, {label}"})
            if len(options) >= 5:
                break
        if len(options) > 1:
            raise CareFinderError("needs_clarification", f"'{q}' matches places in different areas. Which one?", options=options)
    return best, candidates[1:6]


def location_precision(loc: dict) -> dict:
    label, precise = PRECISION.get(loc["kind"], ("place", False))
    if loc["kind"] == "city" and (loc.get("n_points") or 0) < BIG_CITY_POINTS:
        precise = True  # a small town's centre is close enough
    return {
        "precision": label,
        "is_precise": precise,
        "ask_for_more_detail": not precise,
        "more_detail_prompt": None if precise else
            f"Distances are measured from the {label} of {loc['display_name'].split(' (')[0]}. "
            "A locality or 6-digit PIN code would give closer, more accurate results.",
    }


# ---------------------------------------------------------------------------------------------
# Type-ahead suggestions (the web location box)
# ---------------------------------------------------------------------------------------------

SUGGEST_MIN_CHARS = 2   # start suggesting at two characters
SUGGEST_LIMIT = 8
SUGGEST_DEDUPE_KM = 2   # same name resolving to nearly the same point (city + post office) = one row


def location_suggest(store: Store, q: str, limit: int = SUGGEST_LIMIT) -> list[dict]:
    """Prefix-match candidates for the location box, best first.

    Only real rows from the gold location_lookup: PIN codes, post-office localities, towns,
    districts. Bigger places (more facility points) rank first; near-duplicate points that
    differ only by kind are collapsed. Precision labels come from location_precision().
    """
    key = care.key(q or "")
    if len(key) < SUGGEST_MIN_CHARS:
        return []
    rows = store.query(
        "SELECT kind, display_name, district, state, state_key, lat, lon, priority, n_points "
        "FROM location_lookup WHERE starts_with(name_key, ?) AND kind <> 'state' "
        "ORDER BY n_points DESC, priority LIMIT 60",
        [key],
    )

    def base_name(name: str) -> str:
        return name.split(" (")[0].split(",")[0]

    kept: list[dict] = []
    for r in rows:
        dup = next(
            (g for g in kept
             if care.key(base_name(g["display_name"])) == care.key(base_name(r["display_name"]))
             and _km_between(g, r) <= SUGGEST_DEDUPE_KM),
            None,
        )
        if dup is None:
            kept.append(r)
    out = []
    for r in kept[:limit]:
        p = location_precision(r)
        out.append({"kind": r["kind"], "display_name": r["display_name"], "district": r["district"],
                    "state": r["state"], "lat": r["lat"], "lon": r["lon"],
                    "precision": p["precision"], "is_precise": p["is_precise"]})
    return out


# ---------------------------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------------------------


def clinical_depth(r: dict) -> float:
    """0-1 from what the record actually states. Unknown counts as 0: no reward for silence."""
    beds = min(1.0, math.log1p(r["capacity"]) / math.log1p(200)) if r.get("capacity") else 0.0
    docs = min(1.0, math.log1p(r["number_doctors"]) / math.log1p(30)) if r.get("number_doctors") else 0.0
    claims = min(1.0, (r["n_direct_snippets"] + (2 if r["has_specifics"] else 0)) / 5)
    return round(0.4 * beds + 0.3 * docs + 0.3 * claims, 3)


def gate_failures(r: dict, radius_km: float) -> list[str]:
    f = []
    if r["evidence_tier"] != "direct":
        f.append("no direct evidence: only a related specialty is listed")
    if r["only_third_party_text"]:
        f.append("the matching text describes another hospital (directory or referral listing)")
    if r["trust_score"] < MIN_TRUST:
        f.append(f"record trust {r['trust_score']:.2f} is below {MIN_TRUST}")
    if r["type_fit"] < MIN_TYPE_FIT:
        f.append(f"facility type fit {r['type_fit']:.2f} is below {MIN_TYPE_FIT}" + (f" ({r['type_fit_note']})" if r.get("type_fit_note") else ""))
    if r["distance_km"] > radius_km:
        f.append(f"{r['distance_km']:.0f} km away, beyond the {radius_km:.0f} km search radius")
    return f


def normalize_weights(w: dict | None, urgency: str) -> dict:
    base = dict(DEFAULT_WEIGHTS[urgency])
    if w:
        for k in base:
            if k in w and w[k] is not None:
                base[k] = max(0.0, float(w[k]))
    total = sum(base.values()) or 1.0
    return {k: round(v / total, 4) for k, v in base.items()}


CALL_AHEAD_MARKERS = ("Call ahead", "Only one field", "coordinates", "PIN", "single web source", "merged", "another facility")


def card(r: dict, weights: dict, tier: tuple | None = None) -> dict:
    comps = r["components"]
    contrib = {k: round(weights[k] * comps[k], 4) for k in weights}
    cautions = list(r.get("cautions") or [])
    return {
        "tier": tier[0] if tier else None,
        "tier_label": tier[1] if tier else None,
        "tier_reason": tier[2] if tier else None,
        "facility_id": r["facility_id"],
        "name": r["name"],
        "facility_type": r["facility_type"],
        "address": r["address"],
        "city": r["city"],
        "district": r["district"],
        "state": r["state"],
        "pin": r["pin"],
        "phone": r["phone"],
        "website": r["website"],
        "lat": r["lat"],
        "lon": r["lon"],
        "distance_km": r["distance_km"],
        "score": r["score"],
        "confidence": r["confidence"],
        "confidence_reason": r["confidence_reason"],
        "why": [
            r["why_evidence"],
            f"{r['distance_km']:.1f} km away (location from {r['location_source']}).",
            *(r.get("supporting_facts") or [])[:3],
        ],
        "score_breakdown": {
            "components": comps,
            "weights": weights,
            "contributions": contrib,
            "formula": "score = Σ weight × component; evidence = evidence_score × type_fit; proximity = exp(−km / τ)",
            "raw": {"evidence_score": r["evidence_score"], "type_fit": r["type_fit"], "trust_score": r["trust_score"],
                    "tau_km": r["tau_km"], "evidence_fields": r["direct_fields"]},
        },
        "citations": [
            {"field": e["field"], "text": e["text"], "third_party": e["third_party"],
             "source_table": "workspace.hc_gold.facility_evidence_snippets"}
            for e in (r.get("top_evidence") or [])
        ],
        "source_urls": list(r.get("source_urls") or []),
        "cautions": cautions,
        "call_ahead": [c for c in cautions if any(m.lower() in c.lower() for m in CALL_AHEAD_MARKERS)],
        "model_drivers": None,  # filled once the ML model is in the index
    }


# ---------------------------------------------------------------------------------------------
# Recommend
# ---------------------------------------------------------------------------------------------

_DIST_SQL = """
round(2 * 6371 * asin(sqrt(pow(sin(radians(i.lat - ?) / 2), 2)
      + cos(radians(?)) * cos(radians(i.lat)) * pow(sin(radians(i.lon - ?) / 2), 2))), 1)
"""


@dataclass
class Request:
    service: str
    location: str | dict
    urgency: str = "routine"
    weights: dict | None = None
    top_n: int = 3
    audience: str | None = None  # 'provider' | 'patient' | None (general)


def recommend(store: Store, req: Request) -> dict:
    t0 = time.perf_counter()
    urgency = req.urgency if req.urgency in DEFAULT_WEIGHTS else "routine"

    m = care.match_service(req.service)
    if m is None:
        raise CareFinderError("unknown_service", f"I don't have '{req.service}' as a service yet.",
                              options=[s.label for s in care.SERVICES])
    svc = m.service
    candidates = resolve_location(store, req.location)
    loc, other_locs = pick_location(candidates, req.location)
    lat, lon = loc["lat"], loc["lon"]

    weights = normalize_weights(req.weights, urgency)
    radius = min(MAX_SEARCH_KM, svc.tau_km * RADIUS_FACTOR[urgency])
    safe_km = svc.tau_km

    rows = store.query(
        f"""SELECT i.*, f.capacity, f.number_doctors, {_DIST_SQL} AS distance_km
            FROM care_finder_index i LEFT JOIN facilities f USING (facility_id)
            WHERE i.service_key = ? AND i.lat IS NOT NULL""",
        [lat, lat, lon, svc.key],
    )
    for r in rows:
        r["gate_failures"] = gate_failures(r, radius)
        depth = clinical_depth(r)
        r["components"] = {
            "proximity": round(math.exp(-r["distance_km"] / r["tau_km"]), 4),
            "evidence": round(r["evidence_score"] * r["type_fit"], 4),
            "trust": r["trust_score"],
            "depth": depth,
        }
        r["score"] = round(sum(weights[k] * r["components"][k] for k in weights), 4)

    # same facility listed twice -> keep its best record
    best: dict[tuple, dict] = {}
    for r in rows:
        k = ((r["name"] or "").upper(), (r["city"] or "").upper())
        if k not in best or (not r["gate_failures"], r["score"]) > (not best[k]["gate_failures"], best[k]["score"]):
            best[k] = r
    rows = list(best.values())

    passed = sorted((r for r in rows if not r["gate_failures"]), key=lambda r: (-r["score"], r["distance_km"]))
    desert_search = False
    if not passed:  # nothing verified nearby: look further so we can say how far the nearest one is
        desert_search = True
        wide = [r for r in rows if gate_failures(r, DESERT_SEARCH_KM) == []]
        passed = sorted(wide, key=lambda r: r["distance_km"])

    # ---- tiers (distinct facilities)
    chosen: list[tuple[tuple, dict]] = []
    used: set[str] = set()
    orderings = {
        "best_balanced": passed,
        "nearest_verified": sorted(passed, key=lambda r: (r["confidence"] == "Low", r["distance_km"])),
        "highest_confidence": sorted(passed, key=lambda r: (-(r["evidence_score"] * r["type_fit"] * r["trust_score"]), r["distance_km"])),
    }
    for tier in TIERS:
        for r in orderings[tier[0]]:
            if r["facility_id"] not in used:
                chosen.append((tier, r))
                used.add(r["facility_id"])
                break
    if desert_search:  # nothing passes nearby: list the nearest verified options, nearest first
        near = sorted(passed, key=lambda r: r["distance_km"])[:3]
        far_tiers = [("nearest_verified", "Nearest verified", "Nothing verified within the search radius; this is the closest facility that passes every check.")]
        far_tiers += [("next_nearest", "Next nearest verified", "The next closest facility that passes every check.")] * 2
        chosen, used = list(zip(far_tiers, near)), {r["facility_id"] for r in near}
    recs = [card(r, weights, tier) for tier, r in chosen[: max(1, req.top_n)]]

    # ---- closer facilities we did not recommend, and why
    lead_km = min((r["distance_km"] for _, r in chosen), default=radius)
    skipped = []
    for r in sorted(rows, key=lambda r: r["distance_km"]):
        if r["distance_km"] >= lead_km or r["facility_id"] in used:
            continue
        reasons = r["gate_failures"] or [f"passes every check but scores lower ({r['score']:.2f})"]
        skipped.append({
            "facility_id": r["facility_id"], "name": r["name"], "facility_type": r["facility_type"],
            "distance_km": r["distance_km"], "lat": r["lat"], "lon": r["lon"], "confidence": r["confidence"],
            "excluded": bool(r["gate_failures"]), "reasons": reasons,
            "evidence": [{"field": e["field"], "text": e["text"]} for e in (r.get("top_evidence") or [])[:1]],
        })
        if len(skipped) >= 6:
            break

    # ---- funnel
    base = store.funnel_base
    in_radius = [r for r in rows if r["distance_km"] <= radius]
    direct_in_radius = [r for r in in_radius if r["evidence_tier"] == "direct" and not r["only_third_party_text"]]
    n_passed_nearby = 0 if desert_search else len(passed)
    funnel = [
        {"stage": "Facility records received", "count": base["raw_records"]},
        {"stage": "After removing exact duplicates", "count": base["unique_records"]},
        {"stage": "Well-formed, with a usable location", "count": base["usable_records"]},
        {"stage": f"Mention {svc.label.lower()} anywhere (incl. related specialty)", "count": len(rows)},
        {"stage": f"Within {radius:.0f} km of {loc['display_name']}", "count": len(in_radius)},
        {"stage": "Direct evidence in their own text", "count": len(direct_in_radius)},
        {"stage": f"Record trust ≥ {MIN_TRUST} and facility type fits", "count": n_passed_nearby},
        {"stage": "Recommended", "count": len(recs) if not desert_search else 0},
    ]

    # ---- care desert
    verified_safe = [r for r in passed if r["distance_km"] <= safe_km] if not desert_search else []
    nearest = min(passed, key=lambda r: r["distance_km"]) if passed else None
    desert = {
        "triggered": not verified_safe,
        "safe_km": safe_km,
        "nearest_verified_km": nearest["distance_km"] if nearest else None,
        "nearest_verified_name": nearest["name"] if nearest else None,
        "message": None,
    }
    if desert["triggered"]:
        desert["message"] = (
            f"No facility in this dataset with verified {svc.label.lower()} evidence within {safe_km:.0f} km of {loc['display_name']}. "
            + (f"The nearest verified option is {nearest['name']}, {nearest['distance_km']:.0f} km away." if nearest
               else f"None found within {DESERT_SEARCH_KM:.0f} km.")
            + " The dataset under-covers government facilities, so check with the district hospital too."
        )

    resp = {
        "status": "ok",
        "query": {
            "service": {"input": req.service, "key": svc.key, "label": svc.label, "matched_by": m.how, "alternatives": m.alternatives,
                        "tau_km": svc.tau_km},
            "location": {"input": req.location, **{k: loc.get(k) for k in ("kind", "display_name", "district", "state", "lat", "lon")},
                         **location_precision(loc), "alternatives": [c["display_name"] for c in other_locs]},
            "audience": req.audience,
            "urgency": urgency,
            "weights": weights,
            "radius_km": radius,
        },
        "method": {
            "gates": [
                "Direct evidence: the service is named in the facility's own procedure, equipment, capability or description text",
                "The matching text is not only a listing about another hospital",
                f"Record trust ≥ {MIN_TRUST} (penalties for location conflicts, thin sources, merged records)",
                f"Facility type fit ≥ {MIN_TYPE_FIT} (a dental clinic offering a NICU fails)",
                f"Within {radius:.0f} km (τ {svc.tau_km:.0f} km × {RADIUS_FACTOR[urgency]:g} for {urgency})",
            ],
            "score": "Σ weight × component over facilities that pass every gate",
            "confidence_rules": [{"level": lv, "rule": rule} for lv, rule in care.CONFIDENCE_RULES],
        },
        "funnel": funnel,
        "recommendations": recs if not desert_search else [],
        "nearest_beyond_radius": recs if desert_search else [],
        "ranked": [card(r, weights) for r in (passed[:10] if not desert_search else [])],
        "skipped_nearby": skipped,
        "medical_desert_alert": desert,
    }
    resp["spoken_summary"] = spoken_summary(resp, req.audience)
    resp["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return resp
