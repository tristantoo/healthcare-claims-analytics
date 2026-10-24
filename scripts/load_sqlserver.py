"""Load DE-SynPUF CSVs into SQL Server, build the mart, write scores back, and reconcile against pandas.

uv run python scripts/load_sqlserver.py                      # LocalDB, database "claims", data/raw
uv run python scripts/load_sqlserver.py --data data/sample --db claims_sample
Set CLAIMS_SQL_CONN to use another server (any ODBC connection string, without DATABASE=).
Exit code 1 if SQL and pandas disagree on any reconciled count.
"""
import argparse
import os
import re
import subprocess
from pathlib import Path

import pandas as pd
import pyodbc

from claims import cohort
from claims.run import TEST, TRAIN, find

ROOT = Path(__file__).resolve().parents[1]


def connect(db: str | None = None) -> pyodbc.Connection:
    conn = os.environ.get("CLAIMS_SQL_CONN")
    if not conn:
        # The legacy "SQL Server" ODBC driver cannot resolve (localdb)\..., so use the instance pipe.
        subprocess.run(["sqllocaldb", "start", "MSSQLLocalDB"], capture_output=True)
        info = subprocess.run(["sqllocaldb", "info", "MSSQLLocalDB"], capture_output=True, text=True).stdout
        pipe = re.search(r"(np:\S+)", info).group(1)
        conn = f"DRIVER={{SQL Server}};SERVER={pipe};Trusted_Connection=yes;"
    return pyodbc.connect(conn + (f"DATABASE={db};" if db else ""), autocommit=True)


def run_sql(cx, path: Path) -> None:
    for batch in re.split(r"^\s*GO\s*$", path.read_text(), flags=re.M | re.I):
        if batch.strip():
            cx.execute(batch)


def insert(cx, table: str, df: pd.DataFrame) -> None:
    df = df.astype(object).where(df.notna(), None)
    cur = cx.cursor()
    cur.fast_executemany = True
    cols = ",".join(df.columns)
    cur.executemany(f"INSERT {table} ({cols}) VALUES ({','.join('?' * len(df.columns))})",
                    list(df.itertuples(index=False, name=None)))


def dates(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, format="%Y%m%d").dt.date


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/raw")
    ap.add_argument("--db", default="claims")
    ap.add_argument("--scores", default="outputs/index_stays_scored.csv")
    a = ap.parse_args()
    data = Path(a.data)

    master = connect()
    master.execute(f"IF DB_ID('{a.db}') IS NULL CREATE DATABASE [{a.db}]")
    cx = connect(a.db)
    run_sql(cx, ROOT / "sql/01_schema.sql")

    ip = pd.read_csv(find(data, "*Inpatient_Claims*.csv"), dtype=str, usecols=cohort.IP_COLS)
    ip = pd.DataFrame({"desynpuf_id": ip["DESYNPUF_ID"], "clm_id": ip["CLM_ID"].astype("int64"),
                       "segment": ip["SEGMENT"].astype(int), "admit_dt": dates(ip["CLM_ADMSN_DT"]),
                       "discharge_dt": dates(ip["NCH_BENE_DSCHRG_DT"]), "prvdr_num": ip["PRVDR_NUM"],
                       "clm_pmt_amt": pd.to_numeric(ip["CLM_PMT_AMT"]), "clm_drg_cd": ip["CLM_DRG_CD"],
                       **{c.lower(): ip[c] for c in cohort.DX_COLS}})
    insert(cx, "raw.inpatient_claim", ip)

    for year in (2008, 2009, 2010):
        b = pd.read_csv(find(data, f"*{year}_Beneficiary_Summary*.csv"), dtype=str, usecols=cohort.BENE_COLS)
        insert(cx, "raw.beneficiary_year", pd.DataFrame({
            "desynpuf_id": b["DESYNPUF_ID"], "file_year": year, "birth_dt": dates(b["BENE_BIRTH_DT"]),
            "death_dt": pd.to_datetime(b["BENE_DEATH_DT"], format="%Y%m%d").dt.date,
            "sex_cd": b["BENE_SEX_IDENT_CD"], "race_cd": b["BENE_RACE_CD"], "esrd_ind": b["BENE_ESRD_IND"],
            "hi_cov_mos": b["BENE_HI_CVRAGE_TOT_MONS"].astype(int), "hmo_cov_mos": b["BENE_HMO_CVRAGE_TOT_MONS"].astype(int),
            "medreimb_ip": pd.to_numeric(b["MEDREIMB_IP"]), **{c.lower(): b[c].astype(int) for c in cohort.CHRONIC}}))
        print("loaded beneficiary", year)

    run_sql(cx, ROOT / "sql/02_build_mart.sql")
    scores = Path(a.scores)
    if scores.exists():
        s = pd.read_csv(scores, usecols=["DESYNPUF_ID", "stay_seq", "p_glm", "p_gbm"])
        insert(cx, "mart.index_stay_score", s.rename(columns={"DESYNPUF_ID": "desynpuf_id"}))
    run_sql(cx, ROOT / "sql/03_quality_measure.sql")

    # Reconcile SQL mart against the pandas cohort (same rules, independent implementation).
    stays = cohort.build_stays(cohort.load_inpatient(find(data, "*Inpatient_Claims*.csv")))
    bene = cohort.load_beneficiary({y: find(data, f"*{y}_Beneficiary_Summary*.csv") for y in (2008, 2009, 2010)})
    checks = {"ip_stay rows": (len(stays), "SELECT COUNT(*) FROM mart.ip_stay")}
    for split, (start, end) in (("train", TRAIN), ("test", TEST)):
        c, _ = cohort.index_stays(stays, bene, start, end)
        checks[f"{split} index stays"] = (len(c), f"SELECT COUNT(*) FROM mart.index_stay WHERE split='{split}'")
        checks[f"{split} readmits"] = (int(c["readmit_30"].sum()),
                                       f"SELECT SUM(CAST(readmit_30 AS INT)) FROM mart.index_stay WHERE split='{split}'")
        checks[f"{split} prior_stays_365 sum"] = (int(c["prior_stays_365"].sum()),
                                                  f"SELECT SUM(prior_stays_365) FROM mart.index_stay WHERE split='{split}'")
    bad = 0
    for name, (py, q) in checks.items():
        sql = cx.execute(q).fetchone()[0]
        ok = py == sql
        bad += not ok
        print(f"{'OK  ' if ok else 'DIFF'} {name}: pandas={py} sql={sql}")
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
