# Project spec: 30-day readmissions on CMS DE-SynPUF

## 1. Business question

A Medicare plan's care management team can call a limited number of patients after discharge. Two questions:

1. **Who should get the call?** Rank each discharge by its probability of an unplanned return to the hospital within 30 days. Because staffing is set from the expected count, the probabilities must be calibrated, not just well ranked.
2. **Which hospitals readmit more than their case mix predicts?** Compare observed readmissions to the model's expected count (O/E), in the style of the HEDIS Plan All-Cause Readmissions (PCR) measure.

Decision supported: where to send transitional-care outreach, and which hospital partners to review.

## 2. Data

CMS 2008 to 2010 Data Entrepreneurs' Synthetic Public Use File (DE-SynPUF), Sample 1 of 20. Access checked 2026-10-16: the files download freely, with no account or data use agreement ([CMS DE-SynPUF page](https://www.cms.gov/data-research/statistics-trends-and-reports/medicare-claims-synthetic-public-use-files/cms-2008-2010-data-entrepreneurs-synthetic-public-use-file-de-synpuf)).

| File | Rows (Sample 1) | Used for |
|---|---|---|
| Inpatient Claims 2008 to 2010 | 66,773 claim segments | stays, outcome, provider, LOS |
| Beneficiary Summary 2008, 2009, 2010 | 116,352 / 114,538 / 112,754 | demographics, chronic flags, coverage, death |

CMS caveat, quoted in every output: the synthetic process gives the file "very limited inferential research value." Results here demonstrate method, not facts about Medicare. Known file quirks:
- The 2010 Sample 1 beneficiary link points to a file named `..._sample_20.zip`, but it contains the Sample 1 CSV. `scripts/download_synpuf.py` handles this.
- Death dates are month-level (always the 1st).
- 2010 has fewer claims, from attrition and disclosure treatment (CMS). Expect drift in the 2010 test year.

## 3. Data model (SQL Server)

```
raw.beneficiary_year (desynpuf_id, file_year)  1 ─── *  raw.inpatient_claim (clm_id, segment)
            │                                                   │  02_build_mart.sql: gaps and islands
            │ prior-year join                                   ▼
            └──────────────────────────────────────►  mart.ip_stay (desynpuf_id, stay_seq)
                                                                │  window + exclusions
                                                                ▼
mart.index_stay_score (Python GLM/GBM) ───────────►  mart.index_stay  ──► mart.v_provider_oe
                                                                     └──► mart.v_monthly_readmission
mart.attrition (split, step_no): row counts after each exclusion
```

DDL: `sql/01_schema.sql`. Constraints enforce types and ranges (date order, coverage months 0 to 12, flag domains, probabilities in [0, 1]).

## 4. Quality measure: PCR-style 30-day all-cause readmission (adapted)

| Element | Rule | HEDIS PCR | Deviation |
|---|---|---|---|
| Stay | Claims merged when the next admission is no more than 1 day after the running max discharge (direct transfer) | same rule | none |
| Denominator | Stays discharged in the window, alive at discharge, 12 months Part A and 0 HMO months in the prior year | continuous enrollment 365 days before and 30 days after | uses calendar-year months, not daily enrollment |
| Numerator | Any acute admission 2 to 30 days after discharge | same window | **no planned-readmission exclusion** (needs the CMS planned readmission algorithm; TODO) |
| Attribution | Discharging hospital | plan level | hospital level, for the O/E view |
| Risk adjustment | Logistic GLM, observed/expected | HEDIS published risk weights | our own model, not certified weights |
| Outliers | none | members with 4+ stays reported separately | TODO |

Label everywhere: **"PCR-style, adapted; not a certified HEDIS rate."**

Second measure (planned, week 6): HbA1c testing for members with diabetes (`SP_DIABETES = 1`), numerator any carrier claim line with HCPCS 83036 or 83037. Needs the Carrier Claims files (two zips per sample). HEDIS retired testing-only diabetes measures, so this one is also labeled adapted.

## 5. Readmission model

**Unit:** index stay. **Outcome:** `readmit_30`.
**Features (all known at discharge, from the prior calendar year or earlier claims):** age, sex, race (3 groups), ESRD, 11 chronic condition flags (prior-year file), length of stay, number of coded diagnoses, stays in the prior 365 days, log prior-year inpatient reimbursement.

**Eval protocol:** forward-chaining. Train on 2009 discharges, test on 2010 discharges through Dec 1 (so every test stay has 30 days of follow-up in the data). No random split.

**Models:** (a) baseline GLM on age and prior stays, (b) full logistic GLM (statsmodels), (c) histogram gradient boosting (scikit-learn), same features.

**Metrics on the test year:** ROC AUC, Brier, log loss, ECE (10 equal-frequency bins), calibration intercept (logit offset) and slope, reliability diagram, GLM binned residuals (Gelman and Hill).

**Significance:** paired cluster bootstrap, 500 draws, resampling beneficiaries (people contribute several stays). We report the 95% CI of delta AUC and delta Brier.

**What would falsify each claim:**
- "GBM beats GLM": delta AUC CI includes 0 → no claim.
- "The model adds value over the baseline": delta AUC CI for GLM minus baseline includes 0 → the model is not worth deploying.
- "Probabilities are usable for staffing": calibration intercept CI excludes 0, or ECE comparable to the base rate → recalibrate before use.

**Leakage audit:**
- Chronic flags and reimbursement come from the prior-year file; the current-year file can carry conditions coded after discharge. Pinned by `tests/test_cohort.py::test_features_use_prior_year_file_only`.
- `prior_stays_365` counts stays discharged before the index admission only.
- The outcome window never crosses the end of the data (test window ends Dec 1, 2010).
- Death within 30 days is a competing risk. It is kept in the denominator (as in PCR) and its share is reported (`died_within_30d_share_test`).

## 6. Power BI dashboard plan

Source: SQL Server views (`mart.v_provider_oe`, `mart.v_monthly_readmission`, `mart.index_stay`) or the CSVs in `outputs/`.

| Page | Visuals | Question it answers |
|---|---|---|
| 1. Overview | KPI cards: index stays, readmit rate, O/E; line: observed vs expected by month | Is the readmission rate moving? |
| 2. Hospitals | Funnel plot (O/E vs expected count, 95% limits); table sorted by O/E with flag | Which partners to review? |
| 3. Targeting | Risk decile bar chart: share of all readmissions captured by each decile; slicer for decile cutoff | How many readmissions does a top-10% call list reach? |
| 4. Model check | Reliability diagram (from `calibration_glm.csv`), metric table | Can staffing trust the expected counts? |
| 5. Data quality | Attrition waterfall from `mart.attrition` | What was excluded and why? |

DAX measures:

```DAX
Index Stays = COUNTROWS ( index_stay )
Readmits    = SUM ( index_stay[readmit_30] )
Readmit Rate = DIVIDE ( [Readmits], [Index Stays] )
Expected    = SUM ( index_stay_score[p_glm] )
O/E Ratio   = DIVIDE ( [Readmits], [Expected] )
Top Decile Capture =
VAR cutoff = PERCENTILEX.INC ( index_stay_score, index_stay_score[p_glm], 0.9 )
RETURN DIVIDE (
    CALCULATE ( [Readmits], FILTER ( index_stay_score, index_stay_score[p_glm] >= cutoff ) ),
    [Readmits] )
```

Reconciliation rule (from the EvidenceOps habit): card totals must match `SELECT COUNT(*)` and `SUM(readmit_30)` from `mart.index_stay`. Screenshot both for the README.

## 7. Deliverables

1. Public repo with tests passing and a reproducibility checklist.
2. `outputs/metrics.json`, calibration figure, provider O/E table.
3. Power BI file (`dashboard/readmissions.pbix`) plus screenshots.
4. One-page manager memo (`docs/manager_memo_template.md` filled in).
