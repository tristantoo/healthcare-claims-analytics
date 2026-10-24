"""Inpatient stays, PCR-style index stays, 30-day readmission flag, and pre-index features.

Rules (mirrored in sql/02_build_mart.sql; tests/test_cohort.py pins the edge cases):
- Keep claim SEGMENT 1 (segment 2 rows are continuation lines with no dates).
- Direct transfers: a claim admitted on or before the running max discharge + 1 day joins
  the same stay (HEDIS PCR "one calendar day or less" rule). The stay is attributed to the
  discharging (last) provider.
- Index stay: discharge in [start, end]; end leaves 30 days of follow-up inside the data.
- Features come only from the PRIOR calendar year's beneficiary file and from claims before
  the admission, so nothing after the index admission can leak in.
"""
import numpy as np
import pandas as pd

DX_COLS = [f"ICD9_DGNS_CD_{i}" for i in range(1, 11)]
CHRONIC = ["SP_ALZHDMTA", "SP_CHF", "SP_CHRNKIDN", "SP_CNCR", "SP_COPD", "SP_DEPRESSN",
           "SP_DIABETES", "SP_ISCHMCHT", "SP_OSTEOPRS", "SP_RA_OA", "SP_STRKETIA"]
IP_COLS = ["DESYNPUF_ID", "CLM_ID", "SEGMENT", "CLM_ADMSN_DT", "NCH_BENE_DSCHRG_DT",
           "PRVDR_NUM", "CLM_PMT_AMT", "CLM_DRG_CD", *DX_COLS]
BENE_COLS = ["DESYNPUF_ID", "BENE_BIRTH_DT", "BENE_DEATH_DT", "BENE_SEX_IDENT_CD", "BENE_RACE_CD",
             "BENE_ESRD_IND", "BENE_HI_CVRAGE_TOT_MONS", "BENE_HMO_CVRAGE_TOT_MONS", "MEDREIMB_IP", *CHRONIC]
FEATURES = ["age", "female", "race_black", "race_other", "esrd", *[c.lower() for c in CHRONIC],
            "los_days", "n_dx", "prior_stays_365", "log_prior_ip_paid"]


def _dt(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, format="%Y%m%d", errors="coerce")


def load_inpatient(path) -> pd.DataFrame:
    ip = pd.read_csv(path, dtype=str, usecols=IP_COLS)
    ip = ip[ip["SEGMENT"] == "1"].copy()
    ip["admit_dt"] = _dt(ip["CLM_ADMSN_DT"])
    ip["discharge_dt"] = _dt(ip["NCH_BENE_DSCHRG_DT"])
    ip["paid"] = pd.to_numeric(ip["CLM_PMT_AMT"], errors="coerce").fillna(0.0)
    ip["n_dx"] = ip[DX_COLS].notna().sum(axis=1)
    return ip.dropna(subset=["admit_dt", "discharge_dt"])


def load_beneficiary(paths_by_year: dict) -> pd.DataFrame:
    frames = []
    for year, path in paths_by_year.items():
        b = pd.read_csv(path, dtype=str, usecols=BENE_COLS)
        b["file_year"] = int(year)
        frames.append(b)
    return pd.concat(frames, ignore_index=True)


def build_stays(ip: pd.DataFrame) -> pd.DataFrame:
    ip = ip.assign(_clm=pd.to_numeric(ip["CLM_ID"])).sort_values(["DESYNPUF_ID", "admit_dt", "discharge_dt", "_clm"]).reset_index(drop=True)
    prev_max = ip.groupby("DESYNPUF_ID")["discharge_dt"].cummax().groupby(ip["DESYNPUF_ID"]).shift()
    new_stay = prev_max.isna() | (ip["admit_dt"] > prev_max + pd.Timedelta(days=1))
    ip["stay_seq"] = new_stay.astype(int).groupby(ip["DESYNPUF_ID"]).cumsum()
    g = ip.groupby(["DESYNPUF_ID", "stay_seq"], sort=False)
    stays = g.agg(admit_dt=("admit_dt", "min"), discharge_dt=("discharge_dt", "max"),
                  prvdr_num=("PRVDR_NUM", "last"), drg=("CLM_DRG_CD", "last"),
                  paid=("paid", "sum"), n_dx=("n_dx", "max"), n_claims=("CLM_ID", "size")).reset_index()
    stays["los_days"] = (stays["discharge_dt"] - stays["admit_dt"]).dt.days
    nxt = stays.groupby("DESYNPUF_ID")["admit_dt"].shift(-1)
    stays["days_to_next_admit"] = (nxt - stays["discharge_dt"]).dt.days
    # prior stays discharged in the 365 days before this admission (self-join; few stays per person)
    pairs = stays[["DESYNPUF_ID", "stay_seq", "admit_dt"]].merge(
        stays[["DESYNPUF_ID", "discharge_dt"]], on="DESYNPUF_ID")
    hit = (pairs["discharge_dt"] < pairs["admit_dt"]) & (pairs["discharge_dt"] >= pairs["admit_dt"] - pd.Timedelta(days=365))
    counts = pairs[hit].groupby(["DESYNPUF_ID", "stay_seq"]).size().rename("prior_stays_365")
    stays = stays.merge(counts, on=["DESYNPUF_ID", "stay_seq"], how="left")
    stays["prior_stays_365"] = stays["prior_stays_365"].fillna(0).astype(int)
    return stays


def index_stays(stays: pd.DataFrame, bene: pd.DataFrame, start: str, end: str):
    """Return (cohort, attrition). cohort has readmit_30 and FEATURES."""
    steps = []
    df = stays[(stays["discharge_dt"] >= start) & (stays["discharge_dt"] <= end)].copy()
    steps.append(("discharge in window", len(df)))

    df["prior_year"] = df["discharge_dt"].dt.year - 1
    prior = bene.rename(columns={"file_year": "prior_year"})
    df = df.merge(prior, on=["DESYNPUF_ID", "prior_year"], how="inner")
    steps.append(("has prior-year beneficiary record", len(df)))

    full = (pd.to_numeric(df["BENE_HI_CVRAGE_TOT_MONS"]) == 12) & (pd.to_numeric(df["BENE_HMO_CVRAGE_TOT_MONS"]) == 0)
    df = df[full].copy()
    steps.append(("12 months Part A, no HMO, prior year", len(df)))

    # death dates in SynPUF are month-level; the latest file carries the death date
    death = bene.dropna(subset=["BENE_DEATH_DT"]).groupby("DESYNPUF_ID")["BENE_DEATH_DT"].max()
    df["death_dt"] = _dt(df["DESYNPUF_ID"].map(death))
    df = df[~(df["death_dt"] <= df["discharge_dt"])].copy()
    steps.append(("alive at discharge", len(df)))

    df["readmit_30"] = (df["days_to_next_admit"] <= 30).astype(int)
    df["died_30"] = ((df["death_dt"] - df["discharge_dt"]).dt.days <= 30).astype(int)
    df["age"] = (df["discharge_dt"] - _dt(df["BENE_BIRTH_DT"])).dt.days / 365.25
    df["female"] = (df["BENE_SEX_IDENT_CD"] == "2").astype(int)
    df["race_black"] = (df["BENE_RACE_CD"] == "2").astype(int)
    df["race_other"] = df["BENE_RACE_CD"].isin(["3", "5"]).astype(int)
    df["esrd"] = (df["BENE_ESRD_IND"] == "Y").astype(int)
    for c in CHRONIC:
        df[c.lower()] = (df[c] == "1").astype(int)
    df["log_prior_ip_paid"] = np.log1p(pd.to_numeric(df["MEDREIMB_IP"]).clip(lower=0))
    keep = ["DESYNPUF_ID", "stay_seq", "admit_dt", "discharge_dt", "prvdr_num", "drg", "paid",
            "readmit_30", "died_30", *FEATURES]
    return df[keep].reset_index(drop=True), pd.DataFrame(steps, columns=["step", "n_index_stays"])
