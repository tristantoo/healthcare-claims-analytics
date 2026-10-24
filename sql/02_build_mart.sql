/* 02_build_mart.sql: stays (gaps and islands), PCR-style index stays, 30-day readmission flag.
   Same rules as src/claims/cohort.py; scripts/load_sqlserver.py reconciles the two. */

TRUNCATE TABLE mart.ip_stay;
TRUNCATE TABLE mart.index_stay;
TRUNCATE TABLE mart.attrition;
GO

-- 1. Merge direct transfers: a claim admitted within 1 day of the running max discharge joins the stay.
WITH c AS (
    SELECT desynpuf_id, clm_id, admit_dt, discharge_dt, prvdr_num, clm_drg_cd,
           ISNULL(clm_pmt_amt, 0) AS paid,
           (SELECT COUNT(x) FROM (VALUES (icd9_dgns_cd_1),(icd9_dgns_cd_2),(icd9_dgns_cd_3),(icd9_dgns_cd_4),
                   (icd9_dgns_cd_5),(icd9_dgns_cd_6),(icd9_dgns_cd_7),(icd9_dgns_cd_8),(icd9_dgns_cd_9),
                   (icd9_dgns_cd_10)) v(x)) AS n_dx,
           MAX(discharge_dt) OVER (PARTITION BY desynpuf_id ORDER BY admit_dt, discharge_dt, clm_id
                                   ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prev_max_dis
    FROM raw.inpatient_claim
    WHERE segment = 1
), islands AS (
    SELECT *,
           SUM(CASE WHEN prev_max_dis IS NULL OR admit_dt > DATEADD(day, 1, prev_max_dis) THEN 1 ELSE 0 END)
               OVER (PARTITION BY desynpuf_id ORDER BY admit_dt, discharge_dt, clm_id ROWS UNBOUNDED PRECEDING) AS stay_seq
    FROM c
), ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY desynpuf_id, stay_seq
                                 ORDER BY admit_dt DESC, discharge_dt DESC, clm_id DESC) AS rn_last
    FROM islands
), stays AS (
    SELECT desynpuf_id, stay_seq,
           MIN(admit_dt) AS admit_dt, MAX(discharge_dt) AS discharge_dt,
           MAX(CASE WHEN rn_last = 1 THEN prvdr_num END) AS prvdr_num,
           MAX(CASE WHEN rn_last = 1 THEN clm_drg_cd END) AS drg,
           SUM(paid) AS paid, MAX(n_dx) AS n_dx, COUNT(*) AS n_claims
    FROM ranked
    GROUP BY desynpuf_id, stay_seq
)
SELECT * INTO #stays FROM stays;   -- materialize: a CTE in the subquery below would be re-evaluated per row
CREATE CLUSTERED INDEX ix ON #stays (desynpuf_id, discharge_dt);

INSERT mart.ip_stay (desynpuf_id, stay_seq, admit_dt, discharge_dt, prvdr_num, drg, paid, n_dx, n_claims,
                     los_days, days_to_next_admit, prior_stays_365)
SELECT s.desynpuf_id, s.stay_seq, s.admit_dt, s.discharge_dt, s.prvdr_num, s.drg, s.paid, s.n_dx, s.n_claims,
       DATEDIFF(day, s.admit_dt, s.discharge_dt),
       DATEDIFF(day, s.discharge_dt, LEAD(s.admit_dt) OVER (PARTITION BY s.desynpuf_id ORDER BY s.stay_seq)),
       (SELECT COUNT(*) FROM #stays p
         WHERE p.desynpuf_id = s.desynpuf_id
           AND p.discharge_dt < s.admit_dt
           AND p.discharge_dt >= DATEADD(day, -365, s.admit_dt))
FROM #stays s;

DROP TABLE #stays;
GO

-- 2. Index stays for train (2009 discharges) and test (2010 discharges through Dec 1), with attrition.
WITH death AS (
    SELECT desynpuf_id, MAX(death_dt) AS death_dt FROM raw.beneficiary_year GROUP BY desynpuf_id
), w AS (
    SELECT s.*, CASE WHEN s.discharge_dt <= '2009-12-31' THEN 'train' ELSE 'test' END AS split
    FROM mart.ip_stay s
    WHERE s.discharge_dt BETWEEN '2009-01-01' AND '2010-12-01'
), j AS (
    SELECT w.*, b.birth_dt, b.sex_cd, b.esrd_ind, b.sp_chf, b.sp_diabetes, d.death_dt,
           CASE WHEN b.desynpuf_id IS NOT NULL THEN 1 ELSE 0 END AS has_prior,
           CASE WHEN b.hi_cov_mos = 12 AND b.hmo_cov_mos = 0 THEN 1 ELSE 0 END AS full_ffs,
           CASE WHEN d.death_dt IS NULL OR d.death_dt > w.discharge_dt THEN 1 ELSE 0 END AS alive
    FROM w
    LEFT JOIN raw.beneficiary_year b ON b.desynpuf_id = w.desynpuf_id AND b.file_year = YEAR(w.discharge_dt) - 1
    LEFT JOIN death d ON d.desynpuf_id = w.desynpuf_id
)
SELECT * INTO #j FROM j;

INSERT mart.attrition (split, step_no, step, n)
SELECT split, v.step_no, v.step, SUM(v.ok)
FROM #j
CROSS APPLY (VALUES (1, 'discharge in window', 1),
                    (2, 'has prior-year beneficiary record', has_prior),
                    (3, '12 months Part A, no HMO, prior year', has_prior * full_ffs),
                    (4, 'alive at discharge', has_prior * full_ffs * alive)) v(step_no, step, ok)
GROUP BY split, v.step_no, v.step;

INSERT mart.index_stay (desynpuf_id, stay_seq, split, discharge_dt, prvdr_num, readmit_30, died_30, age,
                        female, esrd, sp_chf, sp_diabetes, los_days, prior_stays_365)
SELECT desynpuf_id, stay_seq, split, discharge_dt, prvdr_num,
       CASE WHEN days_to_next_admit <= 30 THEN 1 ELSE 0 END,
       CASE WHEN DATEDIFF(day, discharge_dt, death_dt) <= 30 THEN 1 ELSE 0 END,
       DATEDIFF(day, birth_dt, discharge_dt) / 365.25,
       CASE WHEN sex_cd = '2' THEN 1 ELSE 0 END, CASE WHEN esrd_ind = 'Y' THEN 1 ELSE 0 END,
       CASE WHEN sp_chf = 1 THEN 1 ELSE 0 END, CASE WHEN sp_diabetes = 1 THEN 1 ELSE 0 END,
       los_days, prior_stays_365
FROM #j
WHERE has_prior = 1 AND full_ffs = 1 AND alive = 1;

DROP TABLE #j;
GO
