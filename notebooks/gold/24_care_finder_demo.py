# Databricks notebook source
# MAGIC %md
# MAGIC # Gold 24 · Care Finder demo: the brief's scenarios, end to end
# MAGIC
# MAGIC Change the two widgets to ask your own question. Each result shows **why** (evidence quoted from the
# MAGIC facility record, with its source field), **how** (the score components), and **cautions**.

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

G = cfg.gold
service = widget(dbutils, "service", "dialysis", "service (e.g. dialysis, NICU, C-section, MRI)")
location = widget(dbutils, "location", "Darbhanga, Bihar", "city / district / PIN / 'lat, lon'")


def ask(service, location, top_n=5):
    cands = spark.sql(f"SELECT * FROM {G('resolve_location')}(:q)", args={"q": location}).collect()
    if not cands:
        print(f"Could not find '{location}'. Try a PIN code, a district name, or 'lat, lon'.")
        return None
    best = cands[0]
    others = [c.display_name for c in cands[1:4]]
    print(f"Service: {service} · Location: {best.display_name} ({best.lat:.3f}, {best.lon:.3f})")
    if others:
        print("  also matched:", "; ".join(others))
    res = spark.sql(
        f"SELECT * FROM {G('recommend_facilities')}(:s, :lat, :lon, :n)",
        args={"s": service, "lat": float(best.lat), "lon": float(best.lon), "n": top_n},
    )
    if res.isEmpty():
        print("  No facility with any evidence for this service within 300 km (or the service name was not recognised).")
        return None
    return res


r = ask(service, location)
if r is not None:
    display(r.select("result_rank", "name", "confidence", "distance_km", "score", "why", "evidence", "cautions",
                     "evidence_score", "type_fit", "trust_score", "distance_score", "phone", "address", "source_urls"))

# COMMAND ----------

# MAGIC %md ## The brief's three users

# COMMAND ----------

SCENARIOS = [
    ("Community health worker, rural Bihar: dialysis", "dialysis", "Darbhanga, Bihar"),
    ("NGO coordinator, Maharashtra: high-risk delivery", "emergency c-section", "Nanded, Maharashtra"),
    ("District planner: trauma from a highway hotspot (NH-19 near Agra)", "trauma", "27.18, 78.02"),
    ("MRI near a PIN code (Jaipur)", "mri", "302001"),
    ("NICU near Lucknow", "nicu", "Lucknow"),
]
for title, svc, loc in SCENARIOS:
    print("\n" + "=" * 100 + f"\n{title}")
    r = ask(svc, loc, 3)
    if r is not None:
        for row in r.collect():
            print(f"\n  #{row.result_rank} {row.name}  [{row.confidence}]  {row.distance_km} km  score {row.score}")
            print(f"     WHY: {row.why}")
            for e in row.evidence or []:
                print(f"       - {e.field}: \"{e.text[:160]}\"" + ("  (reads like a listing about another hospital)" if e.third_party else ""))
            print(f"     HOW: evidence {row.evidence_score} x type fit {row.type_fit} x trust {row.trust_score} x distance {row.distance_score}")
            for c in (row.cautions or [])[:3]:
                print(f"     CAUTION: {c}")
