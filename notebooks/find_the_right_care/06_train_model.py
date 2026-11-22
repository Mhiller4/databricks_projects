# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "6"
# ///
# MAGIC %md
# MAGIC # 06 - Train the capability model: "can this facility provide this service?"
# MAGIC
# MAGIC **Purpose.** The LLM review (`02`) carefully checks ~3,000 risky facility x service pairs. This model learns from
# MAGIC those checked answers and scores **all ~40,000 pairs** in seconds, for any service, with reasons.
# MAGIC
# MAGIC | Step | What happens |
# MAGIC |---|---|
# MAGIC | 1 | **Labels**: LLM verdicts that passed the quote check (available = 1; not available / planned / referral / unclear = 0) |
# MAGIC | 2 | **Features**: service-relevant sentences (TF-IDF), warning words, guideline checklist coverage, specialty match, facility facts, trust, source tier, optional text-service embedding similarity |
# MAGIC | 3 | **Split by facility** 70 / 15 / 15 (a facility never appears in two sets) |
# MAGIC | 4 | **Train**: logistic regression (baseline), LightGBM (main), small neural network (comparison) |
# MAGIC | 5 | **Test**: held-out facilities, vs Mekeli's rules, **synthetic stress tests**, human audit (if filled) |
# MAGIC | 6 | **Explain**: top reasons per prediction (LightGBM feature contributions) |
# MAGIC | 7 | **Score all pairs** and write `care_finder_index_final` (LLM verdict wins where it exists; model elsewhere) |
# MAGIC
# MAGIC Location is deliberately **not** a feature: the model judges what a facility can do; distance is applied at ranking time
# MAGIC (so the model cannot learn "rural = less capable").
# MAGIC
# MAGIC Writes: `model_training_set`, `model_eval`, `model_stress_tests`, `model_audit_eval`, `model_scores`,
# MAGIC `care_finder_index_final`, optional `facility_embeddings`; one MLflow run.

# COMMAND ----------

# MAGIC %pip install lightgbm --quiet

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import re, json, math
import numpy as np
import pandas as pd
from pyspark.sql import functions as F, Window

GOLD = "workspace.hc_gold"
FAC = "workspace.hc_silver.vf_facilities"
V2 = f"{GOLD}.care_finder_index_v2"

USE_EMBEDDINGS = True                       # set False if Serving has no embedding model
EMBED_MODEL = "databricks-gte-large-en"     # <- check the Serving page (gte / bge embedding model)
SEED = 42
MODEL_VERSION = "capability_v2_llm_labels"

def save_pdf(pdf, name):
    spark.createDataFrame(pdf).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(name)
    print(f"wrote {name}: {len(pdf):,} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1 - Labels and the rows to score

# COMMAND ----------

v2 = spark.table(V2)
pairs = (v2.select("facility_id", "service_key", "evidence_score", "confidence", "type_fit", "trust_score",
                   "facility_type", "best_source_tier", "travel_only", "dated", "ownership",
                   "reviewed", "llm_verdict", "ungrounded_answer")
           .dropDuplicates(["facility_id", "service_key"]))

# Labels: hc_gold.llm_labels (gold/32): 1,200 random pairs (25 per service x rules confidence, with population
# weights) + the 200 risk-selected pairs from this notebook's first review. Same prompt, same quote check
# (an "available" answer with no verified quote is already "unclear" there). The 43 audit pairs stay out of
# training so the human audit is independent. Label rule unchanged: available = 1, anything else = 0.
labels = (spark.table(f"{GOLD}.llm_labels")
          .where("origin <> 'audit' AND llm_verdict IS NOT NULL AND coalesce(error, '') = ''")
          .withColumn("label", F.when(F.col("llm_verdict") == "available", 1).otherwise(0))
          .withColumn("reason", F.when(F.col("origin") == "random", F.lit("5_random_sample")).otherwise(F.col("origin")))
          .withColumn("sample_weight", F.when(F.col("origin") == "random", F.col("sample_weight")))
          .withColumn("_o", F.when(F.col("origin") == "random", 0).otherwise(1))
          .withColumn("_r", F.row_number().over(Window.partitionBy("facility_id", "service_key").orderBy("_o")))
          .where("_r = 1")
          .select("facility_id", "service_key", "label", "reason", "sample_weight"))
display(labels.groupBy("reason").pivot("label").count().orderBy("reason"))
display(labels.groupBy("service_key").pivot("label").count().orderBy("service_key"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2 - Facility text, services, and features

# COMMAND ----------

def humanize_col(c):
    return F.regexp_replace(F.regexp_replace(c, r"([a-z])([A-Z])", "$1 $2"), r"\s+", " ")

fac = spark.table(FAC).select(
    F.col("unique_id").alias("facility_id"),
    F.concat_ws("\n",
        F.coalesce(F.col("capability"), F.lit("")), F.coalesce(F.col("procedure"), F.lit("")),
        F.coalesce(F.col("equipment"), F.lit("")), F.coalesce(F.col("description"), F.lit(""))).alias("record_text"),
    humanize_col(F.coalesce(F.col("specialties"), F.lit(""))).alias("specialties_text"),
    F.col("capacity").cast("double").alias("beds"), F.col("number_doctors").cast("double").alias("doctors"))

svc = (spark.table(f"{GOLD}.service_catalog").select("service_key", "label", "pattern", "specialties", "synonyms")
       .join(spark.table(f"{GOLD}.guideline_rules").select("service_key", "required_elements"), "service_key", "left"))

pdf = (pairs.join(fac, "facility_id", "left")
            .join(labels.select("facility_id", "service_key", "label", "reason", "sample_weight"), ["facility_id", "service_key"], "left")
            .toPandas())
svc_pdf = svc.toPandas()
print(f"{len(pdf):,} facility x service pairs, {pdf.label.notna().sum():,} labelled")

# COMMAND ----------

NEG = re.compile(r"\b(not available|not equipped|no facility|not provided|unavailable|do not|does not|without|lack)\b")
FUT = re.compile(r"\b(coming soon|upcoming|planned|proposed|under construction|will be|to be started|expected to be)\b")
REF = re.compile(r"\b(refer|referred|referral|transferred to)\b")
SPLIT = re.compile(r'(?<=[.!?;])\s+|\n+|","|\|\|')
STOPW = {"available", "unit", "units", "doctor", "doctors", "trained", "care", "equipment", "beds", "performed", "with",
         "and", "the", "for", "facility", "services", "service", "room", "staff", "24x7", "hours"}

def safe_compile(p):
    try:
        return re.compile(p) if p else re.compile(r"$^")
    except re.error:
        return re.compile(r"$^")

SERVICES = {}
for r in svc_pdf.itertuples():
    elems = []
    for e in (r.required_elements if r.required_elements is not None else []):
        words = {w for w in re.findall(r"[a-z]{4,}", e.lower()) if w not in STOPW}
        if words:
            elems.append(words)
    syn = [s.lower() for s in (r.synonyms if r.synonyms is not None else [])]
    specs = [re.sub(r"([a-z])([A-Z])", r"\1 \2", s).lower() for s in (r.specialties if r.specialties is not None else [])]
    SERVICES[r.service_key] = dict(
        label=r.label,
        pat=safe_compile(r.pattern),
        syn=re.compile("|".join(re.escape(s) for s in syn)) if syn else None,
        elems=elems, specs=specs,
        desc=f"{r.label}. " + ("Requires: " + "; ".join(r.required_elements) if r.required_elements is not None else ""))

def text_features(record_text, specialties_text, service_key):
    s = SERVICES[service_key]
    text = (record_text or "").lower()
    sents = [x.strip() for x in SPLIT.split(text) if len(x.strip()) > 2]
    hits = [x for x in sents if s["pat"].search(x) or (s["syn"] is not None and s["syn"].search(x))]
    cover = (sum(1 for words in s["elems"] if any(w in text for w in words)) / len(s["elems"])) if s["elems"] else 0.0
    spec = (specialties_text or "").lower()
    return dict(
        n_hits=len(hits),
        hit_neg=int(any(NEG.search(h) for h in hits)),
        hit_future=int(any(FUT.search(h) for h in hits)),
        hit_referral=int(any(REF.search(h) for h in hits)),
        checklist_coverage=round(cover, 3),
        specialty_match=int(any(sp in spec for sp in s["specs"])),
        text_len=math.log1p(len(text)),
        snippet=" ".join(hits)[:2000] if hits else "nohit")

def build_features(df):
    tf = pd.DataFrame([text_features(a, b, c) for a, b, c in zip(df.record_text, df.specialties_text, df.service_key)],
                      index=df.index)
    out = pd.concat([df, tf], axis=1)
    out["beds_log"] = np.log1p(out.beds.fillna(0)); out["beds_missing"] = out.beds.isna().astype(int)
    out["doctors_log"] = np.log1p(out.doctors.fillna(0)); out["doctors_missing"] = out.doctors.isna().astype(int)
    out["is_hospital"] = (out.facility_type == "hospital").astype(int)
    out["is_clinic"] = (out.facility_type == "clinic").astype(int)
    out["source_tier_num"] = out.best_source_tier.map({"A": 3, "B": 2, "C": 1, "D": 0}).fillna(0)
    out["travel_only_f"] = out.travel_only.fillna(False).astype(int)
    out["dated_f"] = out.dated.fillna(False).astype(int)
    out["public_f"] = (out.ownership == "public").astype(int)
    out["trust"] = out.trust_score.fillna(0.5)
    out["type_fit_f"] = out.type_fit.fillna(1.0)
    return out

pdf = build_features(pdf)
DENSE = ["n_hits", "hit_neg", "hit_future", "hit_referral", "checklist_coverage", "specialty_match", "text_len",
         "beds_log", "beds_missing", "doctors_log", "doctors_missing", "is_hospital", "is_clinic", "source_tier_num",
         "travel_only_f", "dated_f", "public_f", "trust", "type_fit_f"]
SERVICE_KEYS = sorted(SERVICES)
for k in SERVICE_KEYS:
    pdf[f"svc_{k}"] = (pdf.service_key == k).astype(int)
DENSE += [f"svc_{k}" for k in SERVICE_KEYS]
display(pdf[DENSE + ["label"]].describe().T)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2b - Optional: meaning similarity between the facility text and the service (pre-trained embeddings)

# COMMAND ----------

def embed_texts(texts):
    """Embed a list of strings with the Databricks embedding endpoint via ai_query. Returns list of np arrays."""
    sdf = spark.createDataFrame(pd.DataFrame({"i": range(len(texts)), "t": [t[:2000] for t in texts]}))
    sdf.createOrReplaceTempView("_to_embed")
    res = spark.sql(f"SELECT i, ai_query('{EMBED_MODEL}', t) AS e FROM _to_embed").toPandas().sort_values("i")
    return [np.array(e, dtype=float) for e in res.e]

def cos(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))

if USE_EMBEDDINGS:
    try:
        svc_vec = dict(zip(SERVICE_KEYS, embed_texts([SERVICES[k]["desc"] for k in SERVICE_KEYS])))
        EMB_T = f"{GOLD}.facility_embeddings"
        if not spark.catalog.tableExists(EMB_T):
            ft = pdf.drop_duplicates("facility_id")[["facility_id", "record_text", "specialties_text"]]
            texts = (ft.record_text.fillna("") + " " + ft.specialties_text.fillna("")).tolist()
            vecs = embed_texts(texts)
            save_pdf(pd.DataFrame({"facility_id": ft.facility_id.values, "embedding": [v.tolist() for v in vecs]}), EMB_T)
        emb = spark.table(EMB_T).toPandas()
        fac_vec = dict(zip(emb.facility_id, [np.array(v) for v in emb.embedding]))
        pdf["sim"] = [cos(fac_vec[f], svc_vec[s]) if f in fac_vec else 0.0 for f, s in zip(pdf.facility_id, pdf.service_key)]
        # how this facility's similarity ranks among all services (relative, not absolute)
        pdf["sim_rank"] = pdf.groupby("facility_id").sim.rank(pct=True)
        DENSE += ["sim", "sim_rank"]
        print("embedding features added")
    except Exception as e:
        USE_EMBEDDINGS = False
        print("Embeddings unavailable, continuing with word features only:", str(e)[:300])

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3 - Split by facility, build matrices

# COMMAND ----------

from sklearn.model_selection import GroupShuffleSplit
from sklearn.feature_extraction.text import TfidfVectorizer
from scipy import sparse

lab = pdf[pdf.label.notna()].copy()
lab["label"] = lab.label.astype(int)
gss = GroupShuffleSplit(n_splits=1, test_size=0.30, random_state=SEED)
tr_idx, rest_idx = next(gss.split(lab, groups=lab.facility_id))
rest = lab.iloc[rest_idx]
gss2 = GroupShuffleSplit(n_splits=1, test_size=0.50, random_state=SEED)
va_i, te_i = next(gss2.split(rest, groups=rest.facility_id))
train, valid, test = lab.iloc[tr_idx], rest.iloc[va_i], rest.iloc[te_i]
print({k: (len(d), int(d.label.sum())) for k, d in [("train", train), ("valid", valid), ("test", test)]})
save_pdf(lab.assign(split=np.select([lab.index.isin(train.index), lab.index.isin(valid.index)], ["train", "valid"], "test"))
            [["facility_id", "service_key", "label", "split"] + DENSE], f"{GOLD}.model_training_set")

# Data augmentation: hard negatives built from TRAIN positives only (wording differs from the stress-test edits),
# so the model learns that "<service> + not available / planned / referred" means NO.
AUGMENT = True
if AUGMENT:
    tp = train[train.label == 1]
    aug_templates = [
        "{s} services are currently not provided here.",
        "A {s} wing will be started next year.",
        "We refer {s} cases to a higher centre.",
    ]
    aug = []
    for i, tmpl in enumerate(aug_templates):
        a = tp.sample(frac=0.3, random_state=SEED + i).copy()
        a["record_text"] = [t + "\n" + tmpl.format(s=SERVICES[k]["label"].split(" /")[0].split(" (")[0])
                            for t, k in zip(a.record_text, a.service_key)]
        a["label"] = 0
        aug.append(a)
    aug = pd.concat(aug, ignore_index=True)
    aug = build_features(aug.drop(columns=["n_hits", "hit_neg", "hit_future", "hit_referral", "checklist_coverage",
                                           "specialty_match", "text_len", "snippet"]))
    train = pd.concat([train, aug], ignore_index=True)
    print(f"added {len(aug)} augmented hard negatives to train (valid/test untouched)")

tfidf = TfidfVectorizer(ngram_range=(1, 2), min_df=3, max_features=5000, sublinear_tf=True)
tfidf.fit(train.snippet)
WORDS = [f"word:{w}" for w in tfidf.get_feature_names_out()]
FEATURES = DENSE + WORDS

def matrix(df):
    return sparse.hstack([sparse.csr_matrix(df[DENSE].astype(float).values), tfidf.transform(df.snippet)]).tocsr()

Xtr, Xva, Xte = matrix(train), matrix(valid), matrix(test)
ytr, yva, yte = train.label.values, valid.label.values, test.label.values

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4 - Train three models (tracked in MLflow)

# COMMAND ----------

import mlflow
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import MaxAbsScaler
from sklearn.decomposition import TruncatedSVD
from sklearn.pipeline import make_pipeline
from sklearn.metrics import roc_auc_score, f1_score, precision_score, recall_score, accuracy_score
import lightgbm as lgb

user = spark.sql("SELECT current_user()").first()[0]
mlflow.set_experiment(f"/Users/{user}/find_the_right_care_capability_model")

def best_threshold(y, p):
    grid = np.linspace(0.2, 0.8, 25)
    return float(grid[int(np.argmax([f1_score(y, (p >= t).astype(int), zero_division=0) for t in grid]))])

def metrics(y, p, t):
    yh = (p >= t).astype(int)
    return dict(auc=roc_auc_score(y, p) if len(set(y)) > 1 else float("nan"), f1=f1_score(y, yh, zero_division=0),
                precision=precision_score(y, yh, zero_division=0), recall=recall_score(y, yh, zero_division=0),
                accuracy=accuracy_score(y, yh))

models = {
    "logistic_regression": make_pipeline(MaxAbsScaler(), LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0)),
    "lightgbm": lgb.LGBMClassifier(n_estimators=400, learning_rate=0.05, num_leaves=31, min_child_samples=10,
                                   subsample=0.8, colsample_bytree=0.8, class_weight="balanced", random_state=SEED, verbose=-1),
    "neural_net": make_pipeline(MaxAbsScaler(), TruncatedSVD(n_components=min(100, Xtr.shape[1] - 1), random_state=SEED),
                                MLPClassifier(hidden_layer_sizes=(64, 32), alpha=1e-3, max_iter=300,
                                              early_stopping=True, random_state=SEED)),
}
results, thresholds = [], {}
with mlflow.start_run(run_name=MODEL_VERSION) as run:
    mlflow.log_params(dict(n_train=len(train), n_valid=len(valid), n_test=len(test), embeddings=USE_EMBEDDINGS,
                           n_features=len(FEATURES), seed=SEED))
    for name, m in models.items():
        m.fit(Xtr, ytr)
        pva = m.predict_proba(Xva)[:, 1]
        thresholds[name] = best_threshold(yva, pva)
        pte = m.predict_proba(Xte)[:, 1]
        r = metrics(yte, pte, thresholds[name])
        results.append(dict(model=name, threshold=thresholds[name], **r))
        mlflow.log_metrics({f"{name}_{k}": v for k, v in r.items() if not (isinstance(v, float) and math.isnan(v))})
    # Mekeli's rules as a baseline on the same test rows (rules evidence_score as the score)
    pr = test.evidence_score.fillna(0).values
    results.append(dict(model="rules_baseline (Mekeli)", threshold=0.4, **metrics(yte, pr, 0.4)))
    try:
        mlflow.lightgbm.log_model(models["lightgbm"].booster_, "lightgbm_model")
    except Exception as e:
        print("model logging skipped:", str(e)[:200])
    run_id = run.info.run_id

eval_pdf = pd.DataFrame(results)
save_pdf(eval_pdf.assign(run_id=run_id), f"{GOLD}.model_eval")
display(eval_pdf)

# COMMAND ----------

# Honest estimate for ALL rows: test rows that came from the random sample (not the risk-selected queue)
rnd = test.reason.eq("5_random_sample").values
strata = []
for name, m in models.items():
    p_all = m.predict_proba(Xte)[:, 1]
    strata.append(dict(model=name, stratum="all test rows (mostly risk-selected)", n=len(yte), **metrics(yte, p_all, thresholds[name])))
    if rnd.sum() >= 20:
        strata.append(dict(model=name, stratum="random-sample test rows (represents all 40k)", n=int(rnd.sum()),
                           **metrics(yte[rnd], p_all[rnd], thresholds[name])))
if rnd.sum() >= 20:
    strata.append(dict(model="rules_baseline (Mekeli)", stratum="random-sample test rows (represents all 40k)", n=int(rnd.sum()),
                       **metrics(yte[rnd], test.evidence_score.fillna(0).values[rnd], 0.4)))
else:
    print(f"Only {int(rnd.sum())} random-sample rows in test; raise RANDOM_SAMPLE_ROWS in 02 for a reliable estimate.")
save_pdf(pd.DataFrame(strata), f"{GOLD}.model_eval_by_stratum")
display(pd.DataFrame(strata))

# COMMAND ----------

# Held-out bands on the random-sample test rows, weighted to all ~40k pairs (each random row stands for pop_n / 25 pairs).
# Compares Mekeli's rules bands, the model's bands (same cut-offs as Step 7: >= 0.70 High, >= 0.40 Medium) and the
# stricter of the two. "Holds up" = the LLM said available.
RANK = {"High": 3, "Medium": 2, "Low": 1}
NAME = {3: "High", 2: "Medium", 1: "Low"}
tr_ = test[rnd].copy()
p_main = models["lightgbm"].predict_proba(Xte)[:, 1][rnd]
tr_["rules_band"] = tr_.confidence.map(RANK).fillna(1).astype(int)
tr_["model_band"] = np.select([p_main >= 0.70, p_main >= 0.40], [3, 2], 1)
tr_["stricter_band"] = np.minimum(tr_.rules_band, tr_.model_band)
tr_["average_up_band"] = np.ceil((tr_.rules_band + tr_.model_band) / 2).astype(int)   # used in Step 7
w_ = tr_.sample_weight.fillna(1.0).values
band_rows = []
for method in ["rules_band", "model_band", "stricter_band", "average_up_band"]:
    for b in [3, 2, 1]:
        m_ = (tr_[method] == b).values
        band_rows.append(dict(method=method.replace("_band", ""), band=NAME[b], n_test_rows=int(m_.sum()),
                              share_of_all_pairs=float(w_[m_].sum() / w_.sum()),
                              holds_up=float(np.average(tr_.label.values[m_], weights=w_[m_])) if m_.any() else float("nan")))
band_rows.append(dict(method="lightgbm (auc, weighted)", band="all", n_test_rows=int(rnd.sum()), share_of_all_pairs=1.0,
                      holds_up=float(roc_auc_score(tr_.label, p_main, sample_weight=w_))))
band_rows.append(dict(method="rules evidence_score (auc, weighted)", band="all", n_test_rows=int(rnd.sum()), share_of_all_pairs=1.0,
                      holds_up=float(roc_auc_score(tr_.label, tr_.evidence_score.fillna(0), sample_weight=w_))))
bands = pd.DataFrame(band_rows).assign(run_id=run_id, n_test_facilities=int(tr_.facility_id.nunique()))
save_pdf(bands, f"{GOLD}.model_eval_bands")
display(bands)

# COMMAND ----------

# Per-service results for the main model
main = models["lightgbm"]; T = thresholds["lightgbm"]
pte = main.predict_proba(Xte)[:, 1]
per = []
for k, g in test.assign(p=pte).groupby("service_key"):
    if len(g) >= 10:
        per.append(dict(service_key=k, n=len(g), positives=int(g.label.sum()), **metrics(g.label.values, g.p.values, T)))
display(pd.DataFrame(per))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5 - Synthetic stress tests (real test records, edited)
# MAGIC | Edit | Correct answer |
# MAGIC |---|---|
# MAGIC | add "<service> facility not available." | 0 |
# MAGIC | add "Coming soon: <service> unit (under construction)." | 0 |
# MAGIC | add "Patients needing <service> are referred to the district hospital." | 0 |
# MAGIC | C-section positives: replace caesarean / c-section with "LSCS" | 1 |
# MAGIC
# MAGIC Rules baseline: Mekeli's regex would still match the service words, so it keeps its original score.

# COMMAND ----------

base = test[test.label == 1].groupby("service_key").head(30)
edits = {
    "negation": (lambda t, lab: t + f"\n{lab} facility not available.", 0),
    "future": (lambda t, lab: t + f"\nComing soon: {lab} unit (under construction).", 0),
    "referral": (lambda t, lab: t + f"\nPatients needing {lab} are referred to the district hospital.", 0),
}
rows = []
for kind, (fn, expected) in edits.items():
    b = base.copy()
    b["record_text"] = [fn(t, SERVICES[s]["label"].split(" /")[0].split(" (")[0]) for t, s in zip(b.record_text, b.service_key)]
    b["kind"], b["expected"] = kind, expected
    rows.append(b)
cs = test[(test.label == 1) & (test.service_key == "emergency_c_section")].copy()
if len(cs):
    cs["record_text"] = cs.record_text.str.replace(r"(?i)c[- ]?sections?|caesarean|cesarean", "LSCS", regex=True)
    cs["kind"], cs["expected"] = "synonym_lscs", 1
    rows.append(cs)
stress = pd.concat(rows, ignore_index=True)
stress = build_features(stress.drop(columns=[c for c in ["n_hits", "hit_neg", "hit_future", "hit_referral",
                                    "checklist_coverage", "specialty_match", "text_len", "snippet"] if c in stress.columns]))
for k in SERVICE_KEYS:
    stress[f"svc_{k}"] = (stress.service_key == k).astype(int)
if USE_EMBEDDINGS:
    vecs = embed_texts((stress.record_text.fillna("") + " " + stress.specialties_text.fillna("")).tolist())
    stress["sim"] = [cos(v, svc_vec[s]) for v, s in zip(vecs, stress.service_key)]
    stress["sim_rank"] = 0.5
stress["p_model"] = main.predict_proba(matrix(stress))[:, 1]
stress["model_correct"] = ((stress.p_model >= T).astype(int) == stress.expected)
stress["rules_correct"] = ((stress.evidence_score.fillna(0) >= 0.4).astype(int) == stress.expected)
st = stress.groupby("kind").agg(n=("expected", "size"), rules_accuracy=("rules_correct", "mean"),
                                model_accuracy=("model_correct", "mean")).reset_index()
save_pdf(st, f"{GOLD}.model_stress_tests")
display(st)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 6 - Score every pair, with reasons

# COMMAND ----------

Xall = matrix(pdf)
pdf["model_prob"] = main.predict_proba(Xall)[:, 1]
names = np.array(FEATURES)
PRETTY = {"n_hits": "times the service is mentioned", "hit_neg": "'not available' wording", "hit_future": "'planned / coming soon' wording",
          "hit_referral": "'refer' wording", "checklist_coverage": "guideline checklist coverage", "specialty_match": "related department listed",
          "text_len": "amount of record text", "beds_log": "bed count", "beds_missing": "bed count missing", "doctors_log": "doctor count",
          "doctors_missing": "doctor count missing", "is_hospital": "is a hospital", "is_clinic": "is a clinic",
          "source_tier_num": "source quality", "travel_only_f": "travel-site-only sources", "dated_f": "dated information",
          "public_f": "public facility", "trust": "record trust", "type_fit_f": "facility type fits service",
          "sim": "meaning similarity to the service", "sim_rank": "service similarity rank"}

def pretty(n):
    if n in PRETTY:
        return PRETTY[n]
    if n.startswith("word:"):
        return f"words '{n[5:]}'"
    return n.replace("svc_", "service: ")

def reasons(row_c, row_x, k=3):
    """Top-k features by absolute contribution, as '+ reason' / '- reason' ('no ...' when the feature is absent)."""
    idx = np.argsort(-np.abs(row_c[:-1]))[:k]
    return [("+ " if row_c[i] > 0 else "- ") + ("no " if row_x[i] == 0 else "") + pretty(names[i])
            for i in idx if abs(row_c[i]) >= 0.05]


all_reasons = []
for start in range(0, Xall.shape[0], 2000):              # chunks: contributions for 5,000+ features are large
    xb = Xall[start:start + 2000]
    c = main.booster_.predict(xb, pred_contrib=True)   # log-odds per feature, last col = bias
    c = c.toarray() if sparse.issparse(c) else np.asarray(c)
    xd = xb.toarray()
    all_reasons += [reasons(c[j], xd[j]) for j in range(c.shape[0])]
pdf["model_reasons"] = all_reasons
pdf["model_label"] = (pdf.model_prob >= T).astype(int)
scores = pdf[["facility_id", "service_key", "model_prob", "model_label", "model_reasons"]].assign(
    model_version=MODEL_VERSION, threshold=T, mlflow_run_id=run_id)
save_pdf(scores, f"{GOLD}.model_scores")
display(pdf[["service_key", "model_prob", "model_reasons", "label"]].sample(15, random_state=1))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 7 - Final index: LLM verdict where it exists, model elsewhere
# MAGIC | Row | Final evidence |
# MAGIC |---|---|
# MAGIC | LLM said not available / planned / referral | excluded (unchanged) |
# MAGIC | LLM reviewed (available / unclear) | LLM-adjusted evidence from `02` (unchanged) |
# MAGIC | Not reviewed by the LLM | band = **average of the rules band and the model band, rounded up** (model probability capped at 0.30 for travel-only sources) |
# MAGIC
# MAGIC Same column names as `care_finder_index_v2`, so `find_care()` and the gap analysis just read the new table.

# COMMAND ----------

ms = spark.table(f"{GOLD}.model_scores").select("facility_id", "service_key", "model_prob", "model_reasons")
final = (spark.table(V2).join(ms, ["facility_id", "service_key"], "left")
    .withColumn("evidence_source", F.when(F.col("reviewed"), "AI review").when(F.col("model_prob").isNotNull(), "rules + trained model").otherwise("rules"))
    .withColumn("adj_evidence",
        F.when(F.col("reviewed") | F.col("model_prob").isNull(), F.col("adj_evidence"))
         .when(F.coalesce(F.col("travel_only"), F.lit(False)), F.least(F.col("model_prob"), F.lit(0.30)))
         .otherwise(F.col("model_prob")))
    .withColumn("adj_evidence", F.round("adj_evidence", 3))
    .withColumn("adjusted_base_score", F.round(F.col("adj_evidence") * F.col("trust_score") * F.col("type_fit"), 4))
    # Not reviewed: average of the rules band and the model band (High 3 / Medium 2 / Low 1), rounded up.
    # Held-out (random-sample test rows, population-weighted) this beat either alone: High holds up ~78% while
    # covering ~26% of pairs (rules: 77% / 11%), and Low holds up ~2% (rules: 8%). See model_eval_bands.
    .withColumn("rules_rank", F.when(F.col("confidence") == "High", 3).when(F.col("confidence") == "Medium", 2).otherwise(1))
    .withColumn("model_band", F.when(F.col("adj_evidence") >= 0.70, "High").when(F.col("adj_evidence") >= 0.40, "Medium").otherwise("Low"))
    .withColumn("model_rank", F.when(F.col("model_band") == "High", 3).when(F.col("model_band") == "Medium", 2).otherwise(1))
    .withColumn("combined_rank", F.ceil((F.col("rules_rank") + F.col("model_rank")) / 2))
    .withColumn("adjusted_confidence",
        F.when(F.col("excluded"), "Excluded")
         .when(F.col("reviewed"), F.col("adjusted_confidence"))
         .when(F.col("model_prob").isNull(), F.col("confidence"))
         .when(F.col("combined_rank") >= 3, "High").when(F.col("combined_rank") >= 2, "Medium").otherwise("Low"))
    .withColumn("model_band", F.when(F.col("evidence_source") == "rules + trained model", F.col("model_band")))
    .drop("rules_rank", "model_rank", "combined_rank")
    .withColumn("all_cautions", F.when(F.col("evidence_source") == "rules + trained model",
        F.concat(F.col("all_cautions"), F.array(F.concat(F.lit("Rules + model estimate (not individually reviewed): "),
                                                         F.concat_ws(", ", "model_reasons")))))
        .otherwise(F.col("all_cautions"))))
final.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{GOLD}.care_finder_index_final")
display(spark.table(f"{GOLD}.care_finder_index_final").groupBy("evidence_source", "adjusted_confidence").count()
        .orderBy("evidence_source", "adjusted_confidence"))
print("Next: re-run 04_gap_analysis and 05_serving (they use care_finder_index_final automatically).")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 8 - Human audit (run again once teammates fill `audit_sample.audit_answer`)
# MAGIC `audit_answer`: yes_24x7 / yes_limited = 1, no = 0, no_answer = skipped.

# COMMAND ----------

aud = (spark.table(f"{GOLD}.audit_sample").where("audit_answer IS NOT NULL AND audit_answer <> 'no_answer'")
       .join(spark.table(f"{GOLD}.care_finder_index_final").select("facility_id", "service_key", "evidence_score", "llm_verdict",
             "reviewed", "model_prob").dropDuplicates(["facility_id", "service_key"]), ["facility_id", "service_key"], "left")
       .toPandas())
if len(aud):
    aud["truth"] = aud.audit_answer.isin(["yes_24x7", "yes_limited"]).astype(int)
    out = [dict(method="rules (Mekeli)", n=len(aud), accuracy=float(((aud.evidence_score.fillna(0) >= 0.4).astype(int) == aud.truth).mean()))]
    r = aud[aud.reviewed == True]
    if len(r):
        out.append(dict(method="LLM review", n=len(r), accuracy=float(((r.llm_verdict == "available").astype(int) == r.truth).mean())))
    m = aud[aud.model_prob.notna()]
    out.append(dict(method="trained model", n=len(m), accuracy=float(((m.model_prob >= T).astype(int) == m.truth).mean())))
    save_pdf(pd.DataFrame(out), f"{GOLD}.model_audit_eval")
    display(pd.DataFrame(out))
else:
    print("No audit answers yet. Fill hc_gold.audit_sample.audit_answer, then re-run this cell.")