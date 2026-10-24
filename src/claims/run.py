"""End-to-end run: cohort -> models -> calibration -> PCR-style measure -> outputs/ for Power BI.

uv run python -m claims.run                         # real DE-SynPUF Sample 1 in data/raw
uv run python -m claims.run --data data/sample      # synthetic sample, runs anywhere
Eval protocol: forward-chaining. Train on 2009 discharges, test on 2010 discharges (to Dec 1).
"""
import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from claims import cohort, measure, model  # noqa: E402

TRAIN = ("2009-01-01", "2009-12-31")
TEST = ("2010-01-01", "2010-12-01")
BASELINE = ["age", "prior_stays_365"]


def find(data: Path, pattern: str) -> Path:
    hits = sorted(data.glob(pattern))
    if not hits:
        raise SystemExit(f"missing {pattern} in {data}; run scripts/download_synpuf.py or claims.sample")
    return hits[0]


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/raw")
    ap.add_argument("--out", default="outputs")
    ap.add_argument("--boot", type=int, default=500)
    a = ap.parse_args(argv)
    data, out = Path(a.data), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    ip = cohort.load_inpatient(find(data, "*Inpatient_Claims*.csv"))
    bene = cohort.load_beneficiary({y: find(data, f"*{y}_Beneficiary_Summary*.csv") for y in (2008, 2009, 2010)})
    stays = cohort.build_stays(ip)
    train, att_tr = cohort.index_stays(stays, bene, *TRAIN)
    test, att_te = cohort.index_stays(stays, bene, *TEST)

    X, y = train[cohort.FEATURES], train["readmit_30"]
    glm = model.fit_glm(X, y)
    base = model.fit_glm(train[BASELINE], y)
    gbm = model.fit_gbm(X, y)
    test["p_glm"] = model.predict_glm(glm, test[cohort.FEATURES])
    test["p_base"] = model.predict_glm(base, test[BASELINE])
    test["p_gbm"] = gbm.predict_proba(test[cohort.FEATURES])[:, 1]

    yt = test["readmit_30"]
    report = {
        "protocol": {"train": TRAIN, "test": TEST, "split": "forward-chaining by discharge date"},
        "n": {"claims_seg1": len(ip), "stays": len(stays), "train_index": len(train), "test_index": len(test),
              "test_beneficiaries": int(test["DESYNPUF_ID"].nunique())},
        "test_metrics": {k: model.metrics(yt, test[f"p_{k}"]) for k in ("base", "glm", "gbm")},
        "bootstrap_gbm_minus_glm": model.paired_cluster_bootstrap(yt, test["p_glm"], test["p_gbm"], test["DESYNPUF_ID"], a.boot),
        "bootstrap_glm_minus_base": model.paired_cluster_bootstrap(yt, test["p_base"], test["p_glm"], test["DESYNPUF_ID"], a.boot),
        "died_within_30d_share_test": float(test["died_30"].mean()),
        # share of all test readmissions among the top 10% of stays by predicted risk (10% = random)
        "top_decile_capture": {k: float(yt[test[f"p_{k}"] >= test[f"p_{k}"].quantile(0.9)].sum() / yt.sum())
                               for k in ("base", "glm", "gbm")},
    }
    (out / "metrics.json").write_text(json.dumps(report, indent=2, default=str))

    coef = glm.summary2().tables[1]
    coef.to_csv(out / "glm_coefficients.csv")
    pd.concat([att_tr.assign(split="train"), att_te.assign(split="test")]).to_csv(out / "attrition.csv", index=False)
    test.to_csv(out / "index_stays_scored.csv", index=False)
    measure.oe_table(test, "prvdr_num").to_csv(out / "provider_oe.csv", index=False)
    measure.monthly_rate(test).to_csv(out / "monthly_readmission.csv", index=False)
    br = model.binned_residuals(yt, test["p_glm"])
    br.to_csv(out / "glm_binned_residuals.csv", index=False)

    fig, ax = plt.subplots(1, 2, figsize=(10, 4.2))
    for k in ("glm", "gbm"):
        c = model.calibration_table(yt, test[f"p_{k}"])
        c.to_csv(out / f"calibration_{k}.csv", index=False)
        ax[0].plot(c["mean_pred"], c["obs_rate"], "o-", label=k.upper())
    lim = max(test[["p_glm", "p_gbm"]].max().max(), yt.mean() * 2)
    ax[0].plot([0, lim], [0, lim], "k--", lw=1)
    ax[0].set(xlabel="mean predicted", ylabel="observed rate", title="Reliability, 2010 test")
    ax[0].legend()
    ax[1].errorbar(br["mean_pred"], br["resid"], yerr=br["two_se"], fmt="o", capsize=2)
    ax[1].axhline(0, color="k", lw=1)
    ax[1].set(xlabel="mean predicted", ylabel="observed minus predicted", title="GLM binned residuals")
    fig.tight_layout()
    fig.savefig(out / "calibration.png", dpi=150)
    print(json.dumps({k: report[k] for k in ("n", "test_metrics")}, indent=2, default=str))
    return report


if __name__ == "__main__":
    main()
