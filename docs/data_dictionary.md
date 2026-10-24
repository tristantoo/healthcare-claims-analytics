# Data dictionary

Source codes from the [DE-SynPUF codebook](https://www.cms.gov/files/document/de-10-codebook.pdf-0). Only columns the project reads are listed.

## raw.inpatient_claim (from Inpatient Claims CSV)

| Column | Source | Type | Notes |
|---|---|---|---|
| desynpuf_id | DESYNPUF_ID | CHAR(16) | synthetic beneficiary key |
| clm_id | CLM_ID | BIGINT | claim key; with segment forms the PK |
| segment | SEGMENT | TINYINT | 1 = main claim; 2 = continuation (68 rows in Sample 1, no from/thru dates); only 1 is used |
| admit_dt | CLM_ADMSN_DT | DATE | admission date; never null in Sample 1 |
| discharge_dt | NCH_BENE_DSCHRG_DT | DATE | discharge date; never before admit_dt |
| prvdr_num | PRVDR_NUM | VARCHAR(10) | synthetic provider number; 2,675 distinct in Sample 1 |
| clm_pmt_amt | CLM_PMT_AMT | DECIMAL(12,2) | Medicare payment; 55 negative values (adjustments) |
| clm_drg_cd | CLM_DRG_CD | VARCHAR(3) | DRG; includes 'OTH' |
| icd9_dgns_cd_1..10 | ICD9_DGNS_CD_1..10 | VARCHAR(5) | ICD-9-CM diagnosis codes, no decimal point |

## raw.beneficiary_year (from Beneficiary Summary CSVs, one per year)

| Column | Source | Type | Notes |
|---|---|---|---|
| desynpuf_id, file_year | DESYNPUF_ID, file name | CHAR(16), SMALLINT | PK |
| birth_dt | BENE_BIRTH_DT | DATE | |
| death_dt | BENE_DEATH_DT | DATE | month-level; null if alive |
| sex_cd | BENE_SEX_IDENT_CD | CHAR(1) | 1 male, 2 female |
| race_cd | BENE_RACE_CD | CHAR(1) | 1 white, 2 black, 3 other, 5 Hispanic |
| esrd_ind | BENE_ESRD_IND | CHAR(1) | 'Y' or '0' |
| hi_cov_mos | BENE_HI_CVRAGE_TOT_MONS | TINYINT | Part A months in year |
| hmo_cov_mos | BENE_HMO_CVRAGE_TOT_MONS | TINYINT | HMO months; claims are incomplete when > 0 |
| medreimb_ip | MEDREIMB_IP | DECIMAL | annual inpatient Medicare reimbursement |
| sp_* (11) | SP_ALZHDMTA ... SP_STRKETIA | TINYINT | chronic condition flags, 1 yes, 2 no |

## mart.ip_stay

| Column | Definition |
|---|---|
| stay_seq | stay number within beneficiary after transfer merge |
| admit_dt, discharge_dt | min admit, max discharge across merged claims |
| prvdr_num, drg | from the last (discharging) claim |
| paid | sum of claim payments |
| n_dx | max count of non-null diagnosis codes on any claim in the stay |
| los_days | discharge_dt minus admit_dt |
| days_to_next_admit | days from discharge to the next stay's admission; null if none |
| prior_stays_365 | stays discharged in the 365 days before this admission |

## mart.index_stay (and `outputs/index_stays_scored.csv`)

| Column | Definition |
|---|---|
| split | train = 2009 discharges; test = 2010-01-01 to 2010-12-01 |
| readmit_30 | 1 if days_to_next_admit is 30 or less |
| died_30 | 1 if month-level death date falls within 30 days of discharge |
| age | years at discharge |
| female, esrd, sp_* | from the prior-year beneficiary file |
| p_glm, p_gbm, p_base | predicted readmission probability (CSV and mart.index_stay_score) |

The SQL table keeps a subset of features (age, sex, ESRD, CHF, diabetes, LOS, prior stays) for dashboard slicing; the CSV has all model features.

## outputs/

| File | Content |
|---|---|
| metrics.json | sizes, protocol, test metrics per model, bootstrap deltas |
| attrition.csv | rows after each exclusion step |
| glm_coefficients.csv | GLM estimates, SE, z, p, 95% CI |
| calibration_glm.csv, calibration_gbm.csv | decile reliability tables |
| glm_binned_residuals.csv | 20 bins with +/- 2 SE |
| provider_oe.csv | O/E by hospital, test year, 25+ stays, exact Poisson CI |
| monthly_readmission.csv | monthly observed and expected readmissions |
| calibration.png | reliability diagram and binned residual plot |
