"""PCR-style measure: observed 30-day readmission rate and risk-adjusted observed/expected (O/E)."""
import numpy as np
import pandas as pd
from scipy.stats import chi2


def _poisson_ci(o: np.ndarray, alpha: float = 0.05):
    lo = np.where(o > 0, chi2.ppf(alpha / 2, 2 * o) / 2, 0.0)
    hi = chi2.ppf(1 - alpha / 2, 2 * (o + 1)) / 2
    return lo, hi


def oe_table(df: pd.DataFrame, by: str, expected_col: str = "p_glm", min_n: int = 25) -> pd.DataFrame:
    """O/E by group with exact Poisson CI on O (expected treated as fixed). Small groups dropped."""
    t = (df.groupby(by).agg(index_stays=("readmit_30", "size"), observed=("readmit_30", "sum"),
                            expected=(expected_col, "sum")).reset_index())
    t = t[t["index_stays"] >= min_n].copy()
    lo, hi = _poisson_ci(t["observed"].to_numpy())
    t["oe_ratio"] = t["observed"] / t["expected"]
    t["oe_lo95"], t["oe_hi95"] = lo / t["expected"], hi / t["expected"]
    t["flag"] = np.select([t["oe_lo95"] > 1, t["oe_hi95"] < 1], ["worse than expected", "better than expected"], "as expected")
    return t.sort_values("oe_ratio", ascending=False)


def monthly_rate(df: pd.DataFrame) -> pd.DataFrame:
    m = df.assign(month=df["discharge_dt"].dt.to_period("M").astype(str))
    return m.groupby("month").agg(index_stays=("readmit_30", "size"), readmits=("readmit_30", "sum"),
                                  expected=("p_glm", "sum")).reset_index().assign(
        rate=lambda t: t["readmits"] / t["index_stays"])
