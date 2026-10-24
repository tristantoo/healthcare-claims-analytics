# Reproducibility checklist

Tick each before tagging a release or linking the repo on a resume.

- [ ] Fresh clone, then `uv sync` succeeds (Python and package versions pinned in `uv.lock`).
- [ ] `uv run pytest` passes (runs the synthetic sample end to end; no CMS files needed).
- [ ] `uv run python scripts/download_synpuf.py` downloads and unzips Sample 1 into `data/raw/` (not committed).
- [ ] `uv run python -m claims.run` reproduces `outputs/metrics.json` exactly (seeds fixed: GBM `random_state=0`, bootstrap `seed=0`).
- [ ] `uv run python scripts/load_sqlserver.py` exits 0: SQL Server mart and pandas cohort agree on stays, index stays, readmits, and prior-stay sums for both splits.
- [ ] Power BI card totals equal `SELECT COUNT(*), SUM(CAST(readmit_30 AS INT)) FROM mart.index_stay WHERE split='test'`.
- [ ] Every number in the README and memo is copied from `outputs/`, not typed by hand.
- [ ] README states the CMS caveat (synthetic data, limited inferential value) and the "PCR-style, adapted" label.
- [ ] Eval protocol, significance test, and falsification criteria are stated (docs/spec.md section 5).
- [ ] No credentials or connection strings are committed (`CLAIMS_SQL_CONN` is read from the environment).
