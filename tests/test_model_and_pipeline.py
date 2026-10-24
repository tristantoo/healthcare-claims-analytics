import json

import numpy as np

from claims import model, run, sample


def test_ece_near_zero_when_calibrated_and_bootstrap_zero_for_identical_models():
    rng = np.random.default_rng(0)
    p = rng.uniform(0.01, 0.3, 20000)
    y = (rng.random(20000) < p).astype(int)
    assert model.ece(y, p) < 0.01
    assert model.ece(y, np.clip(p * 2, 0, 1)) > 0.05
    a, s = model.calibration_slope_intercept(y, p)
    assert abs(a) < 0.1 and abs(s - 1) < 0.15
    bs = model.paired_cluster_bootstrap(y, p, p, np.arange(len(y)) // 2, B=20)
    assert bs["delta_auc"] == 0 and bs["delta_brier"] == 0


def test_pipeline_end_to_end_on_synthetic_sample(tmp_path):
    sample.main(str(tmp_path / "data"))
    rep = run.main(["--data", str(tmp_path / "data"), "--out", str(tmp_path / "out"), "--boot", "20"])
    assert rep["n"]["test_index"] > 200
    assert rep["test_metrics"]["glm"]["auc"] > 0.55  # signal planted in claims.sample
    saved = json.loads((tmp_path / "out" / "metrics.json").read_text())
    assert saved["protocol"]["split"].startswith("forward-chaining")
    for f in ("provider_oe.csv", "monthly_readmission.csv", "index_stays_scored.csv", "calibration.png", "attrition.csv"):
        assert (tmp_path / "out" / f).exists()
