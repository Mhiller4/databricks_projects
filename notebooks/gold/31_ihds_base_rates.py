# Databricks notebook source
# MAGIC %md
# MAGIC # Gold 31 · What do facilities of each type actually offer? (IHDS-II survey base rates)
# MAGIC
# MAGIC | Output | What |
# MAGIC |---|---|
# MAGIC | `hc_gold.ihds_service_base_rates` | share of facilities offering each service proxy, by facility type and ownership |
# MAGIC | `hc_gold.ihds_type_fit_check` | survey-based plausibility of hospital-level services per facility type, next to Care Finder's `TYPE_FIT` prior |
# MAGIC
# MAGIC Care Finder's type fit (`src/hc/care.py`) was set by judgement: a clinic claiming a hospital-level service
# MAGIC (C-section, blood transfusion, ICU…) gets 0.6. The survey shows how often each facility type really offers
# MAGIC these, relative to hospitals. The check table only **reports** the gap. Changing `TYPE_FIT` is a team
# MAGIC decision. Caveats: 2011-12, sampled near IHDS households, proxies for some services (see `ihds.SERVICE_PROXIES`).

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

import pandas as pd

from hc import care, ihds
from hc.io import write_table

S, G = cfg.silver, cfg.gold
pdf = spark.table(S("ext_ihds_facilities")).toPandas()
pdf = pdf[pdf["our_type"].notna()]
offer_cols = [c for c in pdf.columns if c.startswith("offers_")]
pdf[offer_cols] = pdf[offer_cols].astype("float")  # True/False/None -> 1.0/0.0/NaN

rows = []
for (t, own), g in pdf.groupby(["our_type", "ownership"]):
    for svc, rule in ihds.SERVICE_PROXIES.items():
        col = f"offers_{svc}"
        v = g[col].dropna().astype(float)
        rows.append({"our_type": t, "ownership": own, "service_key": svc, "proxy": rule["note"],
                     "n_facilities": int(len(v)), "pct_offering": round(100 * v.mean(), 1) if len(v) else None})
rates = pd.DataFrame(rows)
write_table(spark.createDataFrame(rates), G("ihds_service_base_rates"))
spark.sql(
    f"COMMENT ON TABLE {G('ihds_service_base_rates')} IS 'IHDS-II 2011-12: share of surveyed facilities offering each Care Finder service proxy, "
    "by facility type and ownership.'"
)

# Relative plausibility of hospital-level services, pooled over ownership: rate(type) / rate(hospital)
hosp_level = [s.key for s in care.SERVICES if s.needs_hospital and s.key in ihds.SERVICE_PROXIES]
pooled = pdf.groupby("our_type")[[f"offers_{s}" for s in hosp_level]].mean()
rel = pooled.div(pooled.loc["hospital"]).mean(axis=1)
check = pd.DataFrame({
    "our_type": rel.index,
    "survey_relative_rate": rel.round(3).values,
    "services_compared": ", ".join(hosp_level),
    "current_type_fit_hospital_services": [care.TYPE_FIT.get(t, care.TYPE_FIT[None])[0] for t in rel.index],
    "n_facilities": pdf.groupby("our_type").size().reindex(rel.index).values,
})
check["gap"] = (check["current_type_fit_hospital_services"] - check["survey_relative_rate"]).round(3)
write_table(spark.createDataFrame(check), G("ihds_type_fit_check"))
spark.sql(
    f"COMMENT ON TABLE {G('ihds_type_fit_check')} IS 'Survey-based relative rate of hospital-level services by facility type (hospital = 1) "
    "vs the TYPE_FIT prior in src/hc/care.py. Report only; TYPE_FIT is changed by the team, not here.'"
)
display(spark.table(G("ihds_type_fit_check")))
display(spark.table(G("ihds_service_base_rates")).orderBy("service_key", "our_type", "ownership"))
