# Databricks notebook source
# MAGIC %md
# MAGIC # Gold 34 · Learned confidence: rules vs LightGBM, calibration, bands, scores for every pair
# MAGIC
# MAGIC Spec: `docs/CONFIDENCE_MODEL_SPEC.md`, steps 4 and 5a. (`gold/30` gives the generic leaderboard; this
# MAGIC notebook answers the Care Finder questions.)
# MAGIC
# MAGIC 1. **Out-of-fold** LightGBM and logistic scores for every training pair, grouped by facility.
# MAGIC 2. **Rules vs model** on the same rows: AUC (weighted to the population and unweighted), precision of High.
# MAGIC 3. **Calibration**: cross-fitted isotonic, so "0.85" means about 85% of such claims hold up.
# MAGIC 4. **Stress test** (81 "planned / not available" claims), **priority holdout**, and the **hand audit** once filled.
# MAGIC 5. **Score all pairs**: `p_offered`, `model_band`, disagreement with the rules, top reasons (SHAP).
# MAGIC
# MAGIC | Output | What |
# MAGIC |---|---|
# MAGIC | `hc_gold.service_confidence_model` | every facility × service: p_offered, model_band, rules_confidence, disagreement, reasons |
# MAGIC | `hc_gold.confidence_model_report` | one row per metric (section, model, metric, value, n) |
# MAGIC | `hc_gold.confidence_model_calibration` | calibration bins (predicted vs observed) |
# MAGIC | `hc_gold.confidence_model_importance` | mean abs SHAP per input |

# COMMAND ----------

# MAGIC %pip install -q lightgbm shap

# COMMAND ----------

dbutils.library.restartPython()  # noqa: F821

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

import importlib
import os
import tempfile

import lightgbm as lgb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import mlflow  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.isotonic import IsotonicRegression  # noqa: E402
from sklearn.metrics import brier_score_loss, roc_auc_score  # noqa: E402
from sklearn.model_selection import GroupKFold, GroupShuffleSplit  # noqa: E402

import hc.model as hm  # noqa: E402
from hc.io import write_table  # noqa: E402

importlib.reload(hm)
G = cfg.gold
HIGH_CUT = float(widget(dbutils, "high_cut", "0.85", "calibrated p for High"))  # noqa: F821
MED_CUT = float(widget(dbutils, "medium_cut", "0.50", "calibrated p for Medium"))  # noqa: F821
N_FOLDS = int(widget(dbutils, "n_folds", "5"))  # noqa: F821
REGISTER_AS = widget(dbutils, "register_as", "care_finder_confidence", "UC model name (blank = skip)")  # noqa: F821

NUMERIC = [
    "n_fields", "n_direct_fields", "n_snippets", "n_direct_snippets", "has_specifics", "evidence_direct",
    "only_third_party_text", "evidence_chars", "wording_negation", "wording_future", "wording_referral", "name_conflict",
    "n_web_sources", "in_directory", "beds", "doctors", "facility_age_years", "ihds_peer_rate", "ihds_peer_n", "high_acuity",
]
CATEGORICAL = ["service_key", "facility_type", "name_kind", "ownership", "directory_ownership"]
PARAMS = dict(learning_rate=0.03, num_leaves=8, min_child_samples=25, subsample=0.8, subsample_freq=1,
              colsample_bytree=0.8, reg_lambda=1.0, random_state=42, verbose=-1)

feat = spark.table(G("confidence_features")).toPandas()
NUMERIC += sorted(c for c in feat.columns if c.startswith("flag_"))
fs = hm.FeatureSet(numeric=NUMERIC, categorical=CATEGORICAL)
X_all = hm.build_X(feat, fs)  # built on all pairs so categories match between training and scoring
key = feat["facility_id"] + "|" + feat["service_key"]

labels = spark.table(G("llm_labels")).toPandas()
labels["key"] = labels["facility_id"] + "|" + labels["service_key"]
pos = pd.Series(np.arange(len(feat)), index=key)


def rows(origin: str, labelled: bool = True) -> pd.DataFrame:
    d = labels[(labels["origin"] == origin) & (labels["key"].isin(pos.index))]
    d = d[d["label"].notna()] if labelled else d
    return d.assign(row=pos[d["key"]].to_numpy()).reset_index(drop=True)


tr = rows("random")
X, y = X_all.iloc[tr["row"]].reset_index(drop=True), tr["label"].astype(int)
w = tr["sample_weight"].astype(float).to_numpy()
groups = tr["facility_id"]
print(f"training pairs {len(y)} · facilities {groups.nunique()} · positive rate {y.mean():.1%} (weighted {np.average(y, weights=w):.1%})")
unclear = labels[(labels["origin"] == "random") & labels["label"].isna()]
print(f"random pairs left out as unclear/error: {len(unclear)} of {(labels['origin'] == 'random').sum()}")

# COMMAND ----------

# MAGIC %md ## 1 · Out-of-fold scores (grouped by facility; trees picked by an inner early-stopping split)

# COMMAND ----------


def fit_lgbm(Xt, yt, gt):
    gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    a, v = next(gss.split(Xt, yt, gt))
    probe = lgb.LGBMClassifier(n_estimators=2000, **PARAMS)
    probe.fit(Xt.iloc[a], yt.iloc[a], eval_set=[(Xt.iloc[v], yt.iloc[v])], callbacks=[lgb.early_stopping(100, verbose=False)])
    n = max(int(probe.best_iteration_ or 0), 30)
    return lgb.LGBMClassifier(n_estimators=n, **PARAMS).fit(Xt, yt), n


oof = {"lightgbm": np.full(len(y), np.nan), "logistic": np.full(len(y), np.nan)}
oof_fold = np.full(len(y), -1)
contrib = np.zeros((len(y), X.shape[1] + 1))
best_iters = []
for k, (a, b) in enumerate(GroupKFold(n_splits=N_FOLDS).split(X, y, groups)):
    m, n = fit_lgbm(X.iloc[a], y.iloc[a], groups.iloc[a])
    best_iters.append(n)
    oof["lightgbm"][b] = m.predict_proba(X.iloc[b])[:, 1]
    contrib[b] = m.predict(X.iloc[b], pred_contrib=True)
    lin = hm.make_linear("binary", fs).fit(hm.linear_input(X.iloc[a], fs), y.iloc[a])
    oof["logistic"][b] = lin.predict_proba(hm.linear_input(X.iloc[b], fs))[:, 1]
    oof_fold[b] = k
print("trees per fold:", best_iters)

# cross-fitted isotonic calibration: each fold is calibrated on the other folds' out-of-fold scores
p_cal = np.full(len(y), np.nan)
for k in range(N_FOLDS):
    o, t = oof_fold != k, oof_fold == k
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(oof["lightgbm"][o], y[o], sample_weight=w[o])
    p_cal[t] = iso.predict(oof["lightgbm"][t])

# COMMAND ----------

# MAGIC %md ## 2 · Rules vs model on the same out-of-fold rows

# COMMAND ----------

rules_rank = {"Low": 0, "Medium": 1, "High": 2}
feat_tr = feat.iloc[tr["row"]].reset_index(drop=True)
scores = {
    "rules: evidence score": feat_tr["rules_evidence_score"].to_numpy(),
    "rules: base score (evidence x trust x type fit)": feat_tr["rules_base_score"].to_numpy(),
    "rules: High/Medium/Low": feat_tr["rules_confidence"].map(rules_rank).to_numpy(),
    "logistic (out of fold)": oof["logistic"],
    "lightgbm (out of fold)": oof["lightgbm"],
    "lightgbm calibrated (out of fold)": p_cal,
}
report = []


def add(section, model, metric, value, n=None):
    report.append({"section": section, "model": model, "metric": metric, "value": float(value), "n": None if n is None else int(n)})


for name, s in scores.items():
    ok = ~np.isnan(s)
    add("rules_vs_model", name, "auc_weighted", roc_auc_score(y[ok], s[ok], sample_weight=w[ok]), ok.sum())
    add("rules_vs_model", name, "auc_unweighted", roc_auc_score(y[ok], s[ok]), ok.sum())
add("rules_vs_model", "lightgbm calibrated (out of fold)", "brier_weighted", brier_score_loss(y, p_cal, sample_weight=w), len(y))


def band(p):
    return np.where(p >= HIGH_CUT, "High", np.where(p >= MED_CUT, "Medium", "Low"))


model_band = band(p_cal)
for who, bands in {"rules": feat_tr["rules_confidence"].to_numpy(), "model": model_band}.items():
    for bnd in ["High", "Medium", "Low"]:
        m = bands == bnd
        if m.sum():
            add("band_precision", who, f"{bnd}: share that hold up (weighted)", np.average(y[m], weights=w[m]), m.sum())
            add("band_precision", who, f"{bnd}: share of all pairs (weighted)", w[m].sum() / w.sum(), m.sum())

rep = pd.DataFrame(report)
display(rep.pivot_table(index="model", columns="metric", values="value", aggfunc="first").round(3))  # noqa: F821
display(rep[rep.section == "band_precision"].round(3))  # noqa: F821

# COMMAND ----------

# MAGIC %md ## 3 · Calibration (out of fold): when the model says 0.8, how often is it right?

# COMMAND ----------

cal_rows = []
for name, p in {"raw": oof["lightgbm"], "calibrated": p_cal}.items():
    bins = np.clip((p * 10).astype(int), 0, 9)
    for bi in range(10):
        m = bins == bi
        if m.sum():
            cal_rows.append({"score": name, "bin": f"{bi / 10:.1f}-{(bi + 1) / 10:.1f}", "mean_predicted": float(np.average(p[m], weights=w[m])),
                             "observed": float(np.average(y[m], weights=w[m])), "n": int(m.sum())})
cal = pd.DataFrame(cal_rows)
display(cal)  # noqa: F821

plot_dir = tempfile.mkdtemp()
fig, ax = plt.subplots(figsize=(5, 5))
ax.plot([0, 1], [0, 1], "--", color="grey", lw=1)
for name, g in cal.groupby("score"):
    ax.plot(g["mean_predicted"], g["observed"], "o-", label=name)
ax.set_xlabel("predicted chance the claim holds up")
ax.set_ylabel("observed share (LLM label, population-weighted)")
ax.set_title("Calibration, out of fold")
ax.legend()
cal_png = os.path.join(plot_dir, "calibration.png")
fig.savefig(cal_png, dpi=120, bbox_inches="tight")
plt.close(fig)

# COMMAND ----------

# MAGIC %md ## 4 · Final model, stress test, priority holdout, hand audit

# COMMAND ----------

final, n_trees = fit_lgbm(X, y, groups)
iso_final = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(oof["lightgbm"], y, sample_weight=w)


def predict(rows_idx):
    Xs = X_all.iloc[rows_idx]
    return iso_final.predict(final.predict_proba(Xs)[:, 1])


for origin in ["priority_negation", "priority_high_acuity"]:
    d = rows(origin, labelled=False)
    if not len(d):
        continue
    p = predict(d["row"])
    rc = feat.iloc[d["row"]]["rules_confidence"].to_numpy()
    add(origin, "model", "share rated High", (band(p) == "High").mean(), len(d))
    add(origin, "rules", "share rated High", (rc == "High").mean(), len(d))
    add(origin, "model", "share rated Low", (band(p) == "Low").mean(), len(d))
    lab = d["label"].notna().to_numpy()
    if lab.sum() > 10 and d.loc[lab, "label"].nunique() == 2:
        add(origin, "model", "auc", roc_auc_score(d.loc[lab, "label"].astype(int), p[lab]), lab.sum())
        add(origin, "rules", "auc", roc_auc_score(d.loc[lab, "label"].astype(int), feat.iloc[d.loc[lab, "row"]]["rules_evidence_score"]), lab.sum())

aud = spark.table(G("audit_sample")).select("facility_id", "service_key", "audit_answer").toPandas()
aud["human"] = aud["audit_answer"].map({"yes_24x7": 1, "yes_limited": 1, "no": 0})
aud = aud[aud["human"].notna()]
aud["key"] = aud["facility_id"] + "|" + aud["service_key"]
aud = aud[aud["key"].isin(pos.index)]
if len(aud):
    r = pos[aud["key"]].to_numpy()
    p = predict(r)
    llm = labels.drop_duplicates("key").set_index("key")["label"].reindex(aud["key"]).to_numpy()
    h = aud["human"].to_numpy()
    add("hand_audit", "model", "accuracy (p >= medium cut = yes)", ((p >= MED_CUT).astype(int) == h).mean(), len(h))
    add("hand_audit", "rules", "accuracy (High or Medium = yes)", (feat.iloc[r]["rules_confidence"].isin(["High", "Medium"]).astype(int).to_numpy() == h).mean(), len(h))
    m = ~pd.isna(llm)
    if m.sum():
        add("hand_audit", "llm", "agreement with humans", (llm[m].astype(int) == h[m]).mean(), m.sum())
    print(f"hand audit: {len(h)} answered")
else:
    print("hand audit: no answers yet (fill hc_gold.audit_sample.audit_answer, then re-run this notebook)")

# COMMAND ----------

# MAGIC %md ## 5 · Score every pair, with reasons (SHAP)

# COMMAND ----------

raw_all = final.predict_proba(X_all)[:, 1]
p_all = iso_final.predict(raw_all)
c_all = final.predict(X_all, pred_contrib=True)[:, :-1]
names = np.array(X_all.columns)


def shown(v):
    return "null" if pd.isna(v) else (f"{v:.3g}" if isinstance(v, (float, np.floating)) else str(v))


up1, up2, down1, keys_up, keys_down = [], [], [], [], []
order = np.argsort(-c_all, axis=1)
for i in range(len(X_all)):
    ups = [j for j in order[i, :2] if c_all[i, j] > 0]
    dn = order[i, -1]
    txt = [f"{names[j]}={shown(X_all.iat[i, j])} (+{c_all[i, j]:.2f})" for j in ups]
    up1.append(txt[0] if txt else None)
    up2.append(txt[1] if len(txt) > 1 else None)
    down1.append(f"{names[dn]}={shown(X_all.iat[i, dn])} ({c_all[i, dn]:.2f})" if c_all[i, dn] < 0 else None)
    keys_up.append([str(names[j]) for j in ups])
    keys_down.append([str(names[dn])] if c_all[i, dn] < 0 else [])

rc = feat["rules_confidence"].to_numpy()
mb = band(p_all)
out = pd.DataFrame({
    "facility_id": feat["facility_id"], "service_key": feat["service_key"],
    "p_offered": np.round(p_all, 4), "p_raw": np.round(raw_all, 4), "model_band": mb, "rules_confidence": rc,
    "disagreement": np.where((rc == "High") & (mb == "Low"), "rules_high_model_low",
                             np.where((rc == "Low") & (mb == "High"), "rules_low_model_high", None)),
    "reason_up_1": up1, "reason_up_2": up2, "reason_down_1": down1,
    "reason_keys_up": keys_up, "reason_keys_down": keys_down,
})
sdf = spark.createDataFrame(out).withColumn("scored_at", F.current_timestamp())
write_table(sdf, G("service_confidence_model"))
spark.sql(f"COMMENT ON TABLE {G('service_confidence_model')} IS 'Learned confidence for every facility x service (gold/34). p_offered = calibrated chance the record supports the service now (LLM-label scale). model_band cut-offs: High >= {HIGH_CUT}, Medium >= {MED_CUT}. Ranking still uses cited evidence; this only changes how sure we say we are.'")

for bnd in ["High", "Medium", "Low"]:
    add("all_pairs", "model", f"{bnd}: pairs", (mb == bnd).sum())
    add("all_pairs", "rules", f"{bnd}: pairs", (rc == bnd).sum())
add("all_pairs", "model", "disagreements: rules High, model Low", ((rc == "High") & (mb == "Low")).sum())
add("all_pairs", "model", "disagreements: rules Low, model High", ((rc == "Low") & (mb == "High")).sum())

# COMMAND ----------

# MAGIC %md ## 6 · Importance, MLflow, report tables

# COMMAND ----------

importance = hm.feature_importance(X, contrib)
display(importance.head(20))  # noqa: F821
plots = hm.shap_plots(X, contrib, plot_dir) + [cal_png]

rep = pd.DataFrame(report)
user = spark.sql("SELECT current_user()").first()[0]
mlflow.set_registry_uri("databricks-uc")
mlflow.set_experiment(f"/Users/{user}/hc_datathon_models")
mlflow.end_run()
with mlflow.start_run(run_name="care_finder_confidence") as run:
    mlflow.log_params({**PARAMS, "n_estimators": n_trees, "n_train": len(y), "n_features": X.shape[1],
                       "high_cut": HIGH_CUT, "medium_cut": MED_CUT, "label_source": "llm_labels (random, stratified)", "group": "facility_id"})
    for r_ in report:
        mlflow.log_metric(f"{r_['section']}.{r_['model']}.{r_['metric']}"[:250].replace(" ", "_").replace(":", "").replace("(", "").replace(")", "").replace("/", "_").replace(",", "").replace(">=", "ge").replace("+", "plus"), r_["value"])
    for p in plots:
        mlflow.log_artifact(p, "plots")
    try:
        kw = {"sk_model": final, "input_example": X.head(5)}
        if REGISTER_AS:
            kw["registered_model_name"] = f"{cfg.catalog}.{cfg.gold_schema}.{REGISTER_AS}"
        try:
            mlflow.sklearn.log_model(name="model", **kw)
        except TypeError:
            mlflow.sklearn.log_model(artifact_path="model", **kw)
    except Exception as e:
        print("model logging/registration skipped:", str(e)[:300])
    run_id = run.info.run_id

meta = {"run_id": run_id}
write_table(spark.createDataFrame(rep.assign(**meta)).withColumn("logged_at", F.current_timestamp()), G("confidence_model_report"))
write_table(spark.createDataFrame(cal.assign(**meta)), G("confidence_model_calibration"))
write_table(spark.createDataFrame(importance.assign(**meta)), G("confidence_model_importance"))
print("MLflow run", run_id)
display(rep.round(3))  # noqa: F821
