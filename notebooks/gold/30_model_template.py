# Databricks notebook source
# MAGIC %md
# MAGIC # Gold 30 · Model template: any table + target → baseline vs LightGBM → SHAP → decision table
# MAGIC
# MAGIC Point it at a table and a target column. It will:
# MAGIC
# MAGIC 1. **Pick features** and say why it left every other column out (ids, dates, free text, mostly-null, excluded).
# MAGIC 2. **Scan for leakage**: any single column that predicts the target almost perfectly is flagged.
# MAGIC 3. **Train three models** on the same split: a dummy (the base rate / mean), an interpretable linear
# MAGIC    model, and LightGBM. If LightGBM doesn't beat linear, say so; that's a finding too.
# MAGIC 4. **Score every row out-of-fold** (each row scored by a model that never saw it) and compute SHAP values.
# MAGIC 5. **Log everything to MLflow** (parent run + one child run per model, plots, tables, the model).
# MAGIC 6. **Write decision tables to gold**: per-row ranking with the top 3 reasons, feature importance, leaderboard.
# MAGIC
# MAGIC | Widget | Meaning |
# MAGIC |---|---|
# MAGIC | `source_table` | name in the gold schema, or a full `catalog.schema.table` |
# MAGIC | `target_col` | what to predict. 2 values → classification; numeric → regression |
# MAGIC | `positive_class` | makes a categorical target binary, e.g. `Expired`, `Readmitted` |
# MAGIC | `id_cols` | carried to the output, never used as features |
# MAGIC | `exclude_cols` | globs for leakage / other outcomes, e.g. `overdose_*,discharge_*` |
# MAGIC | `group_col` | keep groups on one side of every split (state, hospital, patient) |
# MAGIC | `register_as` | blank = don't register; otherwise a UC model name in the gold schema |
# MAGIC
# MAGIC **Default run (works before kickoff):** which counties have more overdose deaths than their social,
# MAGIC health and access profile predicts? Split by state so the score reflects unseen states.
# MAGIC Note: counties with a suppressed count (1-9 deaths) have a NULL target and are left out, which skews
# MAGIC the training set toward larger counties. Say that out loud in the video.

# COMMAND ----------

# MAGIC %pip install -q lightgbm shap

# COMMAND ----------

dbutils.library.restartPython()  # noqa: F821

# COMMAND ----------

# MAGIC %run ../_setup

# COMMAND ----------

import base64
import importlib
import json
import tempfile

import mlflow
import numpy as np
import pandas as pd
from pyspark.sql import types as T

import hc.model as hm
from hc.io import write_table
from hc.naming import snake

importlib.reload(hm)

source_table = widget(dbutils, "source_table", "county_context", "table (gold name or catalog.schema.table)")
target_col = widget(dbutils, "target_col", "overdose_deaths_per_100k", "target column")
task_in = widget(dbutils, "task", "auto", "auto | binary | regression")
positive_class = widget(dbutils, "positive_class", "", "binary from a category, e.g. Expired")
id_cols = hm.parse_list(widget(dbutils, "id_cols", "fips,state_abbr,state_name,county_name", "id / display columns"))
exclude = hm.parse_list(widget(dbutils, "exclude_cols", "overdose_*,rucc_description", "exclude globs (leakage)"))
group_col = widget(dbutils, "group_col", "state_abbr", "group split column (blank = random)")
test_size = float(widget(dbutils, "test_size", "0.2"))
n_folds = int(widget(dbutils, "n_folds", "5"))
max_rows = int(widget(dbutils, "max_rows", "500000", "row cap (sampled above this)"))
run_label = widget(dbutils, "run_name", "", "blank = <table>__<target>")
experiment = widget(dbutils, "experiment", "", "blank = /Users/<you>/hc_datathon_models")
register_as = widget(dbutils, "register_as", "", "UC model name to register (blank = skip)")

table_fqn = source_table if "." in source_table else cfg.gold(source_table)
run_name = run_label or f"{source_table.split('.')[-1]}__{target_col}"
print(f"table={table_fqn}  target={target_col}  run={run_name}")

# COMMAND ----------

# MAGIC %md ## 1 · Load (booleans → 0/1, decimals → double; rows with a NULL target are dropped and counted)

# COMMAND ----------

raw = spark.table(table_fqn)
assert target_col in raw.columns, f"{target_col} not in {table_fqn}: {raw.columns}"
if group_col:
    assert group_col in raw.columns, f"group_col {group_col} not in table"

n_all = raw.count()
sdf = raw.where(F.col(target_col).isNotNull())
sdf = sdf.select(
    *[
        F.col(f.name).cast("int").alias(f.name)
        if isinstance(f.dataType, T.BooleanType)
        else F.col(f.name).cast("double").alias(f.name)
        if isinstance(f.dataType, T.DecimalType)
        else F.col(f.name)
        for f in sdf.schema.fields
    ]
)
n_labeled = sdf.count()
if n_labeled > max_rows:
    sdf = sdf.sample(fraction=min(1.0, 1.05 * max_rows / n_labeled), seed=42).limit(max_rows)
pdf = sdf.toPandas().reset_index(drop=True)

print(f"{n_all:,} rows in table · {n_all - n_labeled:,} with NULL target dropped ({(n_all - n_labeled) / max(n_all, 1):.1%}) · {len(pdf):,} used")

# COMMAND ----------

# MAGIC %md ## 2 · Target, features, leakage scan

# COMMAND ----------

y, task, target_note = hm.make_target(pdf[target_col], task_in, positive_class)
fs = hm.select_features(pdf, target_col, id_cols, exclude)
X = hm.build_X(pdf, fs)
groups = pdf[group_col] if group_col else None

print(f"task={task} ({target_note})")
print(f"{len(fs.numeric)} numeric + {len(fs.categorical)} categorical features, {len(fs.dropped)} columns left out")
if task == "binary":
    print(f"positive rate {y.mean():.2%} ({int(y.sum()):,} of {len(y):,})")
else:
    print(y.describe().round(3).to_string())
display(fs.dropped_frame())  # noqa: F821

leak = hm.leakage_scan(X, y, task)
display(leak.head(20))  # noqa: F821
if leak["suspicious"].any():
    print(
        "WARNING: possible leakage, these alone almost predict the target:",
        leak.loc[leak["suspicious"], "feature"].tolist(),
        "\nIf they are the outcome measured another way, add them to exclude_cols and re-run.",
    )

# COMMAND ----------

# MAGIC %md ## 3 · Dummy vs linear vs LightGBM on one held-out split

# COMMAND ----------

train_idx, test_idx = hm.split_rows(y, task, test_size, groups)
fitted = hm.fit_all(X, y, task, fs, train_idx, test_idx)
board = hm.leaderboard(fitted)
display(board)  # noqa: F821

primary = "roc_auc" if task == "binary" else "r2"
if primary in board.columns:
    s = board.set_index("model")[primary]
    print(f"{primary}: dummy {s['dummy']:.3f} · linear {s['linear']:.3f} · lightgbm {s['lightgbm']:.3f}")
    if s["lightgbm"] <= s["linear"] + 0.005:
        print("LightGBM is not clearly better than linear: lead with the linear model (easier to explain).")
print(f"LightGBM trees (early stopping): {fitted['lightgbm'].best_iter}")

# COMMAND ----------

# MAGIC %md ## 4 · Out-of-fold scores + SHAP for every row

# COMMAND ----------

oof_score, oof_fold, contrib = hm.out_of_fold(X, y, task, fitted["lightgbm"].best_iter, n_folds, groups)
oof_metrics = hm.metrics(y, oof_score, task)
print("out-of-fold LightGBM:", oof_metrics)

importance = hm.feature_importance(X, contrib)
display(importance.head(25))  # noqa: F821

plot_dir = tempfile.mkdtemp()
plots = hm.shap_plots(X, contrib, plot_dir)
for p in plots:
    with open(p, "rb") as fh:
        displayHTML(f'<img src="data:image/png;base64,{base64.b64encode(fh.read()).decode()}" style="max-width:900px"/>')  # noqa: F821

# COMMAND ----------

# MAGIC %md ## 5 · Log to MLflow (parent run + a child run per model)

# COMMAND ----------

user = spark.sql("SELECT current_user()").first()[0]
mlflow.set_registry_uri("databricks-uc")
mlflow.set_experiment(experiment or f"/Users/{user}/hc_datathon_models")
mlflow.autolog(disable=True)  # we log explicitly; avoids duplicate auto-runs
mlflow.end_run()  # close a run left open by an earlier failed cell

common = {
    "source_table": table_fqn,
    "target": target_col,
    "task": task,
    "target_note": target_note,
    "group_col": group_col or "(random)",
    "n_rows": len(y),
    "n_rows_null_target": n_all - n_labeled,
    "n_features": len(fs.all),
}


def _log_model(model, X_example, task):
    """Log the LightGBM model; register to UC if register_as is set. Never fails the notebook."""
    from mlflow.models import infer_signature

    ex = X_example.head(5)
    kwargs = {"sk_model": model, "input_example": ex}
    try:
        kwargs["signature"] = infer_signature(ex, hm.predict_score(model, ex, task))
    except Exception as e:  # categorical dtypes can trip signature inference
        print("signature skipped:", str(e)[:200])
    if register_as:
        kwargs["registered_model_name"] = f"{cfg.catalog}.{cfg.gold_schema}.{snake(register_as)}"
    try:
        try:
            return mlflow.sklearn.log_model(name="model", **kwargs)  # MLflow 3
        except TypeError:
            return mlflow.sklearn.log_model(artifact_path="model", **kwargs)  # MLflow 2
    except Exception as e:
        print("model logging failed (metrics and plots are still logged):", str(e)[:300])


with mlflow.start_run(run_name=run_name) as parent:
    run_id = parent.info.run_id
    mlflow.set_tags({"project": "hc_datathon", "source_table": table_fqn, "target": target_col})
    mlflow.log_params(common)
    for name, f in fitted.items():
        mlflow.log_metrics({f"test_{k}__{name}": v for k, v in f.test_metrics.items()})
        with mlflow.start_run(run_name=f"{run_name}__{name}", nested=True):
            mlflow.log_params({**common, "model": name})
            mlflow.log_metrics({f"test_{k}": v for k, v in f.test_metrics.items()})
            if name == "lightgbm":
                mlflow.log_params({**hm.LGBM_PARAMS, "n_estimators": f.best_iter})
                mlflow.log_metrics({f"oof_{k}": v for k, v in oof_metrics.items()})
                _log_model(f.model, X.iloc[train_idx], task)
    mlflow.log_metrics({f"oof_{k}__lightgbm": v for k, v in oof_metrics.items()})
    for p in plots:
        mlflow.log_artifact(p, "shap")
    for fname, frame in {"leaderboard.csv": board, "feature_importance.csv": importance,
                         "leakage_scan.csv": leak, "dropped_columns.csv": fs.dropped_frame()}.items():
        path = f"{plot_dir}/{fname}"
        frame.to_csv(path, index=False)
        mlflow.log_artifact(path, "tables")

print(f"MLflow run {run_id} in experiment {mlflow.get_experiment(parent.info.experiment_id).name}")

# COMMAND ----------

# MAGIC %md ## 6 · Decision tables in gold
# MAGIC
# MAGIC * `pred_<run>`: one row per input row, scored out-of-fold, ranked, with the top 3 reasons.
# MAGIC   Regression → `excess` = actual − predicted (**higher than expected**). Binary → `risk_score`, `risk_decile`.
# MAGIC * `model_feature_importance`, `model_leaderboard`: appended per run, keyed by `run_id`, for the dashboard.

# COMMAND ----------

pred_table = snake(f"pred_{run_name}")
keep = [c for c in id_cols if c in pdf.columns] or [c for c in pdf.columns if c != target_col]
out = pd.concat(
    [
        pdf[keep].reset_index(drop=True),
        pd.DataFrame({"actual": y.to_numpy(), "cv_fold": oof_fold}),
        hm.decision_columns(y, oof_score, task).reset_index(drop=True),
        hm.reason_codes(X, contrib).reset_index(drop=True),
    ],
    axis=1,
)
for c in [c for c in out.columns if c.startswith("reason_")]:
    out[c] = out[c].astype("string")  # an all-NULL object column would become a VOID type Delta can't store
pred_sdf = spark.createDataFrame(out)
pred_sdf = pred_sdf.select(
    *[
        F.when(F.isnan(F.col(f.name)), None).otherwise(F.col(f.name)).alias(f.name)
        if isinstance(f.dataType, (T.DoubleType, T.FloatType))
        else F.col(f.name)
        for f in pred_sdf.schema.fields
    ]
).withColumn("run_id", F.lit(run_id)).withColumn("scored_at", F.current_timestamp())
write_table(pred_sdf, cfg.gold(pred_table))
spark.sql(
    f"COMMENT ON TABLE {cfg.gold(pred_table)} IS 'Out-of-fold LightGBM scores for {target_col} from {table_fqn} "
    f"(MLflow run {run_id}). reason_1..3 = features pushing the prediction up most.'"
)

meta = {"run_id": run_id, "run_name": run_name, "source_table": table_fqn, "target": target_col, "task": task}
imp_sdf = spark.createDataFrame(importance.assign(**meta)).withColumn("logged_at", F.current_timestamp())
write_table(imp_sdf, cfg.gold("model_feature_importance"), mode="append")

long = [
    {**meta, "model": m, "eval": "holdout", "metric": k, "value": float(v)} for m, f in fitted.items() for k, v in f.test_metrics.items()
] + [{**meta, "model": "lightgbm", "eval": "out_of_fold", "metric": k, "value": float(v)} for k, v in oof_metrics.items()]
write_table(spark.createDataFrame(pd.DataFrame(long)).withColumn("logged_at", F.current_timestamp()), cfg.gold("model_leaderboard"), mode="append")

rank_col = "risk_rank" if task == "binary" else "excess_rank"
display(spark.table(cfg.gold(pred_table)).orderBy(rank_col).limit(25))  # noqa: F821

# COMMAND ----------

summary = {
    "run_id": run_id,
    "pred_table": f"{cfg.catalog}.{cfg.gold_schema}.{pred_table}",
    "task": task,
    "n_rows": len(y),
    "n_features": len(fs.all),
    "holdout": {m: f.test_metrics for m, f in fitted.items()},
    "out_of_fold": oof_metrics,
    "top_features": importance.head(10)[["feature", "direction"]].values.tolist(),
    "leakage_flags": leak.loc[leak["suspicious"], "feature"].tolist(),
}
print(json.dumps(summary, indent=2, default=str))
dbutils.notebook.exit(json.dumps(summary, default=str))  # noqa: F821
