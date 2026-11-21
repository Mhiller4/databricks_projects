# Databricks notebook source
# MAGIC %md
# MAGIC # Silver 16 · IHDS-II medical facility survey, decoded → `hc_silver.ext_ihds_facilities`
# MAGIC
# MAGIC India Human Development Survey 2011-12 (ICPSR 36151 DS6): 4,447 facilities, half government and half
# MAGIC private, each asked which services it provides and which equipment works. Codes are decoded with
# MAGIC `src/hc/ihds.py` (built from the codebook PDF in the landing volume).
# MAGIC
# MAGIC Columns: facility type and ownership, our facility-type bucket (`our_type`), beds, one boolean per
# MAGIC service (`svc_*`) and equipment item (`eq_*`), and `offers_<service>` proxies for Care Finder services.

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

from hc import ihds
from hc.io import write_table
from hc.naming import snake

B, S = cfg.bronze, cfg.silver
raw = spark.table(B("ext_ihds_medical_facilities"))


def num(code):
    return F.expr(f"try_cast(nullif(trim({snake(code)}), '') AS INT)")


def flag(code):
    v = num(code)
    return F.when(v == 1, True).when(v == 0, False)


types = F.create_map(*[x for c, (label, _, _) in ihds.FACILITY_TYPES.items() for x in (F.lit(c), F.lit(label))])
owner_by_type = F.create_map(*[x for c, (_, o, _) in ihds.FACILITY_TYPES.items() if o for x in (F.lit(c), F.lit(o))])
our_type = F.create_map(*[x for c, (_, _, t) in ihds.FACILITY_TYPES.items() if t for x in (F.lit(c), F.lit(t))])
states = F.create_map(*[x for c, s in ihds.STATES.items() for x in (F.lit(c), F.lit(s))])

ftype = num(ihds.FACILITY_TYPE)
cols = [
    F.concat_ws("-", *[F.col(c) for c in ("stateid", "distid", "psuid", "clinicid")]).alias("ihds_facility_id"),
    num("STATEID").alias("state_code_2001"),
    states[num("STATEID")].alias("state"),
    num("DISTID").alias("district_id"),
    ftype.alias("facility_type_code"),
    types[ftype].alias("facility_type"),
    F.coalesce(owner_by_type[ftype], F.when(num(ihds.OWNERSHIP) == 1, "public").when(num(ihds.OWNERSHIP) == 0, "private")).alias("ownership"),
    our_type[ftype].alias("our_type"),
    num(ihds.BEDS).alias("beds"),
    num(ihds.YEAR_OPENED).alias("year_opened"),
    num(ihds.KM_TO_DISTRICT_HOSPITAL).alias("km_to_district_hospital"),
    num(ihds.KM_TO_CHC).alias("km_to_chc"),
]
cols += [flag(c).alias("svc_" + snake(label)) for c, label in ihds.SERVICES.items()]
cols += [flag(c).alias("eq_" + snake(label)) for c, label in ihds.EQUIPMENT.items()]
for svc, rule in ihds.SERVICE_PROXIES.items():
    conds = [flag(c) for c in rule["all"]]
    both = conds[0]
    for c in conds[1:]:
        both = both & c
    cols.append(both.alias(f"offers_{svc}"))

out = raw.where(num("SURVEY") == 2).select(*cols)
write_table(out, S("ext_ihds_facilities"))
spark.sql(
    f"COMMENT ON TABLE {S('ext_ihds_facilities')} IS 'IHDS-II 2011-12 medical facility survey (ICPSR 36151 DS6), decoded. "
    "svc_*/eq_* = facility says it provides the service / has the equipment working. offers_* = Care Finder service proxies (src/hc/ihds.py).'"
)

# COMMAND ----------

display(spark.sql(f"SELECT facility_type, ownership, our_type, count(*) n FROM {S('ext_ihds_facilities')} GROUP BY ALL ORDER BY n DESC"))
