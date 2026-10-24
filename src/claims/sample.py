"""Write a small synthetic sample in the DE-SynPUF column layout so the pipeline runs without CMS files.

uv run python -m claims.sample            # writes data/sample/*.csv
Readmission risk is driven by CHF and prior stays, so a working model should beat AUC 0.5.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from claims.cohort import CHRONIC, DX_COLS


def make(n_bene: int = 4000, seed: int = 7) -> tuple[pd.DataFrame, dict]:
    rng = np.random.default_rng(seed)
    ids = [f"{i:016X}" for i in rng.choice(16**10, n_bene, replace=False)]
    birth = pd.to_datetime("1920-01-01") + pd.to_timedelta(rng.integers(0, 365 * 50, n_bene), unit="D")
    chf = rng.random(n_bene) < 0.35
    bene_years = {}
    for year in (2008, 2009, 2010):
        b = pd.DataFrame({"DESYNPUF_ID": ids, "BENE_BIRTH_DT": birth.strftime("%Y%m%d"), "BENE_DEATH_DT": np.nan,
                          "BENE_SEX_IDENT_CD": rng.choice(["1", "2"], n_bene),
                          "BENE_RACE_CD": rng.choice(["1", "2", "3", "5"], n_bene, p=[.8, .12, .05, .03]),
                          "BENE_ESRD_IND": rng.choice(["0", "Y"], n_bene, p=[.9, .1]),
                          "BENE_HI_CVRAGE_TOT_MONS": "12", "BENE_HMO_CVRAGE_TOT_MONS": "0",
                          "MEDREIMB_IP": rng.choice([0, 4000, 12000], n_bene).astype(float)})
        for c in CHRONIC:
            b[c] = np.where(chf, "1", "2") if c == "SP_CHF" else rng.choice(["1", "2"], n_bene, p=[.3, .7])
        bene_years[year] = b

    rows, clm = [], 10**14
    for i, bid in enumerate(ids):
        t = pd.Timestamp("2008-01-01") + pd.Timedelta(days=int(rng.integers(0, 1050)))
        prior = 0
        while t < pd.Timestamp("2010-12-20"):
            if rng.random() > (0.85 if chf[i] else 0.7):
                break
            los = int(rng.integers(1, 9))
            dx = rng.choice(["4280", "486", "41401", "5990", "25000"], int(rng.integers(1, 10)))
            rows.append({"DESYNPUF_ID": bid, "CLM_ID": str(clm), "SEGMENT": "1",
                         "CLM_ADMSN_DT": t.strftime("%Y%m%d"),
                         "NCH_BENE_DSCHRG_DT": (t + pd.Timedelta(days=los)).strftime("%Y%m%d"),
                         "PRVDR_NUM": f"{rng.integers(1, 40):02d}00AB", "CLM_PMT_AMT": f"{rng.integers(2, 30) * 1000}.00",
                         "CLM_DRG_CD": str(rng.integers(100, 999)),
                         **{c: (dx[k] if k < len(dx) else np.nan) for k, c in enumerate(DX_COLS)}})
            clm += 1
            prior += 1
            p_readmit = min(0.9, 0.08 + 0.15 * chf[i] + 0.05 * prior)
            gap = int(rng.integers(2, 31)) if rng.random() < p_readmit else int(rng.integers(31, 400))
            t = t + pd.Timedelta(days=los + gap)
    return pd.DataFrame(rows), bene_years


def main(out: str = "data/sample") -> None:
    o = Path(out)
    o.mkdir(parents=True, exist_ok=True)
    ip, bene = make()
    ip.to_csv(o / "DE1_0_2008_to_2010_Inpatient_Claims_Sample_SYN.csv", index=False)
    for year, b in bene.items():
        b.to_csv(o / f"DE1_0_{year}_Beneficiary_Summary_File_Sample_SYN.csv", index=False)
    print(f"wrote {len(ip)} claims, {len(bene[2008])} beneficiaries to {o}")


if __name__ == "__main__":
    main(*sys.argv[1:])
