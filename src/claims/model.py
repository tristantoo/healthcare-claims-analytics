"""Readmission models (logistic GLM, gradient boosting), calibration, and paired cluster bootstrap."""
import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score


def fit_glm(X: pd.DataFrame, y: pd.Series):
    return sm.GLM(y, sm.add_constant(X, has_constant="add"), family=sm.families.Binomial()).fit()


def predict_glm(fit, X: pd.DataFrame) -> np.ndarray:
    return np.asarray(fit.predict(sm.add_constant(X, has_constant="add")))


def fit_gbm(X: pd.DataFrame, y: pd.Series, seed: int = 0):
    return HistGradientBoostingClassifier(learning_rate=0.05, max_iter=400, max_leaf_nodes=15,
                                          l2_regularization=1.0, early_stopping=True,
                                          validation_fraction=0.2, random_state=seed).fit(X, y)


def ece(y, p, bins: int = 10) -> float:
    """Expected calibration error over equal-frequency bins."""
    y, p = np.asarray(y, float), np.asarray(p, float)
    b = pd.qcut(p, bins, labels=False, duplicates="drop")
    d = pd.DataFrame({"y": y, "p": p, "b": b}).groupby("b").agg(y=("y", "mean"), p=("p", "mean"), n=("y", "size"))
    return float((d["n"] * (d["y"] - d["p"]).abs()).sum() / len(y))


def calibration_table(y, p, bins: int = 10) -> pd.DataFrame:
    b = pd.qcut(np.asarray(p), bins, labels=False, duplicates="drop")
    return (pd.DataFrame({"y": np.asarray(y), "p": np.asarray(p), "bin": b})
            .groupby("bin").agg(mean_pred=("p", "mean"), obs_rate=("y", "mean"), n=("y", "size")).reset_index())


def calibration_slope_intercept(y, p) -> tuple[float, float]:
    """Slope: logit(y) ~ logit(p). Intercept: calibration-in-the-large with logit(p) as offset."""
    y = np.asarray(y, float)
    lp = np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6)))
    slope = sm.GLM(y, sm.add_constant(lp), family=sm.families.Binomial()).fit().params
    slope = np.asarray(slope)[1]
    intercept = sm.GLM(y, np.ones_like(lp), family=sm.families.Binomial(), offset=lp).fit().params
    intercept = np.asarray(intercept)[0]
    return float(intercept), float(slope)


def metrics(y, p) -> dict:
    a, s = calibration_slope_intercept(y, p)
    return {"auc": roc_auc_score(y, p), "brier": brier_score_loss(y, p), "log_loss": log_loss(y, p),
            "ece": ece(y, p), "cal_intercept": a, "cal_slope": s, "mean_pred": float(np.mean(p)),
            "obs_rate": float(np.mean(y))}


def binned_residuals(y, p, bins: int = 20) -> pd.DataFrame:
    """Gelman-Hill binned residuals; about 95% of bins should fall inside +/- 2 SE."""
    t = calibration_table(y, p, bins)
    t["resid"] = t["obs_rate"] - t["mean_pred"]
    t["two_se"] = 2 * np.sqrt(t["mean_pred"] * (1 - t["mean_pred"]) / t["n"])
    return t


def paired_cluster_bootstrap(y, p_a, p_b, clusters, B: int = 500, seed: int = 0) -> dict:
    """Delta (b minus a) in AUC and Brier, resampling clusters (beneficiaries) with replacement."""
    rng = np.random.default_rng(seed)
    y, p_a, p_b = map(np.asarray, (y, p_a, p_b))
    codes, uniq = pd.factorize(np.asarray(clusters))
    members = pd.Series(np.arange(len(y))).groupby(codes).apply(np.asarray).to_numpy()
    d_auc, d_brier = [], []
    for _ in range(B):
        idx = np.concatenate(members[rng.integers(0, len(uniq), len(uniq))])
        yy = y[idx]
        if yy.min() == yy.max():
            continue
        d_auc.append(roc_auc_score(yy, p_b[idx]) - roc_auc_score(yy, p_a[idx]))
        d_brier.append(brier_score_loss(yy, p_b[idx]) - brier_score_loss(yy, p_a[idx]))
    out = {}
    for name, d in (("auc", np.array(d_auc)), ("brier", np.array(d_brier))):
        out[f"delta_{name}"] = float(np.mean(d))
        out[f"delta_{name}_ci95"] = [float(np.quantile(d, 0.025)), float(np.quantile(d, 0.975))]
    out["n_boot"] = len(d_auc)
    return out
