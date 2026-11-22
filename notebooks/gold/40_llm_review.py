# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "6"
# ///
# MAGIC %md
# MAGIC # Gold 40 · LLM review layer on top of Care Finder
# MAGIC
# MAGIC Mekeli's rules pipeline (`care_finder_index`, `facility_trust`, `recommend_facilities()`) scores
# MAGIC 40k facility x service pairs with regex evidence. This notebook adds what rules cannot do:
# MAGIC
# MAGIC 1. **Read the sentence**: "NICU facility not available", "coming soon", "referred externally"
# MAGIC 2. **Check against Government of India guidelines**: which required elements are present / missing
# MAGIC 3. **Prove it**: every LLM answer must quote the record; code checks the quote exists
# MAGIC 4. **Rate sources**: travel-site-only records, research-paper text, dated (COVID-era) pages
# MAGIC
# MAGIC **Writes only new objects** (nothing of Mekeli's is modified):
# MAGIC
# MAGIC | Object | What it is |
# MAGIC |---|---|
# MAGIC | `hc_gold.guideline_rules` | Required elements per service, with the guideline they come from |
# MAGIC | `hc_gold.facility_source_quality` | Per facility: best source tier A-D, travel-only, freshness, ownership |
# MAGIC | `hc_gold.llm_review_queue` | Which facility x service rows the LLM reviews, and why |
# MAGIC | `hc_gold.llm_review` | Raw + parsed LLM answers, grounding check (resumable, appended in batches) |
# MAGIC | `hc_gold.care_finder_index_v2` | Mekeli's index + LLM verdict + adjusted score/confidence + extra cautions |
# MAGIC | `hc_gold.recommend_facilities_v2()` | Same inputs as `recommend_facilities()`, ranks on the adjusted score |
# MAGIC | `hc_gold.llm_review_changes` | What the LLM changed vs rules only (for the slides) |
# MAGIC | `hc_gold.audit_sample` | 50 stratified rows for the manual audit / phone calls |
# MAGIC
# MAGIC **Before running:** open **Serving** in the left sidebar and copy the name of a `databricks-` chat model
# MAGIC into `MODEL` below. Run cell "Smoke test" first.

# COMMAND ----------

from pyspark.sql import functions as F, Window
import json

CATALOG = "workspace"
GOLD = f"{CATALOG}.hc_gold"
SILVER = f"{CATALOG}.hc_silver"
INDEX = f"{GOLD}.care_finder_index"
FACILITIES = f"{SILVER}.vf_facilities"
REVIEW = f"{GOLD}.llm_review"
MODEL = "databricks-meta-llama-3-3-70b-instruct"   # replace with the name from the Serving page
MAX_REVIEW_ROWS = 200
BATCH_SIZE = 200            # rows per ai_query batch; the loop is resumable
MAX_TEXT_CHARS = 6000       # facility text sent per prompt
USE_RESPONSE_FORMAT = True  # set False if the model rejects JSON-schema output (errors in llm_review.error)

def save(df, name):
    df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(name)
    print(f"wrote {name}: {spark.table(name).count():,} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Smoke test: is ai_query available with this model?

# COMMAND ----------

display(spark.sql(f"""
SELECT ai_query('{MODEL}', 'Reply with the single word: ready',
                modelParameters => named_struct('temperature', 0.0, 'max_tokens', 5)) AS answer
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1 - Guideline rules (one row per service)
# MAGIC Required elements a facility must show for a confident "yes", from Government of India norms.
# MAGIC `high_acuity` services are emergencies where a false positive is dangerous.

# COMMAND ----------

RULES = [
    # service_key, guideline, high_acuity, required elements
    ("emergency_c_section", "FRU / CEmONC guidelines (NHM)", True,
     ["obstetrician or CEmONC-trained doctor", "anaesthetist or LSAS-trained doctor", "operation theatre",
      "blood bank or blood storage unit", "24x7 availability"]),
    ("maternity_delivery", "IPHS 2022 / LaQshya", False,
     ["labour room or delivery room", "obstetrician, doctor or trained nurse-midwife", "newborn care"]),
    ("nicu", "Facility-based newborn care (SNCU) guidelines", True,
     ["newborn intensive or special care unit", "radiant warmers, incubators or phototherapy",
      "paediatrician or neonatologist", "round-the-clock care", "oxygen, CPAP or ventilator"]),
    ("icu", "IPHS 2022 critical care norms", True,
     ["ICU or HDU beds", "ventilators", "patient monitors", "doctors available 24x7", "oxygen supply"]),
    ("dialysis", "Pradhan Mantri National Dialysis Programme guidelines", True,
     ["haemodialysis machines or dialysis unit", "nephrologist or trained dialysis technician",
      "RO water treatment plant"]),
    ("trauma_care", "Trauma care facility norms (NPPMT&BI) / IPHS 2022", True,
     ["24x7 emergency", "operation theatre", "orthopaedic or general surgeon", "X-ray or CT imaging", "blood bank"]),
    ("emergency_department", "IPHS 2022 emergency norms", True,
     ["24x7 emergency or casualty", "doctor on duty", "resuscitation equipment or oxygen", "ambulance or triage"]),
    ("blood_bank", "Drugs and Cosmetics Rules (licensed blood centre / storage unit)", True,
     ["licensed blood bank or blood storage unit", "blood storage or component equipment"]),
    ("cardiac_cath", "PM-JAY specialty criteria (cardiology)", True,
     ["cath lab", "interventional cardiologist", "angiography or angioplasty performed", "ICU or CCU"]),
    ("cardiac_surgery", "PM-JAY specialty criteria (CTVS)", True,
     ["cardiothoracic surgeon", "cardiac operation theatre", "heart-lung machine or perfusion", "cardiac ICU"]),
    ("burn_care", "Burn unit norms (NPPMT&BI)", True,
     ["burn unit or burn ward", "plastic or general surgeon", "ICU or HDU"]),
    ("chemotherapy", "PM-JAY specialty criteria (medical oncology)", False,
     ["medical oncologist", "chemotherapy or day-care oncology unit"]),
    ("radiotherapy", "AERB licensing / PM-JAY radiation oncology", False,
     ["LINAC, cobalt or brachytherapy unit", "radiation oncologist"]),
    ("ct_scan", "AERB registration", False, ["CT scanner", "radiologist"]),
    ("mri", "Standard diagnostic norms", False, ["MRI machine", "radiologist"]),
    ("cataract_surgery", "National Programme for Control of Blindness norms", False,
     ["ophthalmologist", "eye operation theatre or operating microscope"]),
]
rules = spark.createDataFrame(
    [(k, g, h, r, len(r)) for k, g, h, r in RULES],
    "service_key string, guideline string, high_acuity boolean, required_elements array<string>, n_required int")
save(rules, f"{GOLD}.guideline_rules")
missing = (spark.table(f"{GOLD}.service_catalog").select("service_key")
           .join(rules, "service_key", "left_anti").collect())
print("services in service_catalog without a guideline rule:", [r.service_key for r in missing])

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2 - Source quality, freshness, ownership (per facility)
# MAGIC `facility_trust` counts sources; this rates **what kind** they are.
# MAGIC | Tier | Meaning |
# MAGIC |---|---|
# MAGIC | A | Government site or the facility's own site |
# MAGIC | B | Health directory (practo, justdial, lybrate...) |
# MAGIC | C | Social, general, research papers |
# MAGIC | D | Unrelated to care (travel, real estate, company data) |

# COMMAND ----------

TIER_D = ["makemytrip", "goibibo", "booking.com", "tripadvisor", "agoda", "oyorooms", "cleartrip", "yatra.com",
          "trivago", "proptiger", "magicbricks", "99acres", "housing.com", "zoominfo", "tracxn", "nobroker"]
TIER_B = ["practo", "justdial", "lybrate", "docindia", "medindia", "onefivenine", "hexahealth", "medicineindia",
          "credihealth", "drlogy", "ayushmancardhospitals", "healthinsuranceindia", "policyx", "whatclinic",
          "cardiologistindia", "eka.care", "1mg.com", "apollo247", "medifee", "mediyaar", "clinicspots", "sehat"]
TIER_A_GOV = [".gov.in", ".nic.in", ".gov", "nhsrcindia", "pmjay", "abdm", "mohfw"]
RESEARCH = ["pubmed", "ncbi.nlm.nih.gov", "researchgate", "springer", "sciencedirect", "wiley", "jamanetwork"]
HEALTH_WORDS = r"(hospital|clinic|health|care|medical|dental|nursing|diagnostic|surgical|maternity|ortho|eye)"

def any_in(col, items):
    c = F.lit(False)
    for s in items:
        c = c | col.contains(s)
    return c

as_array = lambda c: F.coalesce(F.from_json(F.col(c), "array<string>"),
                                F.when(F.col(c).isNotNull(), F.array(F.col(c))),
                                F.array().cast("array<string>"))
domain_of = lambda c: F.regexp_extract(F.lower(c), r"^(?:[a-z]+://)?(?:www\.)?([^/:?#\s]+)", 1)

fac = spark.table(FACILITIES)
urls = (fac.select(F.col("unique_id").alias("facility_id"), domain_of(F.col("official_website")).alias("own"),
                   F.explode(F.concat(as_array("source_urls"), as_array("websites"), as_array("official_website"))).alias("url"))
           .withColumn("domain", domain_of(F.col("url"))).where("domain <> ''"))
d = F.col("domain")
urls = urls.withColumn("tier",
    F.when(any_in(d, TIER_D), "D").when(any_in(d, RESEARCH), "C").when(any_in(d, TIER_B), "B")
     .when(any_in(d, TIER_A_GOV), "A").when((F.col("own") != "") & (d == F.col("own")), "A")
     .when(d.rlike(HEALTH_WORDS), "A").otherwise("C"))

tiers = (urls.groupBy("facility_id")
         .agg(F.min("tier").alias("best_source_tier"),
              F.min(F.when(F.col("tier") == "D", 1).otherwise(0)).alias("_all_d"),
              F.countDistinct(F.when(F.col("tier").isin("A", "B"), F.col("domain"))).alias("n_health_sources")))

op = F.lower(F.coalesce(F.col("operator_type_id"), F.lit("")))
nm = F.lower(F.col("name"))
alltext = F.lower(F.concat_ws(" ", "capability", "procedure", "equipment", "description"))
sq = (fac.select(F.col("unique_id").alias("facility_id"),
        F.when(op.rlike("public|government|govt"), "public")
         .when(op.rlike("private"), "private")
         .when(op.rlike("trust|ngo|charit|non.?profit"), "non-profit")
         .when(nm.rlike(r"\b(government|govt|district hospital|civil hospital|phc|chc|primary health|community health|aiims|esic?|medical college)\b"), "public")
         .otherwise("unknown").alias("ownership"),
        F.col("recency_of_page_update").alias("page_updated"),
        alltext.rlike(r"covid").alias("mentions_covid"))
      .join(tiers, "facility_id", "left")
      .withColumn("travel_only", F.coalesce(F.col("_all_d") == 1, F.lit(False))).drop("_all_d")
      .withColumn("best_source_tier", F.coalesce("best_source_tier", F.lit("none")))
      .withColumn("dated", (F.col("page_updated") < F.lit("2022-01-01")) | F.col("mentions_covid")))
save(sq, f"{GOLD}.facility_source_quality")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3 - Review queue: which rows the LLM checks, in priority order
# MAGIC 1. **Negation / future / referral wording** in the evidence (rules count these as positive)
# MAGIC 2. **High-acuity services at High/Medium confidence** (a wrong yes sends a patient to the wrong place)
# MAGIC 3. **High-acuity, indirect-only rows at hospitals** (rules give 0.15; the guideline check may lift them)
# MAGIC 4. Everything else at Medium

# COMMAND ----------

idx = spark.table(INDEX)
rules = spark.table(f"{GOLD}.guideline_rules")
NEG = r"(not available|not equipped|no facility|not provided|refer|planned|coming soon|upcoming|proposed|under construction|will be|to be started|expected to be)"

ev_text = F.lower(F.concat_ws(" || ", F.expr("transform(top_evidence, e -> e.text)")))
q = (idx.join(rules.select("service_key", "high_acuity"), "service_key", "left")
        .withColumn("ev_text", ev_text)
        .withColumn("reason",
            F.when(F.col("ev_text").rlike(NEG), "1_negation_or_future_wording")
             .when(F.col("high_acuity") & F.col("confidence").isin("High", "Medium"), "2_high_acuity_high_or_medium")
             .when(F.col("high_acuity") & (F.col("evidence_tier") == "indirect") & (F.col("facility_type") == "hospital"),
                   "3_high_acuity_indirect_hospital")
             .when(F.col("confidence") == "Medium", "4_other_medium"))
        .where("reason IS NOT NULL"))

# one row per facility x service (the index can hold the same pair more than once)
w = Window.partitionBy("facility_id", "service_key").orderBy("reason", F.desc("evidence_score"))
q = q.withColumn("_r", F.row_number().over(w)).where("_r = 1").drop("_r")

display(q.groupBy("reason").count().orderBy("reason"))

w2 = Window.orderBy("reason", F.desc("evidence_score"), "facility_id")
queue = (q.withColumn("queue_pos", F.row_number().over(w2))
          .where(F.col("queue_pos") <= MAX_REVIEW_ROWS)
          .withColumn("batch_no", ((F.col("queue_pos") - 1) / BATCH_SIZE).cast("int"))
          .select("facility_id", "service_key", "service_label", "reason", "queue_pos", "batch_no"))
save(queue, f"{GOLD}.llm_review_queue")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4 - Build prompts
# MAGIC The LLM sees: the service, the guideline's required elements, and the facility's own text fields.
# MAGIC It must answer in a fixed JSON schema and quote the record word for word.

# COMMAND ----------

def humanize(col):
    return F.regexp_replace(F.regexp_replace(col, r"([a-z])([A-Z])", "$1 $2"), r"\s+", " ")

fac_text = fac.select(
    F.col("unique_id").alias("facility_id"),
    F.col("name").alias("fac_name"),
    F.substring(F.concat_ws("\n",
        F.concat(F.lit("Name: "), F.col("name")),
        F.concat(F.lit("Type: "), F.coalesce(F.col("facility_type_id"), F.lit("unknown"))),
        F.concat(F.lit("Capability: "), F.coalesce(F.col("capability"), F.lit("-"))),
        F.concat(F.lit("Procedures: "), F.coalesce(F.col("procedure"), F.lit("-"))),
        F.concat(F.lit("Equipment: "), F.coalesce(F.col("equipment"), F.lit("-"))),
        F.concat(F.lit("Specialties: "), humanize(F.coalesce(F.col("specialties"), F.lit("-")))),
        F.concat(F.lit("Description: "), F.coalesce(F.col("description"), F.lit("-"))),
        F.concat(F.lit("Doctors: "), F.coalesce(F.col("number_doctors").cast("string"), F.lit("not reported"))),
        F.concat(F.lit("Beds: "), F.coalesce(F.col("capacity").cast("string"), F.lit("not reported")))),
      1, MAX_TEXT_CHARS).alias("record_text"))

INSTRUCTIONS = (
    "You verify whether a healthcare facility in India currently provides a specific service, "
    "using ONLY the facility record below. Do not use outside knowledge about the facility.\n"
    "Rules:\n"
    "- verdict = available only if the record states or clearly implies the service is provided now.\n"
    "- verdict = not_available if the record says it is not available, not provided, or absent.\n"
    "- verdict = planned if it is coming soon, under construction, proposed or future.\n"
    "- verdict = referral_only if the facility refers these patients elsewhere.\n"
    "- verdict = unclear if the evidence is only a department name, generic wording, home-care services, "
    "a research study mention, or otherwise insufficient.\n"
    "- For each required element, decide found or missing. Only mark found if the record supports it.\n"
    "- evidence_quotes must be copied word for word from the record (short phrases, max 4).\n"
    "- confidence is your probability (0 to 1) that the facility provides the service now.\n"
    "- red_flags: contradictions, dated (e.g. COVID-period) information, visiting-only doctors, implausible size.\n")

RESPONSE_FORMAT = json.dumps({
  "type": "json_schema",
  "json_schema": {"name": "service_review", "strict": True, "schema": {
    "type": "object", "additionalProperties": False,
    "required": ["verdict", "confidence", "evidence_quotes", "requirements_found", "requirements_missing", "red_flags", "explanation"],
    "properties": {
      "verdict": {"type": "string", "enum": ["available", "not_available", "planned", "referral_only", "unclear"]},
      "confidence": {"type": "number"},
      "evidence_quotes": {"type": "array", "items": {"type": "string"}},
      "requirements_found": {"type": "array", "items": {"type": "string"}},
      "requirements_missing": {"type": "array", "items": {"type": "string"}},
      "red_flags": {"type": "array", "items": {"type": "string"}},
      "explanation": {"type": "string"}}}}})
assert "'" not in RESPONSE_FORMAT

prompts = (spark.table(f"{GOLD}.llm_review_queue")
    .join(rules, "service_key")
    .join(fac_text, "facility_id")
    .withColumn("prompt", F.concat(
        F.lit(INSTRUCTIONS),
        F.lit("\nService: "), F.col("service_label"),
        F.lit("\nGuideline: "), F.col("guideline"),
        F.lit("\nRequired elements: "), F.concat_ws("; ", "required_elements"),
        F.lit("\n\nFacility record:\n"), F.col("record_text"))))
prompts.createOrReplaceTempView("review_prompts")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5 - Run the LLM in resumable batches
# MAGIC Re-running this cell skips batches already done. Errors are kept per row (`error`), never stop the run.

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {REVIEW} (
  facility_id STRING, service_key STRING, batch_no INT, model STRING, reviewed_at TIMESTAMP,
  raw_response STRING, error STRING, record_text STRING, required_elements ARRAY<STRING>, guideline STRING)
""")

done = {r.batch_no for r in spark.table(REVIEW).select("batch_no").distinct().collect()}
todo = sorted({r.batch_no for r in spark.table(f"{GOLD}.llm_review_queue").select("batch_no").distinct().collect()} - done)
print(f"batches done: {len(done)}, to do: {len(todo)}")

RF_ARG = f"responseFormat => '{RESPONSE_FORMAT}', " if USE_RESPONSE_FORMAT else ""
# without responseFormat, ask for JSON in the prompt itself
PROMPT_EXPR = "prompt" if USE_RESPONSE_FORMAT else (
    "concat(prompt, '\\n\\nReply with ONLY a JSON object with keys: verdict, confidence, evidence_quotes, "
    "requirements_found, requirements_missing, red_flags, explanation.')")

for b in todo:
    out = spark.sql(f"""
      SELECT facility_id, service_key, batch_no, '{MODEL}' AS model, current_timestamp() AS reviewed_at,
             r.result AS raw_response, r.errorMessage AS error, record_text, required_elements, guideline
      FROM (
        SELECT *, ai_query('{MODEL}', {PROMPT_EXPR},
                           {RF_ARG}modelParameters => named_struct('temperature', 0.0, 'max_tokens', 700),
                           failOnError => false) AS r
        FROM review_prompts WHERE batch_no = {b})
    """)
    out.write.mode("append").saveAsTable(REVIEW)
    n_err = spark.table(REVIEW).where(f"batch_no = {b} AND error IS NOT NULL").count()
    print(f"batch {b} done ({n_err} errors)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 6 - Parse answers and check every quote against the record
# MAGIC A quote counts only if (after lower-casing and removing punctuation) it appears in the record text.
# MAGIC An "available" answer with **no verified quote** is downgraded to "unclear".

# COMMAND ----------

SCHEMA = ("verdict string, confidence double, evidence_quotes array<string>, requirements_found array<string>, "
          "requirements_missing array<string>, red_flags array<string>, explanation string")

def norm(c):
    return F.trim(F.regexp_replace(F.lower(c), r"[^a-z0-9]+", " "))

rev = (spark.table(REVIEW)
       .withColumn("_rn", F.row_number().over(Window.partitionBy("facility_id", "service_key").orderBy(F.desc("reviewed_at"))))
       .where("_rn = 1").drop("_rn")
       .withColumn("json_text", F.regexp_extract(F.col("raw_response"), r"(?s)(\{.*\})", 1))
       .withColumn("p", F.from_json("json_text", SCHEMA))
       .select("*", "p.*").drop("p")
       .withColumn("record_norm", norm(F.col("record_text")))
       # keep the quote in its original wording if its normalised form appears in the normalised record
       .withColumn("verified_quotes", F.expr(
           "filter(evidence_quotes, x -> length(trim(regexp_replace(lower(x), '[^a-z0-9]+', ' '))) >= 6 "
           "AND instr(record_norm, trim(regexp_replace(lower(x), '[^a-z0-9]+', ' '))) > 0)"))
       .withColumn("n_quotes", F.size(F.coalesce("evidence_quotes", F.array().cast("array<string>"))))
       .withColumn("n_verified", F.size("verified_quotes"))
       .withColumn("grounded", F.col("n_verified") > 0)
       .withColumn("parse_ok", F.col("verdict").isNotNull())
       .withColumn("n_found", F.size(F.coalesce("requirements_found", F.array().cast("array<string>"))))
       .withColumn("n_req", F.size("required_elements"))
       .withColumn("coverage", F.round(F.least(F.lit(1.0), F.col("n_found") / F.greatest(F.col("n_req"), F.lit(1))), 2))
       .withColumn("llm_verdict",
           F.when(~F.col("parse_ok"), "error")
            .when((F.col("verdict") == "available") & ~F.col("grounded"), "unclear")
            .otherwise(F.col("verdict")))
       .withColumn("ungrounded_answer", (F.col("verdict") == "available") & ~F.col("grounded"))
       .drop("record_norm"))
rev.createOrReplaceTempView("review_parsed")

display(rev.groupBy("llm_verdict").count().orderBy(F.desc("count")))
print("answers discarded for ungrounded quotes:", rev.where("ungrounded_answer").count())

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 7 - Adjusted score and confidence (`care_finder_index_v2`)
# MAGIC | LLM verdict | Effect |
# MAGIC |---|---|
# MAGIC | not_available / planned / referral_only | **excluded** from recommendations (kept in table with reason) |
# MAGIC | available (quote verified) | evidence = 0.5 x rules evidence + 0.5 x (LLM confidence x (0.5 + 0.5 x guideline coverage)) |
# MAGIC | unclear | evidence capped at 0.30 |
# MAGIC | not reviewed | rules evidence unchanged |
# MAGIC
# MAGIC Then: travel-site-only sources cap evidence at 0.30. `adjusted_base_score = evidence x trust x type_fit`
# MAGIC (the same structure as Mekeli's `base_score`). Confidence: High >= 0.70 with coverage >= 0.6, Medium >= 0.40, else Low.

# COMMAND ----------

r = rev.select("facility_id", "service_key", "llm_verdict", F.col("confidence").alias("llm_confidence"),
               "verified_quotes", "evidence_quotes", "requirements_found", "requirements_missing", "red_flags",
               F.col("explanation").alias("llm_explanation"), "coverage", "n_found", "n_req", "guideline",
               "ungrounded_answer")

v2 = (spark.table(INDEX).alias("i")
      .join(r, ["facility_id", "service_key"], "left")
      .join(spark.table(f"{GOLD}.facility_source_quality"), "facility_id", "left")
      .withColumn("reviewed", F.col("llm_verdict").isNotNull() & (F.col("llm_verdict") != "error"))
      .withColumn("excluded", F.col("llm_verdict").isin("not_available", "planned", "referral_only"))
      .withColumn("llm_component",
          F.coalesce(F.col("llm_confidence"), F.lit(0.0)) * (0.5 + 0.5 * F.coalesce(F.col("coverage"), F.lit(0.0))))
      .withColumn("adj_evidence",
          F.when(F.col("excluded"), F.lit(0.0))
           .when(F.col("llm_verdict") == "available", 0.5 * F.col("evidence_score") + 0.5 * F.col("llm_component"))
           .when(F.col("llm_verdict") == "unclear", F.least(F.col("evidence_score"), F.lit(0.30)))
           .otherwise(F.col("evidence_score")))
      .withColumn("adj_evidence", F.when(F.col("travel_only"), F.least(F.col("adj_evidence"), F.lit(0.30)))
                                   .otherwise(F.col("adj_evidence")))
      .withColumn("adj_evidence", F.round("adj_evidence", 3))
      .withColumn("adjusted_base_score", F.round(F.col("adj_evidence") * F.col("trust_score") * F.col("type_fit"), 4))
      .withColumn("adjusted_confidence",
          F.when(F.col("excluded"), "Excluded")
           .when(~F.col("reviewed") & ~F.coalesce(F.col("travel_only"), F.lit(False)), F.col("confidence"))
           .when((F.col("adj_evidence") >= 0.70) & (~F.col("reviewed") | (F.col("coverage") >= 0.6)), "High")
           .when(F.col("adj_evidence") >= 0.40, "Medium")
           .otherwise("Low"))
      .withColumn("llm_status",
          F.when(~F.col("reviewed"), "not reviewed by AI")
           .when(F.col("excluded"), F.concat(F.lit("AI review: "), F.regexp_replace("llm_verdict", "_", " ")))
           .otherwise(F.concat(F.lit("AI review: "), F.col("llm_verdict"))))
      .withColumn("guideline_check",
          F.when(F.col("reviewed") & ~F.col("excluded") & F.col("n_req").isNotNull(),
                 F.format_string("Meets %d of %d %s requirements.", F.col("n_found"), F.col("n_req"), F.col("guideline"))))
      .withColumn("extra_cautions", F.filter(F.array(
          F.when(F.col("excluded"), F.concat(F.lit("Record says: \""), F.coalesce(F.element_at("verified_quotes", 1), F.col("llm_explanation")), F.lit("\""))),
          F.when(~F.coalesce(F.col("excluded"), F.lit(False)) & (F.size("requirements_missing") > 0),
                 F.concat(F.lit("Not mentioned (guideline requirement): "), F.concat_ws(", ", "requirements_missing"), F.lit(". Ask when you call."))),
          F.when(F.col("travel_only"), F.lit("Only travel or unrelated websites list this facility.")),
          F.when(F.col("dated"), F.lit("Information may be dated (old page or COVID-period text). Confirm current services.")),
          F.when(F.col("ungrounded_answer"), F.lit("AI could not quote supporting text; treated as unclear.")),
          F.when(F.size("red_flags") > 0, F.concat(F.lit("AI noted: "), F.concat_ws("; ", "red_flags")))),
          lambda x: x.isNotNull()))
      .withColumn("all_cautions", F.concat(F.coalesce("cautions", F.array().cast("array<string>")), "extra_cautions")))
save(v2, f"{GOLD}.care_finder_index_v2")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 8 - `recommend_facilities_v2()`: same inputs as Mekeli's function
# MAGIC Ranks on `adjusted_base_score x exp(-km / tau_km)`, drops AI-excluded rows, and returns the extra columns.

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE FUNCTION {GOLD}.recommend_facilities_v2(
  q_service STRING, q_lat DOUBLE, q_lon DOUBLE, top_n INT DEFAULT 5, max_km DOUBLE DEFAULT 300)
RETURNS TABLE
COMMENT 'Care Finder with AI review: same inputs as recommend_facilities(); ranks on the AI-adjusted score, excludes facilities whose record says the service is not available, planned or referred out, and adds the guideline check.'
RETURN
WITH svc AS (
    SELECT service_key FROM {GOLD}.service_catalog
    WHERE array_contains(match_keys, regexp_replace(upper(q_service), '[^A-Z0-9]', ''))
    LIMIT 1
  ),
  c AS (
    SELECT i.*,
           round(2 * 6371 * asin(sqrt(pow(sin(radians(i.lat - q_lat) / 2), 2)
                 + cos(radians(q_lat)) * cos(radians(i.lat)) * pow(sin(radians(i.lon - q_lon) / 2), 2))), 1) AS distance_km
    FROM {GOLD}.care_finder_index_v2 i JOIN svc ON i.service_key = svc.service_key
    WHERE i.lat IS NOT NULL AND NOT coalesce(i.excluded, false)
  ),
  scored AS (
    SELECT *, round(exp(-distance_km / tau_km), 3) AS distance_score,
              round(adjusted_base_score * exp(-distance_km / tau_km), 4) AS score
    FROM c WHERE distance_km <= max_km
  ),
  dedup AS (
    SELECT * FROM (
      SELECT *, row_number() OVER (PARTITION BY upper(name), coalesce(upper(city), '') ORDER BY score DESC) AS _dup
      FROM scored
    ) WHERE _dup = 1
  ),
  ranked AS (SELECT *, CAST(row_number() OVER (ORDER BY score DESC, distance_km) AS INT) AS result_rank FROM dedup)
  SELECT result_rank, name, facility_type, ownership, adjusted_confidence AS confidence, confidence AS rules_confidence,
         llm_status, guideline_check, distance_km, score,
         concat(why_evidence, ' ', format_string('%.1f km away (location from %s).', distance_km, location_source)) AS why,
         CASE WHEN size(verified_quotes) > 0 THEN verified_quotes ELSE transform(top_evidence, e -> e.text) END AS evidence,
         llm_explanation, all_cautions AS cautions, supporting_facts,
         address, district, state, phone, website, source_urls, best_source_tier,
         location_source, evidence_score AS rules_evidence_score, adj_evidence AS evidence_score,
         type_fit, trust_score, distance_score, service_label, facility_id, lat, lon
  FROM ranked WHERE result_rank <= top_n
  ORDER BY result_rank
""")
print("created recommend_facilities_v2")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 9 - What did the LLM change? (slide material)

# COMMAND ----------

changes = (spark.table(f"{GOLD}.care_finder_index_v2").where("reviewed")
    .withColumn("change",
        F.when(F.col("excluded"), F.concat(F.lit("excluded: "), F.col("llm_verdict")))
         .when(F.col("adjusted_confidence") == F.col("confidence"), "unchanged")
         .when(F.expr("array_position(array('Low','Medium','High'), adjusted_confidence) > "
                      "array_position(array('Low','Medium','High'), confidence)"), "upgraded")
         .otherwise("downgraded"))
    .groupBy("service_key", "confidence", "change").count()
    .withColumnRenamed("confidence", "rules_confidence"))
save(changes, f"{GOLD}.llm_review_changes")
display(spark.table(f"{GOLD}.llm_review_changes").groupBy("change").agg(F.sum("count").alias("rows")).orderBy(F.desc("rows")))

# COMMAND ----------

# Examples of each kind of change, with the quote that justified it
display(spark.table(f"{GOLD}.care_finder_index_v2").where("reviewed AND (excluded OR adjusted_confidence <> confidence)")
        .select("name", "city", "service_key", F.col("confidence").alias("rules"), "adjusted_confidence",
                "llm_verdict", "verified_quotes", "guideline_check", "llm_explanation")
        .orderBy(F.rand(7)).limit(25))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 10 - Audit sample (manual check / phone calls)
# MAGIC 50 rows for 3 headline services, stratified by adjusted confidence. Export to a sheet; **hide the
# MAGIC confidence columns from whoever checks**, then fill `audit_answer` with: yes_24x7 / yes_limited / no / no_answer.

# COMMAND ----------

aud = (spark.table(f"{GOLD}.care_finder_index_v2")
       .where("service_key IN ('emergency_c_section','nicu','dialysis') AND phone IS NOT NULL")
       .withColumn("_r", F.row_number().over(Window.partitionBy("service_key", "adjusted_confidence").orderBy(F.rand(42))))
       .where("_r <= 4")
       .select("facility_id", "name", "city", "state", "phone", "website", "service_key",
               "confidence", "adjusted_confidence", "llm_verdict",
               F.lit(None).cast("string").alias("audit_answer"), F.lit(None).cast("string").alias("audit_notes"),
               F.lit(None).cast("string").alias("checked_by"))
       .limit(50))
# never overwrite hand-filled answers: only (re)draw the sample while no audit_answer has been entered
AUD_T = f"{GOLD}.audit_sample"
if spark.catalog.tableExists(AUD_T) and spark.table(AUD_T).where("audit_answer IS NOT NULL AND audit_answer <> ''").limit(1).count():
    print(f"{AUD_T} already has audit answers: kept as is")
else:
    save(aud, AUD_T)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Smoke tests on known problem rows

# COMMAND ----------

display(spark.sql(f"""
SELECT name, service_key, confidence AS rules_confidence, adjusted_confidence, llm_verdict,
       verified_quotes, guideline_check, extra_cautions
FROM {GOLD}.care_finder_index_v2
WHERE (name LIKE 'Ankur Hospital%' AND service_key = 'nicu')
   OR (name = 'Family Health Care' AND service_key = 'icu')
   OR (name = 'Care Diagnostics' AND service_key = 'ct_scan')
   OR (name LIKE 'Kayalvarath%' AND service_key = 'icu')
"""))

# COMMAND ----------

# Same question through both functions: Patna, emergency C-section
loc = spark.sql(f"SELECT lat, lon FROM {GOLD}.resolve_location('Patna') LIMIT 1").first()
key = spark.sql(f"SELECT element_at(match_keys, 1) AS k FROM {GOLD}.service_catalog WHERE service_key = 'emergency_c_section'").first().k
print("location:", loc, "service match key:", key)
display(spark.sql(f"SELECT result_rank, name, confidence, distance_km, score FROM {GOLD}.recommend_facilities('{key}', {loc.lat}, {loc.lon}, 5, 100)"))
display(spark.sql(f"SELECT result_rank, name, confidence, rules_confidence, llm_status, guideline_check, distance_km, score, cautions FROM {GOLD}.recommend_facilities_v2('{key}', {loc.lat}, {loc.lon}, 5, 100)"))