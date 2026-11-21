"""Model template helpers: target + feature prep, leakage scan, baselines, LightGBM, out-of-fold
scoring with SHAP reason codes, and decision-ready ranking columns.

Pure pandas / scikit-learn / LightGBM (no Spark), so notebooks pass a pandas frame in and get
pandas frames back. Needs `%pip install lightgbm shap` first (shap is only used for plots).

Typical use (see notebooks/gold/30_model_template.py):
    y, task = make_target(pdf[target], task="auto", positive_class="")
    feats = select_features(pdf, target, id_cols, exclude_patterns)
    X = build_X(pdf, feats)
    split = split_rows(y, task, test_size=0.2, groups=None)
    fitted = fit_all(X, y, task, split)            # dummy, linear, lightgbm + metrics
    oof = out_of_fold(X, y, task, fitted["lightgbm"].best_iter, groups=None)
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------------------------
# Parsing helpers
# --------------------------------------------------------------------------------------------


def parse_list(text: str | None) -> list[str]:
    """'a, b ,c' -> ['a', 'b', 'c']"""
    return [x.strip() for x in (text or "").split(",") if x.strip()]


def matches_any(name: str, patterns: list[str]) -> bool:
    """Glob match: 'overdose_*' matches 'overdose_deaths_latest'."""
    return any(fnmatch.fnmatch(name, p) for p in patterns)


# --------------------------------------------------------------------------------------------
# Target
# --------------------------------------------------------------------------------------------


def make_target(s: pd.Series, task: str = "auto", positive_class: str = "") -> tuple[pd.Series, str, str]:
    """Return (y, task, note). task is 'binary' or 'regression'.

    positive_class turns any categorical target into binary: e.g. discharge_status == 'Expired'.
    Multiclass is deliberately not supported: pick the class that matters and make it binary.
    """
    if positive_class:
        y = (s.astype(str).str.strip().str.lower() == positive_class.strip().lower()).astype(int)
        return y, "binary", f"1 = target equals '{positive_class}'"

    values = s.dropna().unique()
    n_unique = len(values)
    if task == "auto":
        if n_unique == 2:
            task = "binary"
        elif pd.api.types.is_numeric_dtype(s):
            task = "regression"
        else:
            raise ValueError(
                f"Target has {n_unique} distinct non-numeric values. Set positive_class to the outcome "
                "that matters (e.g. 'Expired') to make it binary."
            )

    if task == "binary":
        if n_unique != 2:
            raise ValueError(f"Binary task needs exactly 2 target values, found {n_unique}. Use positive_class.")
        ordered = sorted(values.tolist(), key=lambda v: str(v).lower())
        truthy = [v for v in ordered if str(v).strip().lower() in ("1", "1.0", "true", "yes", "y")]
        pos = truthy[0] if truthy else ordered[-1]
        return (s == pos).astype(int), "binary", f"1 = target equals {pos!r}"

    if task == "regression":
        return pd.to_numeric(s, errors="coerce").astype(float), "regression", "numeric target"

    raise ValueError(f"Unknown task {task!r}: use auto, binary or regression")


# --------------------------------------------------------------------------------------------
# Features
# --------------------------------------------------------------------------------------------


@dataclass
class FeatureSet:
    numeric: list[str] = field(default_factory=list)
    categorical: list[str] = field(default_factory=list)
    dropped: dict[str, str] = field(default_factory=dict)  # column -> reason

    @property
    def all(self) -> list[str]:
        return self.numeric + self.categorical

    def dropped_frame(self) -> pd.DataFrame:
        return pd.DataFrame(sorted(self.dropped.items()), columns=["column", "reason"])


def select_features(
    df: pd.DataFrame,
    target: str,
    id_cols: list[str],
    exclude_patterns: list[str],
    max_null_frac: float = 0.95,
    max_categories: int = 50,
) -> FeatureSet:
    """Pick model features and record why every other column was left out."""
    fs = FeatureSet()
    for c in df.columns:
        s = df[c]
        if c == target:
            continue
        if c in id_cols:
            fs.dropped[c] = "id column"
        elif c.startswith("_"):
            fs.dropped[c] = "metadata column"
        elif matches_any(c, exclude_patterns):
            fs.dropped[c] = "excluded by pattern (leakage / not a feature)"
        elif pd.api.types.is_datetime64_any_dtype(s) or _looks_like_dates(s):
            fs.dropped[c] = "date/time: engineer features (age, days since, month) in a gold table first"
        elif s.isna().mean() > max_null_frac:
            fs.dropped[c] = f"more than {max_null_frac:.0%} null"
        elif s.nunique(dropna=True) <= 1:
            fs.dropped[c] = "constant"
        elif pd.api.types.is_bool_dtype(s) or pd.api.types.is_numeric_dtype(s):
            fs.numeric.append(c)
        elif s.nunique(dropna=True) > max_categories:
            fs.dropped[c] = f"text with more than {max_categories} distinct values (free text or an id)"
        else:
            fs.categorical.append(c)
    if not fs.all:
        raise ValueError("No usable features left. Check id_cols / exclude_cols.")
    return fs


def _looks_like_dates(s: pd.Series) -> bool:
    if s.dtype != object:
        return False
    sample = s.dropna().head(50)
    return len(sample) > 0 and all(hasattr(v, "year") and hasattr(v, "month") for v in sample)


def build_X(df: pd.DataFrame, fs: FeatureSet) -> pd.DataFrame:
    """Numeric -> float, categorical -> pandas 'category' (LightGBM uses it natively)."""
    X = pd.DataFrame(index=df.index)
    for c in fs.numeric:
        X[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    for c in fs.categorical:
        X[c] = df[c].astype("string").astype("category")
    return X


def leakage_scan(X: pd.DataFrame, y: pd.Series, task: str, threshold: float = 0.95) -> pd.DataFrame:
    """Single-feature strength vs the target. A feature that alone predicts the target almost
    perfectly is usually leakage (the outcome measured another way), not a discovery."""
    from sklearn.metrics import roc_auc_score

    rows = []
    for c in X.columns:
        x = X[c]
        if isinstance(x.dtype, pd.CategoricalDtype):
            x = x.cat.codes.replace(-1, np.nan).astype(float)  # rough, ordinal codes
        mask = x.notna() & y.notna()
        if mask.sum() < 20 or x[mask].nunique() < 2:
            continue
        if task == "binary":
            if y[mask].nunique() < 2:
                continue
            auc = roc_auc_score(y[mask], x[mask])
            score, metric = max(auc, 1 - auc), "single-feature AUC"
        else:
            score, metric = abs(x[mask].rank().corr(y[mask].rank())), "abs Spearman"
        rows.append((c, metric, round(float(score), 4)))
    out = pd.DataFrame(rows, columns=["feature", "metric", "score"]).sort_values("score", ascending=False)
    out["suspicious"] = out["score"] >= threshold
    return out.reset_index(drop=True)


# --------------------------------------------------------------------------------------------
# Splits
# --------------------------------------------------------------------------------------------


def split_rows(y: pd.Series, task: str, test_size: float = 0.2, groups: pd.Series | None = None, seed: int = 42):
    """Return (train_idx, test_idx) as positional arrays.
    groups (e.g. state, hospital, patient id) keeps every row of a group on one side, so the test
    score reflects generalization to new groups instead of memorized ones."""
    from sklearn.model_selection import GroupShuffleSplit, train_test_split

    idx = np.arange(len(y))
    if groups is not None:
        gss = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=seed)
        return next(gss.split(idx, y, groups.fillna("__missing__").astype(str)))
    strat = y if task == "binary" and y.value_counts().min() >= 2 else None
    return train_test_split(idx, test_size=test_size, random_state=seed, stratify=strat)


def _folds(y: pd.Series, task: str, n_folds: int, groups: pd.Series | None, seed: int = 42):
    from sklearn.model_selection import GroupKFold, KFold, StratifiedKFold

    idx = np.arange(len(y))
    if groups is not None:
        g = groups.fillna("__missing__").astype(str)
        return GroupKFold(n_splits=min(n_folds, g.nunique())).split(idx, y, g)
    if task == "binary":
        return StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=seed).split(idx, y)
    return KFold(n_splits=n_folds, shuffle=True, random_state=seed).split(idx, y)


# --------------------------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------------------------

LGBM_PARAMS = dict(
    learning_rate=0.03,
    num_leaves=31,
    min_child_samples=20,
    subsample=0.8,
    subsample_freq=1,
    colsample_bytree=0.8,
    reg_lambda=1.0,
    random_state=42,
    verbose=-1,
)


def make_dummy(task: str):
    from sklearn.dummy import DummyClassifier, DummyRegressor

    return DummyClassifier(strategy="prior") if task == "binary" else DummyRegressor(strategy="mean")


def make_linear(task: str, fs: FeatureSet):
    """Interpretable baseline: median-impute (+ missing flags), scale, one-hot, then
    logistic regression (balanced) or ridge."""
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression, RidgeCV
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    parts = []
    if fs.numeric:
        parts.append(
            ("num", Pipeline([("impute", SimpleImputer(strategy="median", add_indicator=True)), ("scale", StandardScaler())]), fs.numeric)
        )
    if fs.categorical:
        parts.append(
            (
                "cat",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="constant", fill_value="__missing__")),
                        ("onehot", OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=10)),
                    ]
                ),
                fs.categorical,
            )
        )
    pre = ColumnTransformer(parts)
    est = (
        LogisticRegression(max_iter=3000, class_weight="balanced", C=1.0)
        if task == "binary"
        else RidgeCV(alphas=np.logspace(-3, 3, 13))
    )
    return Pipeline([("prep", pre), ("model", est)])


def linear_input(X: pd.DataFrame, fs: FeatureSet) -> pd.DataFrame:
    """sklearn's imputer/one-hot want plain object columns, not pandas categories."""
    Xl = X.copy()
    for c in fs.categorical:
        Xl[c] = Xl[c].astype(object).where(Xl[c].notna(), np.nan)
    return Xl


def make_lgbm(task: str, n_estimators: int = 2000):
    import lightgbm as lgb

    cls = lgb.LGBMClassifier if task == "binary" else lgb.LGBMRegressor
    return cls(n_estimators=n_estimators, **LGBM_PARAMS)


def fit_lgbm_early_stopping(X: pd.DataFrame, y: pd.Series, task: str, seed: int = 42):
    """Hold out 15% of the training rows to pick the number of trees, then refit on all of them."""
    import lightgbm as lgb
    from sklearn.model_selection import train_test_split

    strat = y if task == "binary" and y.value_counts().min() >= 2 else None
    Xa, Xv, ya, yv = train_test_split(X, y, test_size=0.15, random_state=seed, stratify=strat)
    probe = make_lgbm(task)
    probe.fit(Xa, ya, eval_set=[(Xv, yv)], callbacks=[lgb.early_stopping(100, verbose=False)])
    best_iter = max(int(probe.best_iteration_ or 0), 50)
    model = make_lgbm(task, n_estimators=best_iter).fit(X, y)
    return model, best_iter


def predict_score(model, X: pd.DataFrame, task: str) -> np.ndarray:
    return model.predict_proba(X)[:, 1] if task == "binary" else model.predict(X)


# --------------------------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------------------------


def metrics(y_true, score, task: str) -> dict[str, float]:
    from sklearn import metrics as m

    y_true = np.asarray(y_true)
    score = np.asarray(score, dtype=float)
    if task == "binary":
        out = {"base_rate": float(y_true.mean())}
        if len(np.unique(y_true)) == 2:
            out.update(
                roc_auc=m.roc_auc_score(y_true, score),
                pr_auc=m.average_precision_score(y_true, score),
                brier=m.brier_score_loss(y_true, score),
                log_loss=m.log_loss(y_true, np.clip(score, 1e-6, 1 - 1e-6)),
                top_decile_lift=top_k_lift(y_true, score, 0.10),
            )
    else:
        out = dict(
            rmse=float(np.sqrt(m.mean_squared_error(y_true, score))),
            mae=m.mean_absolute_error(y_true, score),
            r2=m.r2_score(y_true, score),
            spearman=float(pd.Series(y_true).rank().corr(pd.Series(score).rank())),
        )
    return {k: round(float(v), 5) for k, v in out.items()}


def top_k_lift(y_true, score, frac: float = 0.10) -> float:
    """How many times more positives are in the top `frac` by score than overall.
    The decision-maker reading: 'focusing on our top 10% finds Nx as many cases as random'."""
    y_true = np.asarray(y_true)
    k = max(1, int(len(y_true) * frac))
    top = np.argsort(-np.asarray(score))[:k]
    base = y_true.mean()
    return float(y_true[top].mean() / base) if base > 0 else float("nan")


# --------------------------------------------------------------------------------------------
# Fit everything on one split
# --------------------------------------------------------------------------------------------


@dataclass
class Fitted:
    name: str
    model: object
    test_metrics: dict[str, float]
    best_iter: int | None = None


def fit_all(X: pd.DataFrame, y: pd.Series, task: str, fs: FeatureSet, train_idx, test_idx) -> dict[str, Fitted]:
    Xtr, Xte = X.iloc[train_idx], X.iloc[test_idx]
    ytr, yte = y.iloc[train_idx], y.iloc[test_idx]
    out: dict[str, Fitted] = {}

    dummy = make_dummy(task).fit(np.zeros((len(Xtr), 1)), ytr)  # predicts the training mean / base rate
    out["dummy"] = Fitted("dummy", dummy, metrics(yte, predict_score(dummy, np.zeros((len(Xte), 1)), task), task))

    lin = make_linear(task, fs).fit(linear_input(Xtr, fs), ytr)
    out["linear"] = Fitted("linear", lin, metrics(yte, predict_score(lin, linear_input(Xte, fs), task), task))

    gbm, best_iter = fit_lgbm_early_stopping(Xtr, ytr, task)
    out["lightgbm"] = Fitted("lightgbm", gbm, metrics(yte, predict_score(gbm, Xte, task), task), best_iter)
    return out


def leaderboard(fitted: dict[str, Fitted]) -> pd.DataFrame:
    return pd.DataFrame([{"model": f.name, **f.test_metrics} for f in fitted.values()])


# --------------------------------------------------------------------------------------------
# Out-of-fold scoring + SHAP contributions for every row
# --------------------------------------------------------------------------------------------


def out_of_fold(
    X: pd.DataFrame, y: pd.Series, task: str, n_estimators: int, n_folds: int = 5, groups: pd.Series | None = None
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Every row is scored by a model that never saw it. Returns (score, fold, contrib) where
    contrib is n_rows x (n_features + 1) TreeSHAP values from LightGBM (last column = bias),
    in log-odds for binary and target units for regression.

    Out-of-fold scores are what make 'higher than expected' honest: an in-sample residual is
    shrunk toward zero because the model already saw that row."""
    score = np.full(len(y), np.nan)
    fold = np.full(len(y), -1)
    contrib = np.zeros((len(y), X.shape[1] + 1))
    for k, (tr, te) in enumerate(_folds(y, task, n_folds, groups)):
        model = make_lgbm(task, n_estimators=n_estimators).fit(X.iloc[tr], y.iloc[tr])
        score[te] = predict_score(model, X.iloc[te], task)
        contrib[te] = model.predict(X.iloc[te], pred_contrib=True)
        fold[te] = k
    return score, fold, contrib


def feature_importance(X: pd.DataFrame, contrib: np.ndarray) -> pd.DataFrame:
    """Mean |SHAP| per feature plus direction: does a higher value push the prediction up or down?"""
    shap_vals = contrib[:, :-1]
    rows = []
    for j, c in enumerate(X.columns):
        x = X[c]
        direction = ""
        if not isinstance(x.dtype, pd.CategoricalDtype):
            mask = x.notna().to_numpy()
            if mask.sum() > 10 and x[mask].nunique() > 1:
                rho = pd.Series(x.to_numpy()[mask]).rank().corr(pd.Series(shap_vals[mask, j]).rank())
                if pd.notna(rho):
                    direction = "higher -> raises prediction" if rho > 0.1 else "higher -> lowers prediction" if rho < -0.1 else "mixed / non-linear"
        else:
            direction = "categorical (see dependence plot)"
        rows.append((c, float(np.abs(shap_vals[:, j]).mean()), direction))
    out = pd.DataFrame(rows, columns=["feature", "mean_abs_shap", "direction"])
    out = out.sort_values("mean_abs_shap", ascending=False).reset_index(drop=True)
    out["rank"] = np.arange(1, len(out) + 1)
    return out


def reason_codes(X: pd.DataFrame, contrib: np.ndarray, top_n: int = 3) -> pd.DataFrame:
    """Per row: the top_n features pushing this prediction UP, as 'feature=value (+0.123)'.
    This is the column a decision-maker reads: why is this county/patient flagged?"""
    shap_vals = contrib[:, :-1]
    names = np.array(X.columns)
    order = np.argsort(-shap_vals, axis=1)[:, :top_n]
    out = {}
    for r in range(top_n):
        texts = []
        for i in range(len(X)):
            j = order[i, r]
            v = shap_vals[i, j]
            if v <= 0:
                texts.append(None)
                continue
            raw = X.iat[i, j]
            shown = "null" if pd.isna(raw) else (f"{raw:.3g}" if isinstance(raw, (float, np.floating)) else str(raw))
            texts.append(f"{names[j]}={shown} (+{v:.3g})")
        out[f"reason_{r + 1}"] = texts
    return pd.DataFrame(out, index=X.index)


def decision_columns(y: pd.Series, score: np.ndarray, task: str) -> pd.DataFrame:
    """Ranking columns a dashboard/app sorts by.
    binary:     risk_score, risk_rank (1 = highest), risk_decile (10 = top)
    regression: predicted, excess (actual - predicted), excess_rank (1 = most above expected)"""
    s = pd.Series(score, index=y.index)
    if task == "binary":
        return pd.DataFrame(
            {
                "risk_score": s.round(5),
                "risk_rank": s.rank(ascending=False, method="first").astype(int),
                "risk_decile": pd.qcut(s.rank(method="first"), min(10, len(s)), labels=False) + 1,
            }
        )
    excess = y - s
    return pd.DataFrame(
        {
            "predicted": s.round(4),
            "excess": excess.round(4),
            "excess_rank": excess.rank(ascending=False, method="first").astype(int),
        }
    )


# --------------------------------------------------------------------------------------------
# Plots (matplotlib; shap only for the nicer beeswarm/dependence plots)
# --------------------------------------------------------------------------------------------


def shap_plots(X: pd.DataFrame, contrib: np.ndarray, out_dir: str, top_k: int = 3, max_rows: int = 5000, max_display: int = 20) -> list[str]:
    """Writes PNGs to out_dir and returns their paths: beeswarm, bar, and dependence for top_k."""
    import os

    import matplotlib.pyplot as plt

    rng = np.random.default_rng(42)
    take = rng.choice(len(X), size=min(max_rows, len(X)), replace=False)
    Xp = X.iloc[take].copy()
    for c in Xp.columns:
        if isinstance(Xp[c].dtype, pd.CategoricalDtype):
            Xp[c] = Xp[c].cat.codes.replace(-1, np.nan).astype(float)
    vals = contrib[take, :-1]
    imp = np.abs(vals).mean(axis=0)
    top = [X.columns[j] for j in np.argsort(-imp)[:top_k]]
    paths = []

    try:
        import shap

        plt.figure()
        shap.summary_plot(vals, Xp, show=False, max_display=max_display)
        paths.append(_save(plt, os.path.join(out_dir, "shap_beeswarm.png")))
        plt.figure()
        shap.summary_plot(vals, Xp, plot_type="bar", show=False, max_display=max_display)
        paths.append(_save(plt, os.path.join(out_dir, "shap_bar.png")))
        for c in top:
            shap.dependence_plot(c, vals, Xp, show=False, interaction_index=None)
            paths.append(_save(plt, os.path.join(out_dir, f"shap_dependence_{c}.png")))
    except ImportError:
        order = np.argsort(imp)[-max_display:]
        fig, ax = plt.subplots(figsize=(7, 0.35 * len(order) + 1))
        ax.barh(np.array(X.columns)[order], imp[order])
        ax.set_xlabel("mean |SHAP value|")
        paths.append(_save(plt, os.path.join(out_dir, "shap_bar.png")))
        for c in top:
            j = list(X.columns).index(c)
            fig, ax = plt.subplots(figsize=(6, 4))
            ax.scatter(Xp[c], vals[:, j], s=6, alpha=0.5)
            ax.set_xlabel(c)
            ax.set_ylabel("SHAP value")
            paths.append(_save(plt, os.path.join(out_dir, f"shap_dependence_{c}.png")))
    return paths


def _save(plt, path: str) -> str:
    plt.tight_layout()
    plt.savefig(path, dpi=130, bbox_inches="tight")
    plt.close("all")
    return path
